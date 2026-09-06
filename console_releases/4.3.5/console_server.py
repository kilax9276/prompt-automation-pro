#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

from aiohttp import WSMsgType, web

from executor import RunExecutor, StepError
from delivery_manager import DeliveryError, DeliveryManager
from protocol_engine import parse_user_action_payload

VERSION = "4.3.5"
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

    def list_runs(self) -> list[dict[str, Any]]:
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
                "workflowStatus": (execution or {}).get("workflowStatus"),
                "blockedBy": (execution or {}).get("blockedBy"),
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
        }

    def scan_fingerprint(self) -> str:
        rows = self.list_runs()
        stable = [
            (x["runId"], x["mtimeNs"], x.get("receiverStatus"), x.get("workflowStatus"), x.get("blockedBy"))
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
            except Exception as exc:
                await self.publish({"type": "server:error", "error": f"delivery watcher: {exc}"})
            await asyncio.sleep(0.75)

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
        return web.json_response({"ok": True, "runs": self.list_runs(), "revision": self.revision})

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
            result = await self.executor.execute_step(run_id, step_id, options)
            return web.json_response({"ok": True, "step": result})
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

    async def api_log(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        try:
            text = self.executor.terminal_command_log_text(request.match_info["run_id"], request.match_info["step_id"])
        except StepError:
            raise web.HTTPNotFound(text="log not found")
        return web.Response(text=text, content_type="text/plain")

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
        return web.Response(text=text, content_type="text/plain")

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

    async def api_delivery_prepare(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            result = self.executor.load_result(run_id)
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
            )
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except (DeliveryError, StepError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def api_delivery_retry(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            job = self.delivery.retry_failed(run_id, job_id)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def api_delivery_send(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            job = self.delivery.request_send(run_id, job_id)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
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

    async def api_delivery_poll(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        query = request.rel_url.query
        try:
            tab_id = int(query.get("tabId") or -1)
        except Exception:
            return web.json_response({"ok": False, "error": "invalid tabId"}, status=400)
        page = str(query.get("page") or "")
        job = self.delivery.poll_for_tab(tab_id, page)
        return web.json_response({"ok": True, "job": job})

    async def api_delivery_event(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
            job = self.delivery.update_from_client(run_id, job_id, body)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def api_delivery_chunk(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        attachment_id = request.match_info["attachment_id"]
        query = request.rel_url.query
        try:
            offset = int(query.get("offset") or 0)
            limit = int(query.get("limit") or 512 * 1024)
            body = self.delivery.attachment_chunk(run_id, job_id, attachment_id, offset, limit)
            return web.json_response(body)
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

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
