#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

from aiohttp import WSMsgType, web

from executor import RunExecutor, StepError
from delivery_manager import DeliveryError, DeliveryManager
from protocol_engine import parse_user_action_payload
from profile_store import ProfileActivationStore, ProfileError, ProfileSessionStore, ProfileSnapshotStore, ProfileStore, atomic_write_json
from chat_bindings import ChatBindingError, ChatBindingsStore
from endpoint_registry import EndpointError, EndpointRegistry
from run_profile_context import ProfileAuthorizationError, RunProfileContext

VERSION = "4.5.0-s2"

# The extension half of slice 2 ships as its own release; server and extension
# are switched together, so the server names the one version it can speak to.
# The wire compatibility version is the numeric manifest version. The repo
# release directory carries the -s2 label; the protocol does not.
REQUIRED_EXTENSION_VERSION = "2.12.0"
POLL_KINDS = frozenset({"CONTROL_AGENT", "ENDPOINT"})
CONSOLE_SERVER_KEY = web.AppKey("console_server", object)


class ConsoleServer:
    def __init__(self, root: Path, data_dir: Path, token_file: Path) -> None:
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.token_file = token_file.resolve()
        self.instance_id = uuid.uuid4().hex
        self.clients: set[web.WebSocketResponse] = set()
        self.client_run_filters: dict[web.WebSocketResponse, str | None] = {}
        self.revision = 0
        self._last_scan_fingerprint = ""
        self._watcher_task: asyncio.Task | None = None
        self.executor = RunExecutor(self.root, self.data_dir, self.publish)
        self.delivery = DeliveryManager(self.root, self.data_dir, self.executor.build_full_run_log, self.instance_id)
        self.profiles = ProfileStore(self.root)
        self.snapshots = ProfileSnapshotStore(self.root, self.profiles)
        self.sessions = ProfileSessionStore(self.root, self.snapshots)
        self.activations = ProfileActivationStore(self.root)
        self.bindings = ChatBindingsStore(self.root, self.profiles)
        self.endpoints = EndpointRegistry(self.root)
        self.profile_context = RunProfileContext(self.root, self.data_dir, self.profiles, self.bindings, self.endpoints, self.snapshots, self.sessions)

    def token(self) -> str:
        try:
            return self.token_file.read_text("utf-8").strip()
        except Exception:
            return ""

    def is_authorized(self, request: web.Request) -> bool:
        expected = self.token()
        if not expected:
            return False
        return request.headers.get("Authorization", "") == f"Bearer {expected}"

    def require_auth(self, request: web.Request) -> None:
        if not self.is_authorized(request):
            raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "unauthorized"}), content_type="application/json")

    async def publish(self, event: dict[str, Any]) -> None:
        self.revision += 1
        payload = {
            "revision": self.revision,
            "serverInstanceId": self.instance_id,
            **event,
        }
        raw = json.dumps(payload, ensure_ascii=False)
        dead: list[web.WebSocketResponse] = []
        for ws in list(self.clients):
            run_filter = self.client_run_filters.get(ws)
            event_run = payload.get("runId")
            if run_filter and event_run and run_filter != event_run:
                continue
            try:
                await ws.send_str(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
            self.client_run_filters.pop(ws, None)

    def _read_json_file(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return default

    def list_runs(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        if not self.data_dir.is_dir():
            return rows
        for path in self.data_dir.iterdir():
            if not path.is_dir() or not (path / "result.json").is_file():
                continue
            result = self._read_json_file(path / "result.json", {})
            status = self._read_json_file(path / "status.json", {})
            plan = None
            execution = None
            try:
                profile_context = self.profile_context.ensure_run_context(path.name)
            except Exception as exc:
                # Fail closed with its own status. A Run whose context could
                # not be produced is not a Run with a broken chat identity.
                profile_context = {"resolutionStatus": "RUN_CONTEXT_UNAVAILABLE", "blockReason": "RUN_CONTEXT_UNAVAILABLE", "error": str(exc)}
            if profile_id is not None and str(profile_context.get("profileId") or "") != str(profile_id):
                continue
            intake_meta = self._read_json_file(path / "intake-meta.json", {})
            if not isinstance(intake_meta, dict):
                intake_meta = {}
            try:
                plan = self.executor.ensure_plan(path.name)
                execution = self.executor.ensure_state(path.name, plan)
            except Exception:
                pass
            result_mtime_ns = (path / "result.json").stat().st_mtime_ns
            activity_mtime_ns = max(
                result_mtime_ns,
                (path / "status.json").stat().st_mtime_ns if (path / "status.json").exists() else 0,
                self.executor.state_path(path.name).stat().st_mtime_ns if self.executor.state_path(path.name).exists() else 0,
            )
            run_stamp = path.name.split("_", 1)[0]
            stable_run_key = run_stamp if re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", run_stamp) else ""

            rows.append({
                "runId": path.name,
                "page": result.get("page"),
                "chatType": result.get("chatType") or status.get("chatType") or "unknown",
                "chatLabel": result.get("chatLabel") or status.get("chatLabel") or result.get("chatType") or "Unknown",
                "chatConversationId": result.get("chatConversationId") or status.get("chatConversationId"),
                "generatedAt": result.get("generatedAt"),
                "receiverStatus": status.get("status"),
                "expectedFiles": status.get("expectedFiles", 0),
                "completedFiles": status.get("completedFiles", 0),
                "workflowStatus": (execution or {}).get("workflowStatus") if profile_context.get("resolutionStatus") == "RESOLVED" else "BLOCKED",
                "blockedBy": (execution or {}).get("blockedBy"),
                "resolutionStatus": profile_context.get("resolutionStatus"),
                "blockReason": profile_context.get("blockReason"),
                "profileId": profile_context.get("profileId"),
                "profileRole": profile_context.get("role"),
                "sessionId": profile_context.get("sessionId"),
                "snapshotDigest": profile_context.get("snapshotDigest"),
                "duplicateCount": int(intake_meta.get("duplicateCount") or 0),
                "repeatOf": intake_meta.get("repeatOf"),
                "dedupeBypass": bool(intake_meta.get("dedupeBypass")),
                "stepCount": len((plan or {}).get("steps", [])),
                # arrivalOrder never changes when workflow/status files change.
                "arrivalOrder": stable_run_key,
                "arrivalNs": result_mtime_ns,
                # activity mtime is kept only for change detection/WebSocket refresh.
                "mtimeNs": activity_mtime_ns,
            })

        rows.sort(
            key=lambda x: (
                1 if x.get("arrivalOrder") else 0,
                str(x.get("arrivalOrder") or ""),
                int(x.get("arrivalNs") or 0),
                str(x.get("runId") or ""),
            ),
            reverse=True,
        )
        return rows

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run_dir = self.executor.run_dir(run_id)
        if not run_dir.is_dir():
            raise web.HTTPNotFound(text=json.dumps({"ok": False, "error": "run not found"}), content_type="application/json")
        result = self.executor.load_result(run_id)
        status = self._read_json_file(run_dir / "status.json", {})
        plan = self.executor.ensure_plan(run_id)
        state = self.executor.ensure_state(run_id, plan)
        source_files = self.executor.available_source_files(run_id)
        steps = []
        for step in plan.get("steps", []):
            enriched = dict(step)
            if step.get("executable"):
                enriched["execution"] = state.get("steps", {}).get(step["stepId"], {})
            if step.get("type") == "COMMAND_PUT_FILES":
                payload = step.get("payload")
                targets = [str(x) for x in payload] if isinstance(payload, list) else []
                enriched["suggestedMapping"] = self.executor._auto_file_mapping(run_id, targets)
            if step.get("type") == "COMMAND_USER_ACTION_REQ":
                enriched["userAction"] = parse_user_action_payload(step.get("payload"))
            steps.append(enriched)
        return {
            "ok": True,
            "runId": run_id,
            "result": result,
            "receiverStatus": status,
            "plan": {**plan, "steps": steps},
            "execution": state,
            "sourceFiles": source_files,
            "reportSummary": self.delivery.report_summary(plan, state),
            "deliveryJobs": self.delivery.list_jobs(run_id),
            "profileContext": self.profile_context.ensure_run_context(run_id),
            "intakeMeta": self._read_json_file(run_dir / "intake-meta.json", {}),
            "intakeProvenance": self._read_json_file(run_dir / "intake-provenance.json", {}),
        }

    def scan_fingerprint(self) -> str:
        rows = self.list_runs()
        stable = [
            (x["runId"], x["mtimeNs"], x.get("receiverStatus"), x.get("workflowStatus"), x.get("blockedBy"), x.get("resolutionStatus"))
            for x in rows
        ]
        return hashlib.sha256(json.dumps(stable, ensure_ascii=False).encode()).hexdigest()

    async def watcher(self) -> None:
        while True:
            try:
                fingerprint = self.scan_fingerprint()
                if fingerprint != self._last_scan_fingerprint:
                    self._last_scan_fingerprint = fingerprint
                    await self.publish({"type": "runs:update", "runs": self.list_runs()})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.publish({"type": "server:error", "error": f"watcher: {exc}"})
            try:
                stalled = self.delivery.mark_stalled_jobs()
                for job in stalled:
                    await self.publish({"type": "delivery:update", "runId": job.get("runId"), "job": job})
                for job in self._expire_endpoint_waits():
                    await self.publish({"type": "delivery:update", "runId": job.get("runId"), "job": job})
            except Exception as exc:
                await self.publish({"type": "server:error", "error": f"delivery watcher: {exc}"})
            await asyncio.sleep(0.75)

    @staticmethod
    def _parse_utc(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except Exception:
            return None

    def _expire_endpoint_waits(self) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return changed
        now = datetime.now(timezone.utc)
        for run_dir in self.data_dir.iterdir():
            if not run_dir.is_dir():
                continue
            for job in self.delivery.list_jobs(run_dir.name):
                pd = job.get("profileDelivery") if isinstance(job.get("profileDelivery"), dict) else None
                if not pd or str(pd.get("state") or "") != "WAITING_FOR_ENDPOINT":
                    continue
                started = self._parse_utc(pd.get("waitStartedAt"))
                timeout = max(15, int(pd.get("timeoutSec") or 3600))
                if started is None or (now - started).total_seconds() < timeout:
                    continue
                pd["state"] = "ENDPOINT_WAIT_TIMEOUT"
                pd["timedOutAt"] = now.isoformat().replace("+00:00", "Z")
                job["profileDelivery"] = pd
                job["status"] = "CANCELLED"
                job["sendError"] = "ENDPOINT_WAIT_TIMEOUT"
                job["cancelledAt"] = pd["timedOutAt"]
                changed.append(self.delivery.save_job(job))
        return changed

    def _profile_delivery_target_matches(
        self, job: dict[str, Any], endpoint: dict[str, Any]
    ) -> bool:
        target = job.get("target") if isinstance(job.get("target"), dict) else {}
        return str(EndpointRegistry.evaluate(target, endpoint).get("verdict") or "") == "ELIGIBLE"

    def _profile_delivery_selection_matches(self, job: dict[str, Any]) -> bool:
        pd = job.get("profileDelivery") if isinstance(job.get("profileDelivery"), dict) else None
        if not pd:
            return True
        session_id = str(pd.get("deliverySessionId") or "")
        binding_id = str(pd.get("bindingId") or "")
        if not session_id or not binding_id:
            return True
        try:
            relation = self.sessions.selection(session_id, binding_id)
        except ProfileError:
            return False
        if relation is None:
            # Automatic exactly-one selection is not written into the session.
            # The immutable job target is therefore the authority for this
            # already-prepared attempt until an explicit relation appears.
            return True
        target = job.get("target") if isinstance(job.get("target"), dict) else {}
        relation_endpoint_id = str(relation.get("endpointId") or "")
        if relation_endpoint_id == str(target.get("endpointId") or ""):
            return True

        # MAP-034 releases a session-owned endpoint only when its lifecycle is
        # structurally over (CLOSED/EXPIRED).  The selection writer is not
        # rewritten by automatic policy, so poll must apply the same release
        # rule or it would reject the new endpoint that authorize_delivery just
        # selected.  OFFLINE or identity-mismatched endpoints stay sticky.
        relation_endpoint = next(
            (row for row in self.endpoints.list().get("endpoints", [])
             if str(row.get("endpointId") or "") == relation_endpoint_id),
            None,
        )
        if not isinstance(relation_endpoint, dict):
            return False
        verdict = str(EndpointRegistry.evaluate(target, relation_endpoint).get("verdict") or "")
        return verdict == "DEAD_ENDPOINT"

    def _mark_profile_delivery_ready(
        self, job: dict[str, Any], endpoint: dict[str, Any]
    ) -> dict[str, Any]:
        pd = job.get("profileDelivery") if isinstance(job.get("profileDelivery"), dict) else None
        if not pd:
            return job
        if not self._profile_delivery_target_matches(job, endpoint):
            return job
        if not self._profile_delivery_selection_matches(job):
            return job
        if str(pd.get("state") or "") == "WAITING_FOR_ENDPOINT":
            pd["state"] = "READY"
            pd["endpointOnlineAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            job["profileDelivery"] = pd
            return self.delivery.save_job(job)
        return job

    def _profile_job_poll_allowed(
        self, job: dict[str, Any], endpoint: dict[str, Any]
    ) -> bool:
        pd = job.get("profileDelivery") if isinstance(job.get("profileDelivery"), dict) else None
        if pd and str(pd.get("state") or "") == "ENDPOINT_WAIT_TIMEOUT":
            return False
        if not self._profile_delivery_target_matches(job, endpoint):
            return False
        return self._profile_delivery_selection_matches(job)

    async def on_startup(self, app: web.Application) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Safety boundary: a backend restart must never replay an old text/file
        # delivery into a chat. Historical unfinished jobs require an explicit
        # Resume/Prepare action in Web Console.
        self.delivery.pause_unfinished_jobs_after_restart()

        # A new Python process cannot still own subprocesses from the previous
        # Console instance. Resolve stale RUNNING states and recover existing
        # command logs before the first UI scan.
        self.executor.reconcile_orphan_running_steps()

        self._last_scan_fingerprint = self.scan_fingerprint()
        self._watcher_task = asyncio.create_task(self.watcher())

    async def on_cleanup(self, app: web.Application) -> None:
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        for ws in list(self.clients):
            await ws.close(code=1001, message=b"server shutdown")

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "service": "prompt-automation-pro2-console",
            "version": VERSION,
            "serverInstanceId": self.instance_id,
            "websocketClients": len(self.clients),
        })

    async def index(self, request: web.Request) -> web.FileResponse:
        response = web.FileResponse(Path(__file__).resolve().parent / "static" / "index.html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-PAP-Console-Version"] = VERSION
        return response

    async def api_runs(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        profile_id = str(request.rel_url.query.get("profileId") or "").strip() or None
        return web.json_response({"ok": True, "runs": self.list_runs(profile_id), "profileId": profile_id, "revision": self.revision})

    async def api_run(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        return web.json_response(self.run_detail(request.match_info["run_id"]))

    async def api_execute_step(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        step_id = request.match_info["step_id"]
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            body = {}
        options = body if isinstance(body, dict) else {}
        options = dict(options)
        token_value = self.token()
        options["_actor"] = {
            "source": "web-ui",
            "operator": str(request.headers.get("X-PAP-Operator") or "").strip() or "unknown",
            "remoteAddr": str(request.remote or ""),
            "userAgent": str(request.headers.get("User-Agent") or ""),
            "tokenFingerprint": hashlib.sha256(token_value.encode("utf-8")).hexdigest()[:12] if token_value else "",
        }
        try:
            self.profile_context.authorize_execution(run_id)
            result = await self.executor.execute_step(run_id, step_id, options)
            return web.json_response({"ok": True, "step": result})
        except ProfileAuthorizationError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": exc.code, "detail": exc.detail}, status=409)
        except StepError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def api_override_step(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        step_id = request.match_info["step_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            result = await self.executor.override_step(run_id, step_id, str((body or {}).get("note") or ""))
            return web.json_response({"ok": True, "step": result})
        except StepError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_ignore_automatic_error(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        step_id = request.match_info["step_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            result = await self.executor.ignore_automatic_error(
                run_id,
                step_id,
                str((body or {}).get("note") or ""),
            )
            return web.json_response({"ok": True, "step": result})
        except StepError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_cancel_step(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        ok = await self.executor.cancel_step(request.match_info["run_id"], request.match_info["step_id"])
        return web.json_response({"ok": ok})

    @staticmethod
    def truncate_log_text(text: str) -> tuple[str, int]:
        raw = str(text or "").encode("utf-8")
        limit = 50 * 1024
        edge = 25 * 1024
        if len(raw) <= limit:
            return str(text or ""), 0
        head = raw[:edge].decode("utf-8", errors="ignore")
        tail = raw[-edge:].decode("utf-8", errors="ignore")
        kept = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
        omitted = max(0, len(raw) - kept)
        marker = f"\n\n--- PAP2 LOG TRUNCATED: {omitted} BYTES OMITTED ---\n\n"
        return head + marker + tail, omitted

    async def api_log(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            text = self.executor.terminal_command_log_text(request.match_info["run_id"], request.match_info["step_id"])
        except StepError:
            raise web.HTTPNotFound(text="log not found")
        shown, omitted = self.truncate_log_text(text)
        return web.Response(text=shown, content_type="text/plain", headers={"X-PAP-Log-Truncated": "1" if omitted else "0", "X-PAP-Log-Omitted-Bytes": str(omitted)})

    async def api_artifact_text(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        artifact = self.executor.artifact_by_id(request.match_info["run_id"], request.match_info["artifact_id"])
        if not artifact or not artifact.get("isText"):
            raise web.HTTPNotFound(text="text artifact not found")
        path = Path(artifact["snapshotPath"])
        if path.stat().st_size > 5 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "text artifact exceeds 5 MiB copy limit"}, status=413)
        return web.Response(text=path.read_text(artifact.get("encoding") or "utf-8", errors="replace"), content_type="text/plain")

    @staticmethod
    def report_download_name(artifact: dict[str, Any]) -> str:
        explicit = str(artifact.get("downloadName") or "").strip()
        if explicit:
            return Path(explicit).name

        original = str(artifact.get("originalPath") or "").strip()
        snapshot = Path(str(artifact.get("snapshotPath") or artifact.get("name") or "report.bin"))

        if original:
            original_name = Path(original).name or "report"
            if snapshot.name.lower().endswith(".tar.gz") and not original_name.lower().endswith(".tar.gz"):
                return original_name + ".tar.gz"
            return original_name

        name = str(artifact.get("name") or snapshot.name)
        return re.sub(r"^\d{2}_", "", Path(name).name)

    async def api_artifact_download(self, request: web.Request) -> web.StreamResponse:
        self.require_auth(request)
        artifact = self.executor.artifact_by_id(request.match_info["run_id"], request.match_info["artifact_id"])
        if not artifact:
            raise web.HTTPNotFound(text="artifact not found")
        download_name = self.report_download_name(artifact)
        return web.FileResponse(
            Path(artifact["snapshotPath"]),
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
        )

    async def api_source_download(self, request: web.Request) -> web.StreamResponse:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        name = request.match_info["name"]
        source_dir = (self.executor.run_dir(run_id) / "files").resolve()
        path = (source_dir / name).resolve()
        if source_dir not in path.parents or not path.is_file():
            raise web.HTTPNotFound(text="source file not found")
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})

    async def api_full_run_log(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        text = self.executor.build_full_run_log(request.match_info["run_id"])
        shown, omitted = self.truncate_log_text(text)
        return web.Response(text=shown, content_type="text/plain", headers={"X-PAP-Log-Truncated": "1" if omitted else "0", "X-PAP-Log-Omitted-Bytes": str(omitted)})

    async def api_full_run_log_download(self, request: web.Request) -> web.StreamResponse:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        path = self.executor.materialize_full_run_log(run_id)
        safe_name = f"pap2-terminal-{run_id}.log"
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})

    async def api_copy_bundle(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        text = self.executor.copy_bundle(request.match_info["run_id"])
        return web.Response(text=text, content_type="text/plain")

    def _repeat_provenance(self, result: dict[str, Any]) -> dict[str, Any]:
        identity = self.profile_context.resolver.identity_from_result(result, {})
        binding = self.bindings.find_for_chat(str(identity.get("chatType") or ""), str(identity.get("conversationId") or ""))
        state = self.bindings.state()
        provenance: dict[str, Any] = {
            "schemaVersion": 2,
            "capturedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "chatType": identity.get("chatType"),
            "conversationId": identity.get("conversationId"),
            "bindingLookupState": "BOUND" if binding else "UNBOUND",
            "bindingId": binding.get("bindingId") if binding else None,
            "chatBindingsRevision": state.get("revision"),
            "chatBindingsDigest": state.get("digest"),
            "bindingTarget": binding,
            "profileId": binding.get("profileId") if binding else None,
            "role": binding.get("role") if binding else None,
            "sessionId": None,
            "sessionSnapshotDigest": None,
        }
        if binding:
            session = self.sessions.current(str(binding.get("profileId") or ""))
            if session and str(binding.get("bindingId") or "") in {str(x) for x in session.get("bindingIds") or []}:
                provenance.update({
                    "sessionId": session.get("sessionId"),
                    "sessionSnapshotDigest": session.get("snapshotDigest"),
                    "sessionProfileRevision": session.get("profileRevision"),
                    "sessionProfileDigest": session.get("profileDigest"),
                })
            else:
                snap = self.snapshots.publish_current(str(binding.get("profileId") or ""))
                provenance.update({
                    "capturedSnapshotDigest": snap.get("snapshotDigest"),
                    "profileRevision": snap.get("profileRevision"),
                    "profileDigest": snap.get("profileDigest"),
                })
        return provenance

    def repeat_as_new(self, source_id: str) -> dict[str, Any]:
        source = self.executor.run_dir(source_id)
        if not source.is_dir() or not (source / "result.json").is_file():
            raise FileNotFoundError("run not found")
        result = self._read_json_file(source / "result.json", {})
        if not isinstance(result, dict):
            raise ValueError("invalid source run")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        chat_type = re.sub(r"[^A-Za-z0-9._-]+", "-", str(result.get("chatType") or "unknown")).strip("-") or "unknown"
        run_id = f"{stamp}_{chat_type}_{uuid.uuid4().hex[:8]}"
        target = self.executor.run_dir(run_id)
        target.mkdir(mode=0o750)
        try:
            (target / "files").mkdir(mode=0o750)
            for child in (source / "files").iterdir() if (source / "files").is_dir() else []:
                if child.is_file() and not child.is_symlink():
                    shutil.copy2(child, target / "files" / child.name)
            atomic_write_json(target / "result.json", result, mode=0o640)
            status = self._read_json_file(source / "status.json", {})
            status = dict(status) if isinstance(status, dict) else {}
            status["runId"] = run_id
            status["repeatedFrom"] = source_id
            status["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            atomic_write_json(target / "status.json", status, mode=0o640)
            receiver_files = self._read_json_file(source / "receiver-files.json", [])
            if isinstance(receiver_files, list):
                rewritten = []
                for row in receiver_files:
                    if not isinstance(row, dict):
                        continue
                    item = dict(row)
                    if item.get("name"):
                        item["path"] = str(target / "files" / str(item["name"]))
                    rewritten.append(item)
                atomic_write_json(target / "receiver-files.json", rewritten, mode=0o640)
            provenance = self._repeat_provenance(result)
            atomic_write_json(target / "intake-provenance.json", provenance, mode=0o640)
            source_meta = self._read_json_file(source / "intake-meta.json", {})
            atomic_write_json(target / "intake-meta.json", {
                "schemaVersion": 2,
                "fingerprint": (source_meta or {}).get("fingerprint") if isinstance(source_meta, dict) else None,
                "duplicateCount": 0,
                "dedupeBypass": True,
                "repeatOf": source_id,
                "finalizedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }, mode=0o640)
            ctx = self.profile_context.ensure_run_context(run_id)
            if str(ctx.get("resolutionStatus") or "") != "RESOLVED":
                raise RuntimeError(f"repeat-as-new could not establish run context: {ctx.get('blockReason')}")
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return {"runId": run_id, "repeatOf": source_id, "profileContext": ctx}

    async def api_repeat_as_new(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        source_id = request.match_info["run_id"]
        try:
            result = self.repeat_as_new(source_id)
        except FileNotFoundError:
            raise web.HTTPNotFound(text=json.dumps({"ok": False, "error": "run not found"}), content_type="application/json")
        except (ValueError, ProfileError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        await self.publish({"type": "runs:update", "runs": self.list_runs()})
        return web.json_response({"ok": True, **result})

    async def api_delivery_prepare(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            authorization = self.profile_context.authorize_delivery(run_id, allow_wait=True)
            result = dict(self.executor.load_result(run_id))
            endpoint = authorization["endpoint"]
            source = dict(result.get("papSource") or {}) if isinstance(result.get("papSource"), dict) else {}
            source["endpointId"] = str(endpoint.get("endpointId") or "")
            source["browserEpoch"] = str(endpoint.get("browserEpoch") or "")
            source["tabId"] = int(endpoint["tabId"])
            source["url"] = str(endpoint.get("url") or result.get("page") or "")
            source["chatType"] = str(endpoint.get("chatType") or result.get("chatType") or "unknown")
            source["conversationId"] = str(endpoint.get("conversationId") or "")
            source["projectId"] = endpoint.get("projectId")
            result["papSource"] = source
            result["page"] = source["url"] or result.get("page")
            plan = self.executor.ensure_plan(run_id)
            state = self.executor.ensure_state(run_id, plan)
            max_mib = float((body or {}).get("aggregateMaxMiB") or 30)
            stall_seconds = int((body or {}).get("stallTimeoutSeconds") or 120)
            # Normal console delivery always uses the automatic packaging policy.
            # Older UI values such as "open" must not accidentally fan out a
            # large set of small files into individual chat attachments.
            job = self.delivery.create_job(
                run_id, result, plan, state,
                str((body or {}).get("message") or ""),
                "smart_zip",
                int(max_mib * 1024 * 1024),
                stall_seconds,
                delivery_session_id=authorization.get("deliverySessionId"),
                side_effect_key=(
                    f"chat.send:{run_id}:"
                    f"{authorization['binding'].get('bindingId') or 'source'}"
                ),
            )
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            job["profileDelivery"] = {
                "bindingId": authorization["binding"].get("bindingId"),
                "profileId": authorization["profileContext"].get("profileId"),
                "deliverySessionId": authorization.get("deliverySessionId"),
                "state": "WAITING_FOR_ENDPOINT" if authorization.get("waiting") else "READY",
                "waitStartedAt": now if authorization.get("waiting") else None,
                "timeoutSec": int(authorization.get("endpointWaitTimeoutSeconds") or 0) if authorization.get("waiting") else None,
            }
            job = self.delivery.save_job(job)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except ProfileAuthorizationError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": exc.code, "detail": exc.detail}, status=409)
        except (DeliveryError, StepError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def api_delivery_retry(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            authorization = self.profile_context.authorize_delivery(run_id)
            current_job = self.delivery.get_job(run_id, job_id)
            target = current_job.get("target") if isinstance(current_job.get("target"), dict) else {}
            prepared_endpoint_id = str(target.get("endpointId") or "")
            authorized_endpoint_id = str(authorization["endpoint"].get("endpointId") or "")
            if not prepared_endpoint_id or prepared_endpoint_id != authorized_endpoint_id:
                raise ProfileAuthorizationError(
                    "DELIVERY_TARGET_CHANGED",
                    "Prepared delivery endpoint no longer matches the authorized endpoint; prepare delivery again",
                    {"preparedTarget": target, "authorizedEndpoint": authorization["endpoint"]},
                )
            job = self.delivery.retry_failed(run_id, job_id)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except ProfileAuthorizationError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": exc.code, "detail": exc.detail}, status=409)
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_delivery_send(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            authorization = self.profile_context.authorize_delivery(run_id)
            current_job = self.delivery.get_job(run_id, job_id)
            target = current_job.get("target") if isinstance(current_job.get("target"), dict) else {}
            prepared_endpoint_id = str(target.get("endpointId") or "")
            authorized_endpoint_id = str(authorization["endpoint"].get("endpointId") or "")
            if not prepared_endpoint_id or prepared_endpoint_id != authorized_endpoint_id:
                raise ProfileAuthorizationError(
                    "DELIVERY_TARGET_CHANGED",
                    "Prepared delivery endpoint no longer matches the authorized endpoint; prepare delivery again",
                    {"preparedTarget": target, "authorizedEndpoint": authorization["endpoint"]},
                )
            job = self.delivery.request_send(run_id, job_id)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except ProfileAuthorizationError as exc:
            return web.json_response({"ok": False, "error": str(exc), "code": exc.code, "detail": exc.detail}, status=409)
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_delivery_recovery_requeue(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}

            tab_id = int(body.get("tabId") or -1)
            source_run_id = str(body.get("sourceRunId") or "")
            source_job_id = str(body.get("sourceJobId") or "")

            if tab_id < 0:
                return web.json_response(
                    {"ok": False, "error": "missing tabId"},
                    status=400,
                )

            source_job, _ = self.delivery.resolve_recovery_source(
                tab_id=tab_id,
                page_url=str(body.get("page") or ""),
                source_run_id=source_run_id,
                source_job_id=source_job_id,
            )
            source_run_id = str(source_job.get("runId") or source_run_id)
            authorization = self.profile_context.authorize_delivery(source_run_id)
            source_target = source_job.get("target") if isinstance(source_job.get("target"), dict) else {}
            source_endpoint_id = str(source_target.get("endpointId") or "")
            authorized_endpoint_id = str(authorization["endpoint"].get("endpointId") or "")
            if (not source_endpoint_id or source_endpoint_id != authorized_endpoint_id
                    or int(authorization["endpoint"]["tabId"]) != tab_id):
                raise ProfileAuthorizationError(
                    "DELIVERY_TARGET_CHANGED",
                    "Recovery target is no longer the authorized endpoint",
                    {"requestedTabId": tab_id, "sourceTarget": source_target,
                     "authorizedEndpoint": authorization["endpoint"]},
                )

            job = self.delivery.create_recovery_replay(
                tab_id=tab_id,
                page_url=str(body.get("page") or ""),
                source_run_id=source_run_id,
                source_job_id=source_job_id,
                failure_key=str(body.get("failureKey") or ""),
                failure_row_index=str(body.get("failureRowIndex") or ""),
                reason=str(body.get("reason") or ""),
            )

            await self.publish({
                "type": "delivery:update",
                "runId": job.get("runId"),
                "job": job,
            })
            return web.json_response({"ok": True, "job": job})

        except ProfileAuthorizationError as exc:
            return web.json_response(
                {"ok": False, "error": str(exc), "code": exc.code, "detail": exc.detail},
                status=409,
            )
        except DeliveryError as exc:
            return web.json_response(
                {"ok": False, "error": str(exc)},
                status=409,
            )
        except Exception as exc:
            return web.json_response(
                {"ok": False, "error": str(exc)},
                status=500,
            )


    # ---- version mismatch record -----------------------------------------
    #
    # One authoritative record, attached to the endpoint identity, never a
    # second copy on the profile: two copies drift the moment one is cleared.
    # It is a diagnostic fact, not a pause — the pause state does not exist
    # until slice 5, and showing one earlier would show a state the system
    # does not have.

    def _mismatch_path(self) -> Path:
        return self.root / "runtime" / "version-mismatch.json"

    def _record_version_mismatch(self, expected: str, observed: str | None,
                                 endpoint_id: str | None, browser_epoch: str | None) -> None:
        """One record per scope, never a second copy.

        A real 2.11.6 client sends neither endpointId nor browserEpoch, so it
        cannot be keyed by endpoint identity — and inventing one from the URL is
        exactly what the identity rules forbid. Such a client is recorded under
        LEGACY_AGENT: a single row is enough because 4.5 has one control agent.
        A client that already speaks slice-2 identity is recorded under
        ENDPOINT and keyed by it.
        """
        path = self._mismatch_path()
        try:
            body = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        except Exception:
            body = {}
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        scope = "ENDPOINT" if endpoint_id else "LEGACY_AGENT"
        key = f"ENDPOINT:{endpoint_id}" if endpoint_id else "LEGACY_AGENT"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = rows.get(key) if isinstance(rows.get(key), dict) else {}
        rows[key] = {
            "scope": scope,
            "expected": expected,
            "observed": observed,
            "endpointId": endpoint_id,
            "browserEpoch": browser_epoch,
            # Repeated incompatible polls refresh lastSeenAt; they do not
            # multiply events.
            "firstSeenAt": row.get("firstSeenAt") or now,
            "lastSeenAt": now,
        }
        atomic_write_json(path, {"schemaVersion": 1, "mismatches": rows}, mode=0o640)

    def _clear_version_mismatch(self, browser_epoch: str | None, scope: str | None = None) -> None:
        """A compatible handshake clears the active record it proves obsolete.

        A successful CONTROL_AGENT proof clears the LEGACY_AGENT record: the
        agent that could not speak slice 2 has now spoken it. Without this the
        record from a real 2.11.6 client would survive the upgrade for ever,
        because it carries no epoch to match against.
        """
        path = self._mismatch_path()
        if not path.is_file():
            return
        try:
            body = json.loads(path.read_text("utf-8"))
        except Exception:
            return
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        def obsolete(v: dict) -> bool:
            if scope:
                return str(v.get("scope") or "") == scope
            return bool(browser_epoch) and str(v.get("browserEpoch") or "") == str(browser_epoch)
        keep = {k: v for k, v in rows.items() if not obsolete(v)}
        if keep != rows:
            atomic_write_json(path, {"schemaVersion": 1, "mismatches": keep}, mode=0o640)

    def version_mismatches(self) -> list[dict[str, Any]]:
        path = self._mismatch_path()
        if not path.is_file():
            return []
        try:
            body = json.loads(path.read_text("utf-8"))
        except Exception:
            return []
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        return sorted(rows.values(), key=lambda x: str(x.get("firstSeenAt") or ""))


    # ---- browser protocol barrier ----------------------------------------

    def _browser_owner_barrier(self, request: web.Request, *, record_version_mismatch: bool = True):
        """Prove browser protocol version and CONTROL ownership before product mutation.

        A version mismatch may still update its dedicated diagnostic record;
        endpoint and delivery state remain untouched on every refusal.  This is
        the common control-plane prefix for browser operations.  It is
        intentionally separate from the delivery rollout barrier: terminal
        endpoint cleanup must remain possible while delivery is in BARRIER,
        otherwise the operation used to reach quiescence would itself be
        disabled by quiescence.
        """
        query = request.rel_url.query
        extension_version = str(query.get("extensionVersion") or "").strip()
        browser_epoch = str(query.get("browserEpoch") or "").strip()
        endpoint_id = str(query.get("endpointId") or "").strip()

        if extension_version != REQUIRED_EXTENSION_VERSION:
            if record_version_mismatch:
                self._record_version_mismatch(expected=REQUIRED_EXTENSION_VERSION,
                                              observed=extension_version or None,
                                              endpoint_id=endpoint_id or None,
                                              browser_epoch=browser_epoch or None)
            return None, web.json_response(
                {"ok": False, "code": "EXTENSION_VERSION_INCOMPATIBLE",
                 "expected": REQUIRED_EXTENSION_VERSION, "observed": extension_version or None},
                status=409)
        if not browser_epoch:
            return None, web.json_response({"ok": False, "code": "BROWSER_EPOCH_REQUIRED"}, status=400)

        control = self.endpoints.control_check(browser_epoch)
        if control.get("conflict"):
            return None, web.json_response({"ok": False, "code": "CONTROL_AGENT_CONFLICT",
                                            "browserEpoch": browser_epoch,
                                            "heldBy": control.get("heldBy")}, status=409)
        if not control.get("owner"):
            return None, web.json_response({"ok": False, "code": "NOT_CONTROL_OWNER",
                                            "browserEpoch": browser_epoch}, status=409)
        return {"browserEpoch": browser_epoch, "endpointId": endpoint_id or None}, None

    def _browser_barrier(self, request: web.Request, *, require_endpoint: bool):
        """Settle owner, rollout and endpoint state before delivery mutation.

        Shared by every delivery route the browser can reach. Duplicating the
        checks per route is how one of them ends up missing a check and becomes
        a way around all the others.

        Returns a validated context, or a web.Response to send back untouched.
        """
        ctx, refusal = self._browser_owner_barrier(request)
        if refusal is not None:
            return None, refusal
        browser_epoch = str(ctx.get("browserEpoch") or "")
        endpoint_id = str(ctx.get("endpointId") or "")

        rollout = self.delivery.rollout_state()
        if not rollout.get("valid", True):
            # Rollout state that cannot be trusted is not a working mode. A
            # damaged file used to surface as a latched DRAIN, which still
            # permits events for claimed work — so damaging the persisted
            # BARRIER reopened the very plane it had closed.
            return None, web.json_response({"ok": False, "code": "DELIVERY_ROLLOUT_STATE_INVALID",
                                            "error": rollout.get("stateError")}, status=409)
        if rollout.get("mode") == "BARRIER":
            # A real refusal, not a label. Control and diagnostics stay
            # reachable; product delivery does not.
            return None, web.json_response({"ok": False, "code": "DELIVERY_BARRIER"}, status=409)

        if not require_endpoint:
            return {"browserEpoch": browser_epoch, "endpointId": endpoint_id or None}, None

        if not endpoint_id:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)
        row = next((e for e in self.endpoints.list()["endpoints"]
                    if str(e.get("endpointId") or "") == endpoint_id), None)
        if row is None:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_UNKNOWN",
                                            "endpointId": endpoint_id}, status=409)
        if str(row.get("browserEpoch") or "") != browser_epoch:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_EPOCH_MISMATCH",
                                            "endpointId": endpoint_id}, status=409)
        if str(row.get("state") or "") in ("CLOSED", "EXPIRED"):
            # A terminal endpoint must not move delivery state. Its tab is gone;
            # accepting an event for it would attribute the outcome of a
            # delivery to a target that cannot have received it.
            return None, web.json_response({"ok": False, "code": "ENDPOINT_TERMINAL",
                                            "endpointId": endpoint_id,
                                            "state": row.get("state")}, status=409)
        return {"browserEpoch": browser_epoch, "endpointId": endpoint_id, "endpoint": row}, None

    async def api_delivery_poll(self, request: web.Request) -> web.Response:
        """Poll entry point. Every barrier runs before anything is recorded.

        Order matters more than it looks. In 4.4.0 `observe` sat inside a
        `try/except: pass`, so a client of an incompatible version reached the
        registry first and only then failed — and its failure was swallowed. A
        refusal that arrives after the state has already moved is not a refusal.
        Version, kind and ownership are therefore settled here, before observe,
        and outside any swallowing block.
        """
        self.require_auth(request)
        query = request.rel_url.query

        extension_version = str(query.get("extensionVersion") or "").strip()
        poll_kind = str(query.get("pollKind") or "").strip().upper()
        browser_epoch = str(query.get("browserEpoch") or "").strip()

        if extension_version != REQUIRED_EXTENSION_VERSION:
            # Recorded as a durable, single fact rather than an event per poll,
            # so the operator can see which tabs were never updated instead of
            # reading a repeating refusal in a log.
            self._record_version_mismatch(expected=REQUIRED_EXTENSION_VERSION,
                                          observed=extension_version or None,
                                          endpoint_id=str(query.get("endpointId") or "").strip() or None,
                                          browser_epoch=browser_epoch or None)
            return web.json_response(
                {"ok": False, "code": "EXTENSION_VERSION_INCOMPATIBLE",
                 "expected": REQUIRED_EXTENSION_VERSION, "observed": extension_version or None},
                status=409)
        if poll_kind not in POLL_KINDS:
            return web.json_response({"ok": False, "code": "POLL_KIND_INVALID",
                                      "expected": sorted(POLL_KINDS)}, status=400)
        if not browser_epoch:
            return web.json_response({"ok": False, "code": "BROWSER_EPOCH_REQUIRED"}, status=400)

        if poll_kind == "CONTROL_AGENT":
            state = self.endpoints.acquire_control(browser_epoch)
            if not state["owner"]:
                # The loser gets no plan and no delivery. Showing the conflict
                # while handing both epochs a plan would leave two reconcilers
                # competing, which is the situation the lease exists to avoid.
                return web.json_response({"ok": False, "code": "CONTROL_AGENT_CONFLICT",
                                          "browserEpoch": browser_epoch,
                                          "heldBy": state.get("heldBy")}, status=409)
            self._clear_version_mismatch(browser_epoch, scope="LEGACY_AGENT")
            self._clear_version_mismatch(browser_epoch)
            return web.json_response({"ok": True, "controlState": "OWNER",
                                      "browserEpoch": browser_epoch,
                                      "leaseUntil": state["leaseUntil"],
                                      "transferred": state["transferred"],
                                      "reacquired": state.get("reacquired", False),
                                      "expiredEndpoints": state["expiredEndpoints"]})

        # The first ENDPOINT poll is what creates the endpoint, so this branch
        # checks ownership but cannot require the endpoint to exist yet.
        _ctx, refusal = self._browser_barrier(request, require_endpoint=False)
        if refusal is not None:
            return refusal

        endpoint_id = str(query.get("endpointId") or "").strip()
        if not endpoint_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)
        chat_type = str(query.get("chatType") or "").strip()
        conversation_id = str(query.get("conversationId") or "").strip()
        project_id = str(query.get("projectId") or "").strip() or None
        if not chat_type or not conversation_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_IDENTITY_REQUIRED"}, status=400)
        try:
            tab_id = int(query.get("tabId") or -1)
        except Exception:
            return web.json_response({"ok": False, "error": "invalid tabId"}, status=400)
        page = str(query.get("page") or "")
        title = str(query.get("title") or "").strip() or None

        # Deliberately not swallowed. On the new protocol path a registry
        # refusal is the answer, not something to hide behind an empty 200 —
        # that combination is what let a broken call look healthy.
        try:
            observed_endpoint = self.endpoints.observe(
                tab_id, page, endpoint_id=endpoint_id,
                title=title, browser_epoch=browser_epoch,
                chat_type=chat_type, conversation_id=conversation_id,
                project_id=project_id)
        except EndpointError as exc:
            return web.json_response({"ok": False, "code": "ENDPOINT_REJECTED",
                                      "error": str(exc)}, status=409)

        self._clear_version_mismatch(browser_epoch)
        self._expire_endpoint_waits()
        job = self.delivery.poll_for_tab(tab_id, page, endpoint_id)
        if job is not None:
            job = self._mark_profile_delivery_ready(job, observed_endpoint)
            if not self._profile_job_poll_allowed(job, observed_endpoint):
                job = None
        return web.json_response({"ok": True, "job": job})

    async def api_delivery_event(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        ctx, refusal = self._browser_barrier(request, require_endpoint=True)
        if refusal is not None:
            return refusal
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
            # The tab is taken from the endpoint the barrier just validated,
            # never from the request body. Checking endpointId and then trusting
            # a client-supplied tabId made the endpoint identity decorative: an
            # endpoint belonging to one tab could claim and report on a delivery
            # addressed to another simply by naming it.
            body = dict(body)
            body["tabId"] = int(ctx["endpoint"].get("tabId"))
            body["endpointId"] = str(ctx.get("endpointId") or "")
            job = self.delivery.update_from_client(run_id, job_id, body)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def api_delivery_chunk(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        # Attachment bytes are part of a delivery in progress, so the same
        # barrier applies: an incompatible or unowned client must not be able
        # to read them just because this route is not the poll route.
        ctx, refusal = self._browser_barrier(request, require_endpoint=True)
        if refusal is not None:
            return refusal
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        attachment_id = request.match_info["attachment_id"]
        query = request.rel_url.query
        try:
            offset = int(query.get("offset") or 0)
            limit = int(query.get("limit") or 512 * 1024)
            # Reading a chunk is part of performing a delivery, so it needs the
            # same proof as reporting on one: the caller's own tab, and a live
            # lease it holds. Without this a drain still handed out fresh parts
            # of a delivery nobody had claimed.
            body = self.delivery.attachment_chunk(
                run_id, job_id, attachment_id, offset, limit,
                tab_id=int(ctx["endpoint"].get("tabId")),
                lease_token=str(query.get("leaseToken") or "").strip(),
                endpoint_id=str(ctx.get("endpointId") or ""))
            return web.json_response(body)
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    def _actor_name(self, request: web.Request) -> str:
        return str(request.headers.get("X-PAP-Operator") or "").strip() or "unknown"

    async def api_profiles(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        rows = self.profiles.list_profiles()
        bindings = self.bindings.list()
        endpoint_rows = self.endpoints.list().get("endpoints") or []
        run_rows = self.list_runs()
        for row in rows:
            pid = str(row.get("id") or "")
            profile_bindings = [b for b in bindings if str(b.get("profileId") or "") == pid]
            row["bindingCount"] = len(profile_bindings)
            online = 0
            for b in profile_bindings:
                if any(
                    ep.get("online")
                    and str(ep.get("chatType")) == str(b.get("chatType"))
                    and str(ep.get("conversationId") or "") == str(b.get("conversationId") or "")
                    for ep in endpoint_rows
                ):
                    online += 1
            row["onlineBindingCount"] = online
            row["runCount"] = sum(1 for r in run_rows if str(r.get("profileId") or "") == pid)
        return web.json_response({"ok": True, "profiles": rows})

    async def api_profile_create(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            profile = self.profiles.save_profile(body if isinstance(body, dict) else {}, self._actor_name(request), create=True)
            await self.publish({"type": "config:update", "kind": "profiles"})
            return web.json_response({"ok": True, "profile": profile}, status=201)
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_profile_get(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            return web.json_response({"ok": True, "profile": self.profiles.get_profile(request.match_info["profile_id"], include_prompts=True)})
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    async def api_profile_update(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            profile = self.profiles.save_profile(body if isinstance(body, dict) else {}, self._actor_name(request), expected_id=request.match_info["profile_id"], create=False)
            await self.publish({"type": "config:update", "kind": "profiles"})
            return web.json_response({"ok": True, "profile": profile})
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_profile_delete(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        profile_id = request.match_info["profile_id"]
        try:
            self.profiles.delete_profile(profile_id, self._actor_name(request), binding_count=self.bindings.count_for_profile(profile_id))
            await self.publish({"type": "config:update", "kind": "profiles"})
            return web.json_response({"ok": True})
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_profile_secret(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            value = str((body or {}).get("value") or "")
            meta = self.profiles.set_secret(request.match_info["profile_id"], request.match_info["name"], value, self._actor_name(request))
            return web.json_response({"ok": True, "secret": meta})
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_profile_error_test(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            result = self.profiles.test_error_signatures(request.match_info["profile_id"], str((body or {}).get("text") or ""))
            return web.json_response({"ok": True, **result})
        except ProfileError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_bindings(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        state = self.bindings.state()
        return web.json_response({"ok": True, **state})

    async def api_binding_create(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            result = self.bindings.create(body if isinstance(body, dict) else {}, self._actor_name(request))
            await self.publish({"type": "config:update", "kind": "chat-bindings"})
            return web.json_response({"ok": True, **result}, status=201)
        except ChatBindingError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_binding_update(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            body = await request.json()
            result = self.bindings.update(request.match_info["binding_id"], body if isinstance(body, dict) else {}, self._actor_name(request))
            await self.publish({"type": "config:update", "kind": "chat-bindings"})
            return web.json_response({"ok": True, **result})
        except ChatBindingError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_binding_delete(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            self.bindings.delete(request.match_info["binding_id"], self._actor_name(request))
            await self.publish({"type": "config:update", "kind": "chat-bindings"})
            return web.json_response({"ok": True})
        except ChatBindingError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_endpoints(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        data = self.endpoints.list()
        bindings = self.bindings.list()
        for ep in data.get("endpoints") or []:
            ep["binding"] = next((
                b for b in bindings
                if str(b.get("chatType")) == str(ep.get("chatType"))
                and str(b.get("conversationId") or "") == str(ep.get("conversationId") or "")
            ), None)
        return web.json_response({"ok": True, **data})

    async def api_endpoint_close(self, request: web.Request) -> web.Response:
        """Terminally close one endpoint for the current CONTROL owner.

        This is browser control-plane state, not a delivery event.  Version and
        ownership are proven before the endpoint row is examined, and every
        refusal precedes the terminal write.  CLOSED/EXPIRED rows are returned
        unchanged so repeated tab-close delivery is idempotent.
        """
        self.require_auth(request)
        ctx, refusal = self._browser_owner_barrier(request, record_version_mismatch=False)
        if refusal is not None:
            return refusal

        endpoint_id = str(request.rel_url.query.get("endpointId") or "").strip()
        if not endpoint_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)
        browser_epoch = str(ctx.get("browserEpoch") or "")

        row = next((e for e in self.endpoints.list().get("endpoints") or []
                    if str(e.get("endpointId") or "") == endpoint_id), None)
        if row is None:
            return web.json_response({"ok": False, "code": "ENDPOINT_UNKNOWN",
                                      "endpointId": endpoint_id}, status=409)
        if str(row.get("browserEpoch") or "") != browser_epoch:
            return web.json_response({"ok": False, "code": "ENDPOINT_EPOCH_MISMATCH",
                                      "endpointId": endpoint_id}, status=409)

        try:
            endpoint = self.endpoints.close(endpoint_id, browser_epoch)
        except EndpointError as exc:
            # The preflight above and close() execute without an await in one
            # event-loop turn.  This is still fail-closed if persisted state is
            # externally replaced between the two reads.
            return web.json_response({"ok": False, "code": "ENDPOINT_CLOSE_REFUSED",
                                      "error": str(exc)}, status=409)
        return web.json_response({"ok": True, "endpoint": endpoint})

    async def api_select_endpoint(self, request: web.Request) -> web.Response:
        """Select one endpoint for one binding in one live ProfileSession.

        Request authentication is only the outer gate.  The session, profile,
        binding and endpoint are re-read immediately before the write, and any
        refusal occurs before session selection state is mutated.
        """
        self.require_auth(request)
        session_id = str(request.match_info.get("session_id") or "").strip()
        binding_id = str(request.match_info.get("binding_id") or "").strip()
        try:
            body = await request.json()
        except Exception:
            body = {}
        endpoint_id = str((body or {}).get("endpointId") or "").strip() if isinstance(body, dict) else ""
        if not endpoint_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)

        try:
            session = self.sessions.get(session_id)
            if session is None:
                raise ProfileError("profile session not found")
            if str(session.get("state") or "") not in self.sessions.LIVE_STATES:
                raise ProfileError("profile session is not live")
            if binding_id not in {str(x) for x in session.get("bindingIds") or []}:
                raise ProfileError("binding is not part of profile session")

            binding = self.bindings.get(binding_id)
            if binding is None:
                raise ProfileError("chat binding not found")
            if not bool(binding.get("enabled")):
                raise ProfileError("chat binding is disabled")
            profile_id = str(session.get("profileId") or "")
            if str(binding.get("profileId") or "") != profile_id:
                raise ProfileError("binding does not belong to profile session")
            profile = self.profiles.get_profile(profile_id, include_prompts=False)
            if not bool(profile.get("enabled", True)):
                raise ProfileError("profile is disabled")

            endpoint = next((
                row for row in self.endpoints.list().get("endpoints") or []
                if str(row.get("endpointId") or "") == endpoint_id
            ), None)
            if endpoint is None:
                raise EndpointError("endpoint not found")
            if str(endpoint.get("state") or "") in {"CLOSED", "EXPIRED"}:
                raise EndpointError("endpoint is terminal")
            if not bool(endpoint.get("online")):
                raise EndpointError("endpoint is OFFLINE")
            if str(endpoint.get("chatType") or "") != str(binding.get("chatType") or ""):
                raise EndpointError("endpoint chatType does not match binding")
            if str(endpoint.get("conversationId") or "") != str(binding.get("conversationId") or ""):
                raise EndpointError("endpoint conversationId does not match binding")
            binding_project = str(binding.get("projectId") or "")
            if binding_project and str(endpoint.get("projectId") or "") != binding_project:
                raise EndpointError("endpoint projectId does not match binding")

            relation = self.sessions.select_endpoint(
                session_id, binding_id, endpoint_id,
                selected_by=self._actor_name(request), reason="OPERATOR")
        except (ProfileError, EndpointError) as exc:
            return web.json_response({"ok": False, "code": "ENDPOINT_SELECTION_REFUSED",
                                      "error": str(exc)}, status=409)

        await self.publish({"type": "session:update", "sessionId": session_id,
                            "bindingId": binding_id, "endpointId": endpoint_id})
        return web.json_response({"ok": True, "sessionId": session_id,
                                  "bindingId": binding_id, "endpointId": endpoint_id,
                                  "selection": relation, "endpoint": endpoint})

    # api_endpoint_pin / api_endpoint_unpin removed in slice 2. Pinning an
    # endpoint is no longer an operation: selection is a session-binding
    # relation established by selectEndpoint, and leaving a route that can
    # still create the old shape would let the removed semantics back in.

    async def api_config_history(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            limit = int(request.rel_url.query.get("limit") or 300)
        except Exception:
            limit = 300
        return web.json_response({"ok": True, "history": self.profiles.history.list(limit)})

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=2 * 1024 * 1024)
        await ws.prepare(request)
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=10)
        except asyncio.TimeoutError:
            await ws.close(code=4001, message=b"auth timeout")
            return ws
        if msg.type != WSMsgType.TEXT:
            await ws.close(code=4001, message=b"auth required")
            return ws
        try:
            hello = json.loads(msg.data)
        except Exception:
            hello = {}
        if hello.get("type") != "auth" or not secrets.compare_digest(str(hello.get("token") or ""), self.token()):
            await ws.send_json({"type": "auth:error", "error": "unauthorized"})
            await ws.close(code=4003, message=b"unauthorized")
            return ws

        self.clients.add(ws)
        self.client_run_filters[ws] = None
        await ws.send_json({
            "type": "auth:ok",
            "serverInstanceId": self.instance_id,
            "revision": self.revision,
            "runs": self.list_runs(),
        })
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(message.data)
                    except Exception:
                        continue
                    if payload.get("type") == "subscribe:run":
                        run_id = str(payload.get("runId") or "") or None
                        self.client_run_filters[ws] = run_id
                        if run_id:
                            try:
                                await ws.send_json({"type": "run:init", "runId": run_id, "detail": self.run_detail(run_id)})
                            except Exception as exc:
                                await ws.send_json({"type": "run:error", "runId": run_id, "error": str(exc)})
                    elif payload.get("type") == "request:runs":
                        await ws.send_json({"type": "runs:update", "runs": self.list_runs(), "revision": self.revision})
                elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                    break
        finally:
            self.clients.discard(ws)
            self.client_run_filters.pop(ws, None)
        return ws



@web.middleware
async def no_cache_frontend_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-PAP-Console-Version"] = VERSION
    return response

def create_app(root: Path, data_dir: Path, token_file: Path) -> web.Application:
    server = ConsoleServer(root, data_dir, token_file)
    app = web.Application(middlewares=[no_cache_frontend_middleware], client_max_size=2 * 1024 * 1024)
    app[CONSOLE_SERVER_KEY] = server
    static_dir = Path(__file__).resolve().parent / "static"
    app.router.add_get("/", server.index)
    app.router.add_static("/static/", static_dir, show_index=False)
    app.router.add_get("/health", server.health)
    app.router.add_get("/api/runs", server.api_runs)
    app.router.add_get("/api/runs/{run_id}", server.api_run)
    app.router.add_post("/api/runs/{run_id}/repeat-as-new", server.api_repeat_as_new)
    app.router.add_post("/api/runs/{run_id}/steps/{step_id}/execute", server.api_execute_step)
    app.router.add_post("/api/runs/{run_id}/steps/{step_id}/override", server.api_override_step)
    app.router.add_post("/api/runs/{run_id}/steps/{step_id}/ignore-auto-error", server.api_ignore_automatic_error)
    app.router.add_post("/api/runs/{run_id}/steps/{step_id}/cancel", server.api_cancel_step)
    app.router.add_get("/api/runs/{run_id}/steps/{step_id}/log", server.api_log)
    app.router.add_get("/api/runs/{run_id}/artifacts/{artifact_id}/text", server.api_artifact_text)
    app.router.add_get("/api/runs/{run_id}/artifacts/{artifact_id}/download", server.api_artifact_download)
    app.router.add_get("/api/runs/{run_id}/source/{name}/download", server.api_source_download)
    app.router.add_get("/api/runs/{run_id}/full-log", server.api_full_run_log)
    app.router.add_get("/api/runs/{run_id}/full-log/download", server.api_full_run_log_download)
    app.router.add_get("/api/runs/{run_id}/copy-bundle", server.api_copy_bundle)
    app.router.add_post("/api/runs/{run_id}/delivery/prepare", server.api_delivery_prepare)
    app.router.add_post("/api/runs/{run_id}/delivery/{job_id}/retry", server.api_delivery_retry)
    app.router.add_post("/api/runs/{run_id}/delivery/{job_id}/send", server.api_delivery_send)
    app.router.add_post("/api/chat-delivery/recovery/requeue", server.api_delivery_recovery_requeue)
    app.router.add_get("/api/chat-delivery/poll", server.api_delivery_poll)
    app.router.add_post("/api/chat-delivery/jobs/{run_id}/{job_id}/event", server.api_delivery_event)
    app.router.add_get("/api/chat-delivery/jobs/{run_id}/{job_id}/attachments/{attachment_id}/chunk", server.api_delivery_chunk)
    app.router.add_get("/api/profiles", server.api_profiles)
    app.router.add_post("/api/profiles", server.api_profile_create)
    app.router.add_get("/api/profiles/{profile_id}", server.api_profile_get)
    app.router.add_put("/api/profiles/{profile_id}", server.api_profile_update)
    app.router.add_delete("/api/profiles/{profile_id}", server.api_profile_delete)
    app.router.add_post("/api/profiles/{profile_id}/secrets/{name}", server.api_profile_secret)
    app.router.add_post("/api/profiles/{profile_id}/error-signatures/test", server.api_profile_error_test)
    app.router.add_get("/api/chat-bindings", server.api_bindings)
    app.router.add_post("/api/chat-bindings", server.api_binding_create)
    app.router.add_put("/api/chat-bindings/{binding_id}", server.api_binding_update)
    app.router.add_delete("/api/chat-bindings/{binding_id}", server.api_binding_delete)
    app.router.add_get("/api/endpoints", server.api_endpoints)
    app.router.add_post("/api/endpoints/close", server.api_endpoint_close)
    app.router.add_post("/api/profile-sessions/{session_id}/bindings/{binding_id}/select-endpoint", server.api_select_endpoint)
    app.router.add_get("/api/config-history", server.api_config_history)
    app.router.add_get("/ws", server.websocket)
    app.on_startup.append(server.on_startup)
    app.on_cleanup.append(server.on_cleanup)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prompt Automation Pro 2 step-by-step Web console")
    parser.add_argument("--root", default="/home/ext_disk/prompt_automation_pro2")
    parser.add_argument("--data-dir", default="/home/ext_disk/prompt_automation_pro2/data")
    parser.add_argument("--token-file", default="/home/ext_disk/prompt_automation_pro2/runtime/token.txt")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8871)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    app = create_app(root, Path(args.data_dir), Path(args.token_file))
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
