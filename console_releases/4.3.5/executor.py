from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
import os
import shutil
import signal
import socket
import sys
import tarfile
import time
import pwd
import grp
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from execution_error_detector import ExecutionErrorDetector

from protocol_engine import (
    CONTROL_TYPES,
    OutputMatcher,
    build_plan,
    evaluate_condition,
    evaluate_condition_partial,
    normalize_filename,
    parse_user_action_payload,
)

PublishFn = Callable[[dict[str, Any]], Awaitable[None]]

POST_EXIT_PIPE_DRAIN_SECONDS = 0.75
PROCESS_EXIT_POLL_SECONDS = 0.10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def detect_text(path: Path, max_probe: int = 256 * 1024) -> tuple[bool, str | None]:
    try:
        raw = path.read_bytes()[:max_probe]
    except Exception:
        return False, None
    if b"\x00" in raw:
        return False, None
    try:
        raw.decode("utf-8")
        return True, "utf-8"
    except UnicodeDecodeError:
        return False, None


class StepError(RuntimeError):
    pass


class RunExecutor:
    def __init__(self, root: Path, data_dir: Path, publish: PublishFn) -> None:
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.publish = publish
        self._locks: dict[str, asyncio.Lock] = {}
        self._processes: dict[tuple[str, str], asyncio.subprocess.Process] = {}
        self._cancel_requested: set[tuple[str, str]] = set()

    def run_dir(self, run_id: str) -> Path:
        candidate = (self.data_dir / run_id).resolve()
        if self.data_dir not in candidate.parents:
            raise StepError("Invalid run id")
        return candidate

    def exec_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "executor"

    def plan_path(self, run_id: str) -> Path:
        return self.exec_dir(run_id) / "plan.json"

    def state_path(self, run_id: str) -> Path:
        return self.exec_dir(run_id) / "state.json"

    def events_path(self, run_id: str) -> Path:
        return self.exec_dir(run_id) / "events.ndjson"

    def _lock(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]

    def load_result(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "result.json"
        if not path.is_file():
            raise StepError("result.json not found")
        return json.loads(path.read_text("utf-8"))

    def ensure_plan(self, run_id: str) -> dict[str, Any]:
        path = self.plan_path(run_id)

        if path.is_file():
            cached = json.loads(path.read_text("utf-8"))
            if cached.get("messageScope") == "LATEST_ASSISTANT_MESSAGE":
                return cached

            cached_steps = cached.get("steps") if isinstance(cached.get("steps"), list) else []
            positions = [
                int(step.get("messagePosition"))
                for step in cached_steps
                if step.get("messagePosition") is not None
            ]

            if positions:
                latest_position = max(positions)
                filtered_steps = [
                    step for step in cached_steps
                    if int(step.get("messagePosition") or -1) == latest_position
                ]
                result = self.load_result(run_id)
                source_messages = result.get("messages") if isinstance(result.get("messages"), list) else []
                cached.update({
                    "schemaVersion": 2,
                    "messageScope": "LATEST_ASSISTANT_MESSAGE",
                    "sourceMessageCount": len(source_messages),
                    "selectedMessagePosition": latest_position,
                    "steps": filtered_steps,
                })
                atomic_write_json(path, cached)
                return cached

            plan = build_plan(self.load_result(run_id))
            atomic_write_json(path, plan)
            return plan

        plan = build_plan(self.load_result(run_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, plan)
        return plan

    def initial_state(self, run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        step_state = {}
        for step in plan.get("steps", []):
            if step.get("executable"):
                step_state[step["stepId"]] = {
                    "status": "PENDING",
                    "updatedAt": utc_now(),
                    "attempts": 0,
                }
        return {
            "schemaVersion": 1,
            "runId": run_id,
            "workflowStatus": "READY",
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
            "blockedBy": None,
            "steps": step_state,
        }

    def ensure_state(self, run_id: str, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self.state_path(run_id)
        plan = plan or self.ensure_plan(run_id)

        if path.is_file():
            state = json.loads(path.read_text("utf-8"))

            if plan.get("messageScope") == "LATEST_ASSISTANT_MESSAGE":
                dirty = False
                valid_ids = {
                    str(step.get("stepId"))
                    for step in plan.get("steps", [])
                    if step.get("executable")
                }

                if state.get("blockedBy") not in valid_ids and state.get("blockedBy") is not None:
                    state["blockedBy"] = None
                    dirty = True

                if state.get("messageScope") != "LATEST_ASSISTANT_MESSAGE":
                    state["messageScope"] = "LATEST_ASSISTANT_MESSAGE"
                    dirty = True

                selected_position = plan.get("selectedMessagePosition")
                if state.get("selectedMessagePosition") != selected_position:
                    state["selectedMessagePosition"] = selected_position
                    dirty = True

                workflow_status = self._derive_workflow_status(plan, state)
                if state.get("workflowStatus") != workflow_status:
                    state["workflowStatus"] = workflow_status
                    dirty = True

                if dirty:
                    atomic_write_json(path, state)

            return state

        state = self.initial_state(run_id, plan)
        state["messageScope"] = plan.get("messageScope")
        state["selectedMessagePosition"] = plan.get("selectedMessagePosition")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, state)
        return state

    def save_state(self, run_id: str, state: dict[str, Any]) -> None:
        state["updatedAt"] = utc_now()
        atomic_write_json(self.state_path(run_id), state)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        payload = {"at": utc_now(), **event}
        path = self.events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def get_step(self, plan: dict[str, Any], step_id: str) -> dict[str, Any]:
        for step in plan.get("steps", []):
            if step.get("stepId") == step_id:
                return step
        raise StepError(f"Unknown step {step_id}")

    def _prior_executable_steps(self, plan: dict[str, Any], step: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for candidate in plan.get("steps", []):
            if candidate.get("stepId") == step.get("stepId"):
                break
            if candidate.get("executable"):
                result.append(candidate)
        return result

    def assert_can_execute(self, plan: dict[str, Any], state: dict[str, Any], step: dict[str, Any]) -> None:
        current = state.get("steps", {}).get(step["stepId"], {})
        if current.get("status") == "RUNNING":
            raise StepError("Step already running")
        if current.get("status") in {"DONE", "DONE_WITH_WARNINGS", "HANDLED", "OVERRIDDEN"}:
            raise StepError("Step already completed")

        # COMMAND_GET_REPORTS is an ALWAYS-RUN finalizer. A failed/STOPped normal
        # step must never prevent us from collecting diagnostics for the chat.
        # We only refuse while an earlier subprocess is still actively running,
        # because copying reports mid-write can produce a corrupt snapshot.
        if step.get("type") == "COMMAND_GET_REPORTS":
            for prior in self._prior_executable_steps(plan, step):
                prior_status = state.get("steps", {}).get(prior["stepId"], {}).get("status")
                if prior_status == "RUNNING":
                    raise StepError(f"Previous step {prior['stepId']} is still RUNNING")
            return

        if state.get("workflowStatus") == "BLOCKED":
            raise StepError(f"Workflow blocked by {state.get('blockedBy')}")
        for prior in self._prior_executable_steps(plan, step):
            prior_status = state.get("steps", {}).get(prior["stepId"], {}).get("status")
            if prior_status not in {"DONE", "DONE_WITH_WARNINGS", "HANDLED", "OVERRIDDEN"}:
                raise StepError(f"Previous step {prior['stepId']} is {prior_status or 'PENDING'}")

    async def _broadcast(self, run_id: str, event_type: str, **payload: Any) -> None:
        await self.publish({"type": event_type, "runId": run_id, **payload})

    async def execute_step(self, run_id: str, step_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step = self.get_step(plan, step_id)
            if not step.get("executable"):
                raise StepError("Step is display-only")
            self.assert_can_execute(plan, state, step)

            step_state = state["steps"][step_id]
            step_state.update({
                "status": "RUNNING",
                "startedAt": utc_now(),
                "updatedAt": utc_now(),
                "attempts": int(step_state.get("attempts") or 0) + 1,
                "error": None,
            })
            self.save_state(run_id, state)
            self.append_event(run_id, {"type": "STEP_STARTED", "stepId": step_id, "stepType": step.get("type")})
            await self._broadcast(run_id, "step:state", stepId=step_id, step=step_state)

        # Do not hold the run lock while a command runs for minutes/hours.
        try:
            step_type = step.get("type")
            if step_type == "COMMAND_RUN":
                result = await self._execute_command(run_id, step, options)
            elif step_type == "COMMAND_PUT_FILES":
                result = await self._execute_put_files(run_id, step, options)
            elif step_type == "COMMAND_GET_REPORTS":
                result = await self._execute_get_reports(run_id, step)
            elif step_type == "COMMAND_USER_ACTION_REQ":
                result = self._resolve_user_action(step, options)
            elif step_type in CONTROL_TYPES:
                result = self._handle_control(step, options)
            else:
                raise StepError(f"Unsupported executable step type {step_type}")
        except Exception as exc:
            async with self._lock(run_id):
                state = self.ensure_state(run_id, plan)
                step_state = state["steps"][step_id]
                step_state.update({"status": "ERROR", "finishedAt": utc_now(), "error": str(exc)})
                if step.get("type") == "COMMAND_GET_REPORTS":
                    # Report collection failure is visible, but it is never the
                    # reason the workflow is blocked. Preserve an existing blocker.
                    state["reportFinalizerError"] = str(exc)
                    state["workflowStatus"] = self._derive_workflow_status(plan, state)
                else:
                    state["workflowStatus"] = "BLOCKED"
                    state["blockedBy"] = step_id
                self.save_state(run_id, state)
                self.append_event(run_id, {"type": "STEP_ERROR", "stepId": step_id, "error": str(exc)})
            await self._broadcast(run_id, "step:state", stepId=step_id, step=step_state)
            await self._broadcast(run_id, "workflow:state", workflowStatus=state["workflowStatus"], blockedBy=state.get("blockedBy"))
            raise

        async with self._lock(run_id):
            state = self.ensure_state(run_id, plan)
            step_state = state["steps"][step_id]
            final_status = result.pop("_status", "DONE")
            step_state.update(result)
            step_state.update({"status": final_status, "finishedAt": utc_now(), "error": None})

            if final_status in {"STOPPED_BY_CONDITION", "CANCELLED_BY_OPERATOR"}:
                state["workflowStatus"] = "BLOCKED"
                state["blockedBy"] = step_id
            elif step.get("type") == "COMMAND_CURRENT_DEV_COMPLETE":
                state["workflowStatus"] = "COMPLETE"
                state["blockedBy"] = None
            else:
                state["workflowStatus"] = self._derive_workflow_status(plan, state)
                if state["workflowStatus"] != "BLOCKED":
                    state["blockedBy"] = None

            self.save_state(run_id, state)
            self.append_event(run_id, {"type": "STEP_FINISHED", "stepId": step_id, "status": final_status})

        await self._broadcast(run_id, "step:state", stepId=step_id, step=step_state)
        await self._broadcast(run_id, "workflow:state", workflowStatus=state["workflowStatus"], blockedBy=state.get("blockedBy"))
        return step_state

    def _derive_workflow_status(self, plan: dict[str, Any], state: dict[str, Any]) -> str:
        normal_statuses = []
        report_statuses = []
        for step in plan.get("steps", []):
            if not step.get("executable"):
                continue
            status = state.get("steps", {}).get(step["stepId"], {}).get("status", "PENDING")
            if step.get("type") == "COMMAND_GET_REPORTS":
                report_statuses.append(status)
            else:
                normal_statuses.append(status)
        if any(x in {"ERROR", "STOPPED_BY_CONDITION", "CANCELLED_BY_OPERATOR", "INTERRUPTED_BY_BACKEND_RESTART"} for x in normal_statuses):
            return "BLOCKED"
        if any(x == "RUNNING" for x in normal_statuses + report_statuses):
            return "RUNNING"
        normal_complete = bool(normal_statuses) and all(x in {"DONE", "DONE_WITH_WARNINGS", "HANDLED", "OVERRIDDEN"} for x in normal_statuses)
        report_complete = all(x in {"DONE", "DONE_WITH_WARNINGS", "ERROR", "OVERRIDDEN"} for x in report_statuses) if report_statuses else True
        if normal_complete and report_complete:
            if any(x in {"DONE_WITH_WARNINGS", "ERROR"} for x in report_statuses):
                return "COMPLETE_WITH_WARNINGS"
            return "COMPLETE"
        return "READY"

    def _effective_condition(self, step: dict[str, Any]) -> tuple[str | None, str]:
        explicit = step.get("conditionRun")
        if explicit is not None and str(explicit).strip():
            return str(explicit), "EXPLICIT_CONDITION"
        has_stop = step.get("stopRun") is not None
        has_continue = step.get("continueRun") is not None
        if has_stop and has_continue:
            return "STOP_RUN || !CONTINUE_RUN", "COMPATIBILITY_CRITERIA"
        if has_stop:
            return "STOP_RUN", "COMPATIBILITY_CRITERIA"
        if has_continue:
            return "!CONTINUE_RUN", "COMPATIBILITY_CRITERIA"
        return None, "RETURN_CODE"

    def _criteria_payload(
        self,
        step: dict[str, Any],
        matcher: OutputMatcher,
        *,
        final: bool,
        return_code: int | None = None,
        error_detector: ExecutionErrorDetector | None = None,
    ) -> dict[str, Any]:
        match = matcher.result()
        condition_expression, declared_decision_basis = self._effective_condition(step)

        if final:
            condition_result = evaluate_condition(
                condition_expression,
                stop_run=match.stop_run,
                continue_run=match.continue_run,
            ) if condition_expression is not None else None
            if condition_expression is not None:
                declared_stopped = bool(condition_result)
            else:
                declared_stopped = bool(return_code)
            declared_decision = "STOP" if declared_stopped else "NO_STOP"
        else:
            stop_live: bool | None
            continue_live: bool | None

            if matcher.stop_patterns is None:
                stop_live = None
            elif not matcher.stop_patterns:
                stop_live = False
            else:
                stop_live = True if match.stop_run else None

            if matcher.continue_patterns is None:
                continue_live = None
            elif not matcher.continue_patterns:
                continue_live = True
            else:
                continue_live = True if match.continue_run else None

            condition_result = evaluate_condition_partial(
                condition_expression,
                stop_run=stop_live,
                continue_run=continue_live,
            ) if condition_expression is not None else None
            declared_decision = (
                "STOP" if condition_result is True
                else "NO_STOP" if condition_result is False
                else "WAITING"
            )

        automatic_matches = error_detector.result() if error_detector is not None else []
        automatic_reasons: list[dict[str, Any]] = []
        if final and return_code not in (None, 0):
            automatic_reasons.append({
                "id": "RETURN_CODE_NONZERO",
                "description": f"Main shell exited with return code {return_code}",
                "returnCode": return_code,
            })
        automatic_reasons.extend(automatic_matches)
        automatic_error_detected = bool(automatic_reasons)

        if automatic_error_detected:
            decision = "STOP"
            decision_basis = "AUTOMATIC_EXECUTION_ERROR"
        else:
            decision = declared_decision
            decision_basis = declared_decision_basis

        stop_patterns = []
        for row in match.stop_hits:
            found = bool(row["found"])
            stop_patterns.append({
                **row,
                "state": "MATCHED" if found else ("NOT_FOUND" if final else "WAITING"),
            })

        continue_patterns = []
        for row in match.continue_hits:
            found = bool(row["found"])
            continue_patterns.append({
                **row,
                "state": "MATCHED" if found else ("MISSING" if final else "WAITING"),
            })

        return {
            "final": final,
            "decision": decision,
            "decisionBasis": decision_basis,
            "declaredDecision": declared_decision,
            "declaredDecisionBasis": declared_decision_basis,
            "automaticErrorDetected": automatic_error_detected,
            "automaticErrorOverride": automatic_error_detected and declared_decision != "STOP",
            "automaticErrorReasons": automatic_reasons,
            "returnCode": return_code if final else None,
            "stopRun": match.stop_run,
            "continueRun": match.continue_run,
            "conditionRun": step.get("conditionRun"),
            "effectiveCondition": condition_expression,
            "conditionResult": condition_result,
            "stopPatterns": stop_patterns,
            "continuePatterns": continue_patterns,
            "stopMatched": sum(1 for x in stop_patterns if x["found"]),
            "stopTotal": len(stop_patterns),
            "continueMatched": sum(1 for x in continue_patterns if x["found"]),
            "continueTotal": len(continue_patterns),
        }

    async def _publish_live_criteria(
        self,
        run_id: str,
        step_id: str,
        criteria: dict[str, Any],
    ) -> None:
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step_state = state.get("steps", {}).get(step_id)
            if isinstance(step_state, dict) and step_state.get("status") == "RUNNING":
                step_state["criteria"] = criteria
                step_state["updatedAt"] = utc_now()
                self.save_state(run_id, state)
        self.append_event(run_id, {
            "type": "STEP_CRITERIA",
            "stepId": step_id,
            "criteria": criteria,
        })
        await self._broadcast(run_id, "step:criteria", stepId=step_id, criteria=criteria)

    def _execution_audit(self, options: dict[str, Any], proc_pid: int) -> dict[str, Any]:
        actor = options.get("_actor") if isinstance(options.get("_actor"), dict) else {}
        try:
            user_name = pwd.getpwuid(os.geteuid()).pw_name
        except Exception:
            user_name = str(os.geteuid())
        try:
            group_name = grp.getgrgid(os.getegid()).gr_name
        except Exception:
            group_name = str(os.getegid())
        group_names: list[str] = []
        for gid in os.getgroups():
            try:
                group_names.append(grp.getgrgid(gid).gr_name)
            except Exception:
                group_names.append(str(gid))
        conda_env = str(os.environ.get("CONDA_DEFAULT_ENV") or "")
        return {
            "operator": str(actor.get("operator") or "unknown"),
            "requestSource": str(actor.get("source") or "internal-api"),
            "remoteAddr": str(actor.get("remoteAddr") or ""),
            "userAgent": str(actor.get("userAgent") or ""),
            "tokenFingerprint": str(actor.get("tokenFingerprint") or ""),
            "execUser": user_name,
            "uid": os.geteuid(),
            "execGroup": group_name,
            "gid": os.getegid(),
            "groups": group_names,
            "host": socket.gethostname(),
            "cwd": str(self.root),
            "condaEnv": conda_env,
            "shell": "/bin/bash --noprofile --norc -c",
            "python": sys.executable,
            "consolePid": os.getpid(),
            "commandPid": proc_pid,
            "startedAt": utc_now(),
        }

    def _prompt_lines(self, command: str, audit: dict[str, Any]) -> str:
        env_prefix = f"({audit.get('condaEnv')}) " if audit.get("condaEnv") else ""
        prompt = f"{env_prefix}{audit.get('execUser')}@{audit.get('host')}:{audit.get('cwd')}$ "
        lines = command.splitlines() or [""]
        rendered = [prompt + lines[0]]
        rendered.extend("> " + line for line in lines[1:])
        return "\n".join(rendered) + "\n"

    def _audit_header(self, command: str, audit: dict[str, Any]) -> str:
        groups = ",".join(str(x) for x in audit.get("groups") or [])
        rows = [
            "===== PAP COMMAND START =====",
            f"UTC_START: {audit.get('startedAt')}",
            f"OPERATOR: {audit.get('operator')}",
            f"REQUEST_SOURCE: {audit.get('requestSource')}",
            f"REMOTE_ADDR: {audit.get('remoteAddr')}",
            f"USER_AGENT: {audit.get('userAgent')}",
            f"TOKEN_FINGERPRINT: {audit.get('tokenFingerprint')}",
            f"EXEC_USER: {audit.get('execUser')}",
            f"EXEC_UID: {audit.get('uid')}",
            f"EXEC_GROUP: {audit.get('execGroup')}",
            f"EXEC_GID: {audit.get('gid')}",
            f"EXEC_GROUPS: {groups}",
            f"HOST: {audit.get('host')}",
            f"CWD: {audit.get('cwd')}",
            f"CONDA_ENV: {audit.get('condaEnv') or '-'}",
            f"SHELL: {audit.get('shell')}",
            f"PYTHON: {audit.get('python')}",
            f"CONSOLE_PID: {audit.get('consolePid')}",
            f"COMMAND_PID: {audit.get('commandPid')}",
            "",
            self._prompt_lines(command, audit).rstrip("\n"),
            "===== PAP COMMAND OUTPUT =====",
            "",
        ]
        return "\n".join(rows) + "\n"

    def _audit_footer(self, audit: dict[str, Any], criteria: dict[str, Any], return_code: int) -> str:
        finished = utc_now()
        return "\n".join([
            "",
            "===== PAP COMMAND END =====",
            f"UTC_END: {finished}",
            f"OPERATOR: {audit.get('operator')}",
            f"EXEC_USER: {audit.get('execUser')}",
            f"COMMAND_PID: {audit.get('commandPid')}",
            f"RETURN_CODE: {return_code}",
            f"STOP_RUN: {criteria.get('stopRun')}",
            f"CONTINUE_RUN: {criteria.get('continueRun')}",
            f"CONDITION_RUN: {criteria.get('effectiveCondition') or '-'}",
            f"CONDITION_RESULT: {criteria.get('conditionResult')}",
            f"AUTOMATIC_ERROR_DETECTED: {criteria.get('automaticErrorDetected')}",
            "AUTOMATIC_ERROR_IDS: " + ",".join(
                str(row.get("id"))
                for row in (criteria.get("automaticErrorReasons") or [])
                if isinstance(row, dict) and row.get("id")
            ),
            f"DECISION: {criteria.get('decision')}",
            "===== PAP COMMAND CLOSED =====",
            "",
        ]) + "\n"

    async def _publish_live_audit(self, run_id: str, step_id: str, audit: dict[str, Any]) -> None:
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step_state = state.get("steps", {}).get(step_id)
            if isinstance(step_state, dict) and step_state.get("status") == "RUNNING":
                step_state["audit"] = audit
                step_state["updatedAt"] = utc_now()
                self.save_state(run_id, state)
        self.append_event(run_id, {"type": "STEP_AUDIT", "stepId": step_id, "audit": audit})
        await self._broadcast(run_id, "step:audit", stepId=step_id, audit=audit)

    async def _register_live_log_path(
        self,
        run_id: str,
        step_id: str,
        log_path: Path,
        *,
        log_bytes: int = 0,
        output_bytes: int = 0,
    ) -> None:
        """Make a running COMMAND_RUN log immediately available for download."""
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step_state = state.get("steps", {}).get(step_id)
            if not isinstance(step_state, dict):
                return
            step_state["logPath"] = str(log_path)
            step_state["logBytes"] = int(log_bytes)
            step_state["outputBytes"] = int(output_bytes)
            step_state["updatedAt"] = utc_now()
            self.save_state(run_id, state)

    def reconcile_orphan_running_steps(self) -> list[dict[str, Any]]:
        """Resolve stale RUNNING states after Web Console restart."""
        changed: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return changed

        for run_dir in self.data_dir.iterdir():
            if not run_dir.is_dir() or not (run_dir / "result.json").is_file():
                continue

            run_id = run_dir.name
            try:
                plan = self.ensure_plan(run_id)
                state = self.ensure_state(run_id, plan)
            except Exception:
                continue

            dirty = False
            run_changed: list[str] = []

            for step in plan.get("steps", []):
                if not step.get("executable"):
                    continue

                step_id = str(step.get("stepId") or "")
                step_state = state.get("steps", {}).get(step_id)
                if not isinstance(step_state, dict):
                    continue
                if str(step_state.get("status") or "") != "RUNNING":
                    continue

                default_log = self.exec_dir(run_id) / "logs" / f"{step_id}.log"
                if not step_state.get("logPath") and default_log.is_file():
                    step_state["logPath"] = str(default_log)
                    step_state["logBytes"] = default_log.stat().st_size

                step_state["status"] = "INTERRUPTED_BY_BACKEND_RESTART"
                step_state["finishedAt"] = utc_now()
                step_state["updatedAt"] = utc_now()
                step_state["error"] = (
                    "Web Console restarted while this step was RUNNING. "
                    "The previous Console instance can no longer manage that subprocess."
                )
                dirty = True
                run_changed.append(step_id)
                changed.append({"runId": run_id, "stepId": step_id})

            if dirty:
                state["workflowStatus"] = self._derive_workflow_status(plan, state)
                blockers = []
                for step in plan.get("steps", []):
                    step_id = str(step.get("stepId") or "")
                    status = str(
                        state.get("steps", {}).get(step_id, {}).get("status") or ""
                    )
                    if status in {
                        "ERROR",
                        "STOPPED_BY_CONDITION",
                        "CANCELLED_BY_OPERATOR",
                        "INTERRUPTED_BY_BACKEND_RESTART",
                    }:
                        blockers.append(step_id)

                state["blockedBy"] = blockers[0] if blockers else None
                self.save_state(run_id, state)
                self.append_event(
                    run_id,
                    {
                        "type": "ORPHAN_RUNNING_STEPS_RECONCILED",
                        "steps": run_changed,
                    },
                )

        return changed

    async def _execute_command(self, run_id: str, step: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        step_id = step["stepId"]
        command = str(step.get("command") or "")
        if not command.strip():
            raise StepError("COMMAND_RUN body is empty")

        logs_dir = self.exec_dir(run_id) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{step_id}.log"
        matcher = OutputMatcher(step.get("stopRun"), step.get("continueRun"))
        error_detector = ExecutionErrorDetector()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")

        env = os.environ.copy()
        env["PAP_RUN_ID"] = run_id
        env["PAP_STEP_ID"] = step_id

        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            command,
            cwd=str(self.root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self._processes[(run_id, step_id)] = proc
        byte_count = 0
        options = options or {}
        audit = self._execution_audit(options, proc.pid)
        terminal_prompt = self._prompt_lines(command, audit)
        await self._publish_live_audit(run_id, step_id, audit)

        # Publish the initial matcher state immediately after the subprocess is
        # started. The browser can therefore show every STOP/CONTINUE criterion
        # as WAITING before the first byte of stdout/stderr arrives.
        live_criteria = self._criteria_payload(
            step, matcher, final=False, error_detector=error_detector
        )
        await self._publish_live_criteria(run_id, step_id, live_criteria)

        pipe_detached_after_main_exit = False
        read_task: asyncio.Task[bytes] | None = None
        main_exit_at: float | None = None
        key = (run_id, step_id)

        try:
            with log_path.open("wb") as log:
                prompt_bytes = terminal_prompt.encode("utf-8")
                log.write(prompt_bytes)
                log.flush()

                await self._register_live_log_path(
                    run_id,
                    step_id,
                    log_path,
                    log_bytes=log_path.stat().st_size,
                    output_bytes=0,
                )

                await self._broadcast(
                    run_id,
                    "step:log",
                    stepId=step_id,
                    text=terminal_prompt,
                    bytes=byte_count,
                )

                assert proc.stdout is not None
                loop = asyncio.get_running_loop()
                read_task = asyncio.create_task(proc.stdout.read(16384))

                while True:
                    # asyncio Process.wait() is intentionally NOT used as the
                    # main exit detector here. With stdout=PIPE, wait() can be
                    # delayed until inherited pipe descriptors close. The
                    # child watcher updates proc.returncode as soon as the main
                    # bash process itself exits.
                    if proc.returncode is not None and main_exit_at is None:
                        main_exit_at = loop.time()

                    if main_exit_at is not None:
                        elapsed = loop.time() - main_exit_at
                        if elapsed >= POST_EXIT_PIPE_DRAIN_SECONDS:
                            pipe_detached_after_main_exit = not proc.stdout.at_eof()
                            break

                    try:
                        chunk = await asyncio.wait_for(
                            asyncio.shield(read_task),
                            timeout=PROCESS_EXIT_POLL_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        # No stdout in this 100ms slice. This is expected for
                        # long-running foreground commands and also gives us a
                        # chance to observe proc.returncode without waiting for
                        # pipe EOF.
                        continue

                    if not chunk:
                        break

                    log.write(chunk)
                    log.flush()
                    byte_count += len(chunk)
                    text = decoder.decode(chunk)
                    matcher_changed = matcher.feed(text)
                    error_changed = error_detector.feed(text)

                    await self._broadcast(
                        run_id,
                        "step:log",
                        stepId=step_id,
                        text=text,
                        bytes=byte_count,
                    )

                    if matcher_changed or error_changed:
                        live_criteria = self._criteria_payload(
                            step,
                            matcher,
                            final=False,
                            error_detector=error_detector,
                        )
                        await self._publish_live_criteria(
                            run_id,
                            step_id,
                            live_criteria,
                        )

                    read_task = asyncio.create_task(proc.stdout.read(16384))

                if read_task is not None and not read_task.done():
                    read_task.cancel()
                    try:
                        await read_task
                    except asyncio.CancelledError:
                        pass

                if pipe_detached_after_main_exit:
                    # Main bash has exited. Only an inherited descriptor from a
                    # background shell/descendant remains. Proper detached
                    # services already redirect stdout/stderr, so closing our
                    # read transport cannot remove their file-based logs.
                    transport = getattr(proc.stdout, "_transport", None)
                    if transport is not None:
                        transport.close()

                    self.append_event(
                        run_id,
                        {
                            "type": "COMMAND_STDOUT_HELD_AFTER_MAIN_EXIT",
                            "stepId": step_id,
                            "drainGraceMs": int(
                                POST_EXIT_PIPE_DRAIN_SECONDS * 1000
                            ),
                        },
                    )

                tail = decoder.decode(b"", final=True)
                if tail:
                    matcher_changed = matcher.feed(tail)
                    error_changed = error_detector.feed(tail)
                    await self._broadcast(
                        run_id,
                        "step:log",
                        stepId=step_id,
                        text=tail,
                        bytes=byte_count,
                    )
                    if matcher_changed or error_changed:
                        live_criteria = self._criteria_payload(
                            step,
                            matcher,
                            final=False,
                            error_detector=error_detector,
                        )
                        await self._publish_live_criteria(
                            run_id,
                            step_id,
                            live_criteria,
                        )

            # Normally proc.returncode is already set. Fall back to wait() only
            # when stdout reached EOF before the child watcher callback landed.
            if proc.returncode is None:
                return_code = await proc.wait()
            else:
                return_code = int(proc.returncode)

            cancelled_by_operator = key in self._cancel_requested

        finally:
            self._processes.pop(key, None)
            self._cancel_requested.discard(key)

        criteria = self._criteria_payload(
            step,
            matcher,
            final=True,
            return_code=return_code,
            error_detector=error_detector,
        )
        await self._publish_live_criteria(run_id, step_id, criteria)

        if cancelled_by_operator:
            final_status = "CANCELLED_BY_OPERATOR"
        else:
            stopped = criteria["decision"] == "STOP"
            final_status = "STOPPED_BY_CONDITION" if stopped else "DONE"

        return {
            "_status": final_status,
            "returnCode": return_code,
            "logPath": str(log_path),
            "logBytes": log_path.stat().st_size if log_path.exists() else byte_count,
            "outputBytes": byte_count,
            "audit": audit,
            "criteria": criteria,
            "pipeDetachedAfterMainExit": pipe_detached_after_main_exit,
            "pipeDrainGraceMs": int(POST_EXIT_PIPE_DRAIN_SECONDS * 1000),
        }

    def available_source_files(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self.run_dir(run_id)
        files_dir = run_dir / "files"
        if not files_dir.is_dir():
            return []
        status = {}
        try:
            status = json.loads((run_dir / "status.json").read_text("utf-8"))
        except Exception:
            pass
        metadata = {
            str(row.get("name")): row
            for row in (status.get("files") if isinstance(status.get("files"), list) else [])
            if isinstance(row, dict) and row.get("name")
        }
        rows = []
        for path in sorted(files_dir.iterdir(), key=lambda p: (p.stat().st_mtime_ns, p.name.lower())):
            if path.is_file() and not path.name.startswith("."):
                meta = metadata.get(path.name, {})
                rows.append({
                    "name": path.name,
                    "path": str(path),
                    "size": int(meta.get("bytes") or path.stat().st_size),
                    "sha256": meta.get("sha256"),
                })
        return rows

    def _auto_file_mapping(self, run_id: str, targets: list[str]) -> list[dict[str, str]]:
        sources = self.available_source_files(run_id)
        unused = list(sources)
        mapping: list[dict[str, str]] = []
        for target in targets:
            target_name = normalize_filename(Path(target).name)
            exact = next((s for s in unused if normalize_filename(s["name"]) == target_name), None)
            if exact is not None:
                mapping.append({"target": target, "source": exact["name"]})
                unused.remove(exact)
            elif len(unused) == 1:
                mapping.append({"target": target, "source": unused.pop(0)["name"]})
            else:
                mapping.append({"target": target, "source": ""})
        return mapping

    async def _execute_put_files(self, run_id: str, step: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        payload = step.get("payload")
        targets = [str(x) for x in payload] if isinstance(payload, list) else []
        if not targets:
            raise StepError("COMMAND_PUT_FILES has no target paths")

        mapping = options.get("mapping") if isinstance(options.get("mapping"), list) else None
        if mapping is None:
            mapping = self._auto_file_mapping(run_id, targets)
        overwrite = bool(options.get("overwrite", False))

        source_dir = (self.run_dir(run_id) / "files").resolve()
        results = []
        by_target = {str(row.get("target")): row for row in mapping if isinstance(row, dict)}
        for target in targets:
            row = by_target.get(target) or {}
            source_name = str(row.get("source") or "")
            if not source_name:
                raise StepError(f"No source file selected for {target}")
            source = (source_dir / source_name).resolve()
            if source_dir not in source.parents or not source.is_file():
                raise StepError(f"Source file not found: {source_name}")
            destination = Path(target).expanduser()
            if destination.exists() and not overwrite:
                raise StepError(f"Target already exists: {destination}; enable overwrite explicitly")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            src_sha = sha256_file(source)
            dst_sha = sha256_file(destination)
            if src_sha != dst_sha or source.stat().st_size != destination.stat().st_size:
                raise StepError(f"Copy verification failed: {source} -> {destination}")
            result = {
                "source": str(source),
                "target": str(destination),
                "size": destination.stat().st_size,
                "sha256": dst_sha,
            }
            results.append(result)
            await self._broadcast(run_id, "step:file", stepId=step["stepId"], action="PUT", file=result)
        return {"filesPlaced": results}

    async def _execute_get_reports(self, run_id: str, step: dict[str, Any]) -> dict[str, Any]:
        payload = step.get("payload")
        paths = [str(x) for x in payload] if isinstance(payload, list) else []
        if not paths:
            raise StepError("COMMAND_GET_REPORTS has no paths")

        snapshot_dir = self.exec_dir(run_id) / "reports" / step["stepId"]
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        missing = []

        for idx, raw_path in enumerate(paths, start=1):
            source = Path(raw_path).expanduser()
            if not source.exists():
                missing.append(raw_path)
                artifacts.append({"originalPath": raw_path, "present": False})
                continue

            if source.is_dir():
                download_name = f"{source.name or 'directory'}.tar.gz"
                snapshot_name = f"{idx:02d}_{download_name}"
                destination = snapshot_dir / snapshot_name
                with tarfile.open(destination, "w:gz") as tf:
                    tf.add(source, arcname=source.name)
            elif source.is_file():
                download_name = source.name
                snapshot_name = f"{idx:02d}_{download_name}"
                destination = snapshot_dir / snapshot_name
                shutil.copy2(source, destination)
            else:
                missing.append(raw_path)
                artifacts.append({"originalPath": raw_path, "present": False, "reason": "unsupported file type"})
                continue

            is_text, encoding = detect_text(destination)
            artifact_id = f"{step['stepId']}-{idx:02d}"
            metadata = {
                "artifactId": artifact_id,
                "originalPath": raw_path,
                "snapshotPath": str(destination),
                "snapshotName": destination.name,
                "name": download_name,
                "downloadName": download_name,
                "present": True,
                "size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "isText": is_text,
                "encoding": encoding,
            }
            artifacts.append(metadata)
            await self._broadcast(run_id, "step:file", stepId=step["stepId"], action="GET", file=metadata)

        meta_path = snapshot_dir / "artifacts.json"
        atomic_write_json(meta_path, {"artifacts": artifacts, "missing": missing})
        return {
            "_status": "DONE_WITH_WARNINGS" if missing else "DONE",
            "reportArtifacts": artifacts,
            "missingReports": missing,
            "reportMetadataPath": str(meta_path),
        }

    def _resolve_user_action(self, step: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_user_action_payload(step.get("payload"))
        if not bool(options.get("confirmed")):
            raise StepError("User action must be explicitly confirmed")
        return {
            "_status": "HANDLED",
            "forId": parsed.get("forId"),
            "userNote": str(options.get("note") or ""),
            "instruction": parsed.get("text"),
        }

    def _handle_control(self, step: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        if not bool(options.get("confirmed")):
            raise StepError("Control directive must be explicitly marked handled")
        return {
            "_status": "HANDLED",
            "operatorNote": str(options.get("note") or ""),
            "payload": step.get("payload"),
        }

    async def ignore_automatic_error(self, run_id: str, step_id: str, note: str) -> dict[str, Any]:
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step = self.get_step(plan, step_id)
            if step.get("type") != "COMMAND_RUN":
                raise StepError("Automatic execution errors can only be ignored for COMMAND_RUN")

            step_state = state.get("steps", {}).get(step_id)
            if not isinstance(step_state, dict):
                raise StepError("Unknown executable step")
            if step_state.get("status") != "STOPPED_BY_CONDITION":
                raise StepError("Only a stopped COMMAND_RUN can ignore an automatic execution error")

            criteria = step_state.get("criteria") if isinstance(step_state.get("criteria"), dict) else {}
            if not criteria.get("automaticErrorDetected"):
                raise StepError("This step has no automatic execution error to ignore")
            if criteria.get("declaredDecision") == "STOP":
                raise StepError("Declared STOP criteria also require stopping; use the general override to continue")

            ignored_at = utc_now()
            reasons = criteria.get("automaticErrorReasons") if isinstance(criteria.get("automaticErrorReasons"), list) else []
            reason_ids = [
                str(row.get("id"))
                for row in reasons
                if isinstance(row, dict) and row.get("id")
            ]
            step_state.update({
                "status": "OVERRIDDEN",
                "automaticErrorIgnored": True,
                "automaticErrorIgnoredAt": ignored_at,
                "automaticErrorIgnoreNote": str(note or ""),
                "automaticErrorIgnoredReasonIds": reason_ids,
                "overrideNote": str(note or "Automatic execution error ignored by operator"),
                "overriddenAt": ignored_at,
            })
            state["blockedBy"] = None
            state["workflowStatus"] = self._derive_workflow_status(plan, state)
            self.save_state(run_id, state)
            self.append_event(run_id, {
                "type": "AUTOMATIC_ERROR_IGNORED",
                "stepId": step_id,
                "reasonIds": reason_ids,
                "note": str(note or ""),
            })
        await self._broadcast(run_id, "step:state", stepId=step_id, step=step_state)
        await self._broadcast(run_id, "workflow:state", workflowStatus=state["workflowStatus"], blockedBy=None)
        return step_state

    async def override_step(self, run_id: str, step_id: str, note: str) -> dict[str, Any]:
        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step_state = state.get("steps", {}).get(step_id)
            if not step_state:
                raise StepError("Unknown executable step")
            if step_state.get("status") not in {"STOPPED_BY_CONDITION", "ERROR", "CANCELLED_BY_OPERATOR", "INTERRUPTED_BY_BACKEND_RESTART"}:
                raise StepError("Only blocked/error/cancelled/interrupted steps can be overridden")
            step_state.update({
                "status": "OVERRIDDEN",
                "overrideNote": str(note or ""),
                "overriddenAt": utc_now(),
            })
            state["blockedBy"] = None
            state["workflowStatus"] = self._derive_workflow_status(plan, state)
            self.save_state(run_id, state)
            self.append_event(run_id, {"type": "STEP_OVERRIDDEN", "stepId": step_id, "note": note})
        await self._broadcast(run_id, "step:state", stepId=step_id, step=step_state)
        await self._broadcast(run_id, "workflow:state", workflowStatus=state["workflowStatus"], blockedBy=None)
        return step_state

    async def cancel_step(self, run_id: str, step_id: str) -> bool:
        key = (run_id, step_id)
        proc = self._processes.get(key)
        if proc is None:
            return False

        requested_at = utc_now()

        if proc.returncode is None:
            self._cancel_requested.add(key)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                self._cancel_requested.discard(key)
                return False
            event_type = "STEP_CANCEL_REQUESTED"
        else:
            # Main shell is already finished; only an inherited stdout pipe can
            # still keep the UI in RUNNING. Release that pipe immediately.
            stdout = proc.stdout
            transport = getattr(stdout, "_transport", None) if stdout is not None else None
            if transport is not None:
                transport.close()
            event_type = "STEP_PIPE_RELEASE_REQUESTED"

        async with self._lock(run_id):
            plan = self.ensure_plan(run_id)
            state = self.ensure_state(run_id, plan)
            step_state = state.get("steps", {}).get(step_id)
            if isinstance(step_state, dict):
                step_state["cancelRequestedAt"] = requested_at
                step_state["updatedAt"] = utc_now()
                self.save_state(run_id, state)

        self.append_event(
            run_id,
            {
                "type": event_type,
                "stepId": step_id,
                "mainReturnCode": proc.returncode,
            },
        )
        return True

    def artifact_by_id(self, run_id: str, artifact_id: str) -> dict[str, Any] | None:
        state = self.ensure_state(run_id, self.ensure_plan(run_id))
        for step_state in state.get("steps", {}).values():
            for artifact in step_state.get("reportArtifacts") or []:
                if artifact.get("artifactId") == artifact_id and artifact.get("present"):
                    return artifact
        return None

    def command_log_path(self, run_id: str, step_id: str) -> Path | None:
        state = self.ensure_state(run_id, self.ensure_plan(run_id))
        row = state.get("steps", {}).get(step_id) or {}
        raw = row.get("logPath")
        allowed = self.exec_dir(run_id).resolve()

        if raw:
            path = Path(raw).resolve()
            if allowed in path.parents and path.is_file():
                return path

        # Old Console versions created executor/logs/sNNN.log immediately but
        # only persisted logPath after completion. Recover that file so logs of
        # a stopped/hung command are not omitted from full-log downloads.
        fallback = (self.exec_dir(run_id) / "logs" / f"{step_id}.log").resolve()
        if allowed in fallback.parents and fallback.is_file():
            return fallback

        return None

    def full_run_log_path(self, run_id: str) -> Path:
        return self.exec_dir(run_id) / "run-full.log"

    def terminal_command_log_text(self, run_id: str, step_id: str) -> str:
        """Return terminal-only command transcript, including legacy logs.

        v4.1.0 and earlier wrapped persisted command logs in PAP audit headers and
        footers. This reader strips those wrappers and reconstructs only the
        shell prompt + exact parsed command + raw combined stdout/stderr. New
        v4.1.1 logs are already stored in terminal-only form and pass through.
        """
        plan = self.ensure_plan(run_id)
        state = self.ensure_state(run_id, plan)
        step = next((x for x in plan.get("steps", []) if str(x.get("stepId") or "") == step_id), None)
        if not step or str(step.get("type") or "") != "COMMAND_RUN":
            raise StepError("COMMAND_RUN step not found")
        st = state.get("steps", {}).get(step_id, {})
        path = self.command_log_path(run_id, step_id)
        if not path:
            raise StepError("command log not found")
        raw = path.read_text("utf-8", errors="replace")
        output_marker = "===== PAP COMMAND OUTPUT =====\n\n"
        end_marker = "\n===== PAP COMMAND END ====="
        if output_marker not in raw:
            return raw

        before, output_and_footer = raw.split(output_marker, 1)
        output = output_and_footer.split(end_marker, 1)[0] if end_marker in output_and_footer else output_and_footer
        audit = st.get("audit") if isinstance(st.get("audit"), dict) else {}
        if not audit:
            # Fallback for a legacy state file missing the audit object.
            fields: dict[str, str] = {}
            for line in before.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1)
                    fields[key] = value
            audit = {
                "execUser": fields.get("EXEC_USER") or "unknown",
                "host": fields.get("HOST") or socket.gethostname(),
                "cwd": fields.get("CWD") or str(self.root),
                "condaEnv": "" if fields.get("CONDA_ENV") in {None, "-"} else fields.get("CONDA_ENV", ""),
            }
        prompt = self._prompt_lines(str(step.get("command") or ""), audit)
        return prompt + output

    def build_full_run_log(self, run_id: str) -> str:
        """Return only the terminal transcript of executed COMMAND_RUN steps.

        No audit metadata, criteria, executor events, PUT/GET metadata, headers,
        footers or synthetic return-code lines are included. Each command log
        already contains the shell-style prompt, the exact parsed command text,
        and the raw combined stdout+stderr emitted by that command.
        """
        plan = self.ensure_plan(run_id)
        state = self.ensure_state(run_id, plan)
        parts: list[str] = []
        for step in plan.get("steps", []):
            if str(step.get("type") or "") != "COMMAND_RUN":
                continue
            step_id = str(step.get("stepId") or "")
            st = state.get("steps", {}).get(step_id, {})
            # terminal_command_log_text also discovers legacy sNNN.log files,
            # so RUNNING/cancelled commands are not silently omitted.
            try:
                text = self.terminal_command_log_text(run_id, step_id)
            except StepError:
                continue
            if not text:
                continue
            if parts and not parts[-1].endswith("\n"):
                parts[-1] += "\n"
            parts.append(text)
        return "".join(parts)

    def materialize_full_run_log(self, run_id: str) -> Path:
        text = self.build_full_run_log(run_id)
        path = self.full_run_log_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return path

    def copy_bundle(self, run_id: str, max_bytes: int = 1_500_000) -> str:
        result = self.load_result(run_id)
        plan = self.ensure_plan(run_id)
        state = self.ensure_state(run_id, plan)
        parts = [
            f"RUN_ID::{run_id}",
            f"PAGE::{result.get('page') or ''}",
            f"WORKFLOW_STATUS::{state.get('workflowStatus') or ''}",
            "",
        ]
        used = sum(len(x.encode("utf-8")) + 1 for x in parts)

        def add(text: str) -> bool:
            nonlocal used
            encoded = text.encode("utf-8")
            if used + len(encoded) + 1 > max_bytes:
                parts.append("[COPY_BUNDLE_TRUNCATED]")
                return False
            parts.append(text)
            used += len(encoded) + 1
            return True

        for step in plan.get("steps", []):
            st = state.get("steps", {}).get(step.get("stepId"), {})
            if not add(f"=== {step.get('stepId')} {step.get('type')} status={st.get('status','DISPLAY_ONLY')} ==="):
                break
            if step.get("type") == "COMMAND_RUN":
                if not add(str(step.get("command") or "")):
                    break
                criteria = st.get("criteria")
                if criteria is not None and not add("CRITERIA::" + json.dumps(criteria, ensure_ascii=False)):
                    break
                log = self.command_log_path(run_id, step["stepId"])
                if log:
                    remaining = max_bytes - used
                    data = log.read_bytes()[:max(0, remaining)]
                    text = data.decode("utf-8", "replace")
                    if not add("OUTPUT::\n" + text):
                        break
            elif step.get("type") == "COMMAND_GET_REPORTS":
                for artifact in st.get("reportArtifacts") or []:
                    if not artifact.get("present"):
                        if not add(f"MISSING::{artifact.get('originalPath')}"):
                            break
                        continue
                    if not add(
                        f"REPORT::{artifact.get('originalPath')} size={artifact.get('size')} sha256={artifact.get('sha256')}"
                    ):
                        break
                    if artifact.get("isText") and int(artifact.get("size") or 0) <= 500_000:
                        path = Path(artifact["snapshotPath"])
                        try:
                            text = path.read_text(artifact.get("encoding") or "utf-8", errors="replace")
                        except Exception:
                            text = "[unable to read text report]"
                        if not add("REPORT_CONTENT::\n" + text):
                            break
            elif step.get("type") in CONTROL_TYPES or step.get("type") == "COMMAND_USER_ACTION_REQ":
                if not add(str(step.get("payload") or "")):
                    break
            elif step.get("type") == "AFTER_COMMANDS":
                if not add(str(step.get("text") or "")):
                    break
            add("")
        return "\n".join(parts)
