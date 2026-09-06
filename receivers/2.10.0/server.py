#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

VERSION = "2.10.0"
# Keep the historical service id for extension compatibility. Chat-specific
# behavior is now described by chatType/chatLabel metadata instead.
SERVICE = "prompt-automation-pro2-receiver"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def infer_chat_metadata(payload: dict) -> dict:
    """Return normalized chat metadata without depending on DOM details.

    The extension is the primary source of chatType/chatLabel. URL inference is
    deliberately kept here as a compatibility fallback for older clients.
    """
    page = str(payload.get("page") or "")
    raw_type = str(payload.get("chatType") or "").strip().lower()
    raw_label = str(payload.get("chatLabel") or "").strip()
    raw_conversation = str(payload.get("chatConversationId") or payload.get("conversationId") or "").strip()

    host = ""
    path = ""
    try:
        parsed = urlparse(page)
        host = parsed.hostname.lower() if parsed.hostname else ""
        path = parsed.path or ""
    except Exception:
        pass

    inferred_type = "unknown"
    inferred_label = "Unknown"
    inferred_conversation = ""
    if host == "claude.ai" or host.endswith(".claude.ai"):
        inferred_type, inferred_label = "claude", "Claude"
        m = re.search(r"/chat/([^/?#]+)", path, re.I)
        inferred_conversation = m.group(1) if m else ""
    elif host in {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}:
        inferred_type, inferred_label = "chatgpt", "ChatGPT"
        m = re.search(r"/c/([^/?#]+)", path, re.I)
        inferred_conversation = m.group(1) if m else ""

    chat_type = re.sub(r"[^a-z0-9_-]+", "-", raw_type or inferred_type).strip("-") or "unknown"
    chat_type = chat_type[:40]
    default_labels = {"claude": "Claude", "chatgpt": "ChatGPT", "unknown": "Unknown"}
    chat_label = (raw_label or default_labels.get(chat_type) or inferred_label or chat_type)[:80]
    conversation_id = (raw_conversation or inferred_conversation)[:240]
    return {
        "chatType": chat_type,
        "chatLabel": chat_label,
        "chatConversationId": conversation_id or None,
    }


def run_chat_slug(meta: dict) -> str:
    chat_type = re.sub(r"[^A-Za-z0-9._-]+", "-", str(meta.get("chatType") or "unknown")).strip("-") or "unknown"
    conversation = re.sub(r"[^A-Za-z0-9._-]+", "-", str(meta.get("chatConversationId") or "")).strip("-")
    if conversation:
        return f"{chat_type}-{conversation[:72]}"
    return chat_type[:80]


def atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def safe_filename(name: str) -> str:
    name = str(name or "file.bin").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name)
    if not name or name in {".", ".."}:
        name = "file.bin"
    return name[:240]


def unique_destination(files_dir: Path, requested: str) -> Path:
    requested = safe_filename(requested)
    candidate = files_dir / requested
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for i in range(2, 10000):
        c = files_dir / f"{stem}-{i}{suffix}"
        if not c.exists():
            return c
    raise RuntimeError("could not allocate destination name")


class ReceiverServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, data_dir: Path, token: str):
        super().__init__(address, handler)
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.lock = threading.RLock()
        self.uploads: dict[str, dict] = {}

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,180}", str(run_id or "")):
            raise ValueError("invalid runId")
        path = (self.data_dir / run_id).resolve()
        if self.data_dir not in path.parents:
            raise ValueError("invalid runId path")
        return path


class Handler(BaseHTTPRequestHandler):
    server: ReceiverServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[{utc_now_iso()}] {self.client_address[0]} {fmt % args}", flush=True)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization,Content-Type,X-Run-Id,X-File-Name,X-File-Sha256,X-Expected-Sha256,X-File-Mime,X-Upload-Id,X-Chunk-Offset,X-Total-Bytes",
        )
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json(self, status: int, body: object) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        if not self.server.token:
            return False
        return self.headers.get("Authorization", "") == "Bearer " + self.server.token

    def _read_bytes(self, max_bytes: int | None = None) -> bytes:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise ValueError("Content-Length required")
        n = int(raw)
        if n < 0 or (max_bytes is not None and n > max_bytes):
            raise ValueError("invalid Content-Length")
        return self.rfile.read(n)

    def _read_json(self, max_bytes: int = 8 * 1024 * 1024) -> dict:
        raw = self._read_bytes(max_bytes)
        body = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        return body

    def _load_status(self, run_dir: Path, run_id: str) -> dict:
        p = run_dir / "status.json"
        if p.is_file():
            try:
                body = json.loads(p.read_text("utf-8"))
                if isinstance(body, dict):
                    return body
            except Exception:
                pass
        return {"runId": run_id, "status": "UNKNOWN", "expectedFiles": 0, "completedFiles": 0, "files": []}

    def _write_latest_snapshot(self, status: dict) -> None:
        snapshot = {
            "runId": status.get("runId"),
            "status": status.get("status"),
            "expectedFiles": status.get("expectedFiles", 0),
            "completedFiles": status.get("completedFiles", 0),
            "currentUpload": status.get("currentUpload"),
            "error": status.get("error"),
            "chatType": status.get("chatType"),
            "chatLabel": status.get("chatLabel"),
            "chatConversationId": status.get("chatConversationId"),
            "updatedAt": status.get("updatedAt"),
        }
        atomic_write_json(self.server.data_dir / "latest.json", snapshot)

    def _write_status_patch(self, run_id: str, patch: dict) -> dict:
        run_dir = self.server.run_dir(run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError("run not found")
        with self.server.lock:
            status = self._load_status(run_dir, run_id)
            status.update(patch)
            status["runId"] = run_id
            status["updatedAt"] = utc_now_iso()
            atomic_write_json(run_dir / "status.json", status)
            self._write_latest_snapshot(status)
            return status

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(HTTPStatus.OK, {
                "ok": True,
                "service": SERVICE,
                "version": VERSION,
                "supportedChatTypes": ["claude", "chatgpt"],
                "genericChatApi": True,
                "time": utc_now_iso(),
            })
            return
        if path == "/api/latest":
            if not self._authorized():
                self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            p = self.server.data_dir / "latest.json"
            if not p.is_file():
                self.send_json(HTTPStatus.OK, {"ok": True, "latest": None})
                return
            try:
                self.send_json(HTTPStatus.OK, {"ok": True, "latest": json.loads(p.read_text("utf-8"))})
            except Exception as exc:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            if path in {"/api/chat-result", "/api/claude-result"}:
                return self._result()
            if path in {"/api/chat-status", "/api/claude-status"}:
                return self._status()
            if path in {"/api/chat-file/start", "/api/claude-file/start"}:
                return self._file_start()
            if path in {"/api/chat-file/chunk", "/api/claude-file/chunk"}:
                return self._file_chunk()
            if path in {"/api/chat-file/finish", "/api/claude-file/finish"}:
                return self._file_finish()
            if path in {"/api/chat-file/abort", "/api/claude-file/abort"}:
                return self._file_abort()
            if path in {"/api/chat-file", "/api/claude-file"}:
                return self._legacy_file()
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except FileNotFoundError as exc:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            print(f"[{utc_now_iso()}] request error path={path}: {exc}", flush=True)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def _result(self):
        payload = self._read_json(32 * 1024 * 1024)
        received = utc_now_iso()
        chat_meta = infer_chat_metadata(payload)
        # Normalize metadata at the boundary so every downstream consumer sees
        # one shape, including runs created by older extension versions.
        payload.update(chat_meta)
        run_id = f"{utc_run_stamp()}_{run_chat_slug(chat_meta)}_{uuid.uuid4().hex[:8]}"
        run_dir = self.server.run_dir(run_id)
        (run_dir / "files").mkdir(parents=True, exist_ok=False)
        atomic_write_json(run_dir / "result.json", payload)
        transfer = payload.get("fileTransfer") if isinstance(payload.get("fileTransfer"), dict) else {}
        expected = int(transfer.get("expectedFiles") or 0)
        status = {
            "runId": run_id,
            "status": "JSON_RECEIVED" if expected == 0 else "FILES_PENDING",
            "expectedFiles": expected,
            "completedFiles": 0,
            "files": [],
            "receivedAt": received,
            "updatedAt": received,
            **chat_meta,
        }
        atomic_write_json(run_dir / "status.json", status)
        self._write_latest_snapshot(status)
        print(f"[{received}] created run {run_id} chatType={chat_meta['chatType']} expectedFiles={expected}", flush=True)
        self.send_json(HTTPStatus.OK, {"ok": True, "runId": run_id, "receivedAt": received, **chat_meta})

    def _status(self):
        body = self._read_json()
        run_id = str(body.pop("runId"))
        status = self._write_status_patch(run_id, body)
        self.send_json(HTTPStatus.OK, {"ok": True, "runId": run_id, "status": status})

    def _file_start(self):
        body = self._read_json()
        run_id = str(body.get("runId") or "")
        file_name = safe_filename(body.get("fileName") or body.get("name") or "file.bin")
        total_raw = body.get("totalBytes")
        total = int(total_raw) if total_raw not in (None, "", 0, "0") else None
        if total is not None and total < 0:
            raise ValueError("totalBytes must be >= 0")
        run_dir = self.server.run_dir(run_id)
        if not (run_dir / "result.json").is_file():
            raise FileNotFoundError("run not found")
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_destination(files_dir, file_name)
        upload_id = uuid.uuid4().hex
        part = files_dir / ("." + upload_id + ".part")
        part.touch(exist_ok=False)
        session = {
            "uploadId": upload_id,
            "runId": run_id,
            "fileName": dest.name,
            "dest": dest,
            "part": part,
            "received": 0,
            "total": total,
            "mimeType": str(body.get("mimeType") or "application/octet-stream"),
            "expectedSha256": str(body.get("sha256") or body.get("expectedSha256") or "").lower(),
            "sha": hashlib.sha256(),
        }
        with self.server.lock:
            self.server.uploads[upload_id] = session
        self._write_status_patch(run_id, {"status": "FILES_PENDING", "currentUpload": {"uploadId": upload_id, "name": dest.name, "status": "UPLOADING", "receivedBytes": 0, "totalBytes": total, "startedAt": utc_now_iso()}})
        self.send_json(HTTPStatus.OK, {"ok": True, "uploadId": upload_id, "runId": run_id, "fileName": dest.name, "receivedBytes": 0, "totalBytes": total})

    def _get_upload(self, upload_id: str) -> dict:
        with self.server.lock:
            session = self.server.uploads.get(upload_id)
        if not session:
            raise FileNotFoundError("upload session not found")
        return session

    def _file_chunk(self):
        upload_id = self.headers.get("X-Upload-Id", "")
        offset = int(self.headers.get("X-Chunk-Offset", "-1"))
        session = self._get_upload(upload_id)
        if offset != session["received"]:
            raise ValueError(f"chunk offset mismatch expected={session['received']} actual={offset}")
        chunk = self._read_bytes(16 * 1024 * 1024)
        if session["total"] is not None and session["received"] + len(chunk) > session["total"]:
            raise ValueError("chunk exceeds expected size")
        with open(session["part"], "ab") as fh:
            fh.write(chunk)
            fh.flush()
        session["sha"].update(chunk)
        session["received"] += len(chunk)
        self._write_status_patch(session["runId"], {"currentUpload": {"uploadId": upload_id, "name": session["fileName"], "status": "UPLOADING", "receivedBytes": session["received"], "totalBytes": session["total"]}})
        self.send_json(HTTPStatus.OK, {"ok": True, "uploadId": upload_id, "receivedBytes": session["received"], "totalBytes": session["total"]})

    def _record_completed(self, session: dict, digest: str) -> dict:
        run_dir = self.server.run_dir(session["runId"])
        with self.server.lock:
            status = self._load_status(run_dir, session["runId"])
            files = status.get("files") if isinstance(status.get("files"), list) else []
            info = {
                "name": session["fileName"],
                "path": str(session["dest"]),
                "bytes": session["received"],
                "sha256": digest,
                "mimeType": session["mimeType"],
                "completedAt": utc_now_iso(),
            }
            files.append(info)
            status["files"] = files
            status["completedFiles"] = len(files)
            status.pop("currentUpload", None)
            if int(status.get("expectedFiles") or 0) > len(files):
                status["status"] = "FILES_PENDING"
            status["updatedAt"] = utc_now_iso()
            atomic_write_json(run_dir / "status.json", status)
            self._write_latest_snapshot(status)
            return info

    def _file_finish(self):
        body = self._read_json()
        upload_id = str(body.get("uploadId") or self.headers.get("X-Upload-Id") or "")
        session = self._get_upload(upload_id)
        if session["total"] is not None and session["received"] != session["total"]:
            raise ValueError(f"size mismatch expected={session['total']} actual={session['received']}")
        if session["received"] <= 0:
            raise ValueError("empty upload")
        digest = session["sha"].hexdigest()
        expected = str(body.get("sha256") or body.get("expectedSha256") or session["expectedSha256"] or "").lower()
        if expected and digest != expected:
            raise ValueError(f"sha256 mismatch expected={expected} actual={digest}")
        os.replace(session["part"], session["dest"])
        info = self._record_completed(session, digest)
        with self.server.lock:
            self.server.uploads.pop(upload_id, None)
        self.send_json(HTTPStatus.OK, {"ok": True, "uploadId": upload_id, "runId": session["runId"], "fileName": session["fileName"], "receivedBytes": session["received"], "sha256": digest, "file": info})

    def _file_abort(self):
        body = self._read_json()
        upload_id = str(body.get("uploadId") or self.headers.get("X-Upload-Id") or "")
        reason = str(body.get("error") or body.get("reason") or "upload aborted")
        session = self._get_upload(upload_id)
        try:
            session["part"].unlink(missing_ok=True)
        finally:
            with self.server.lock:
                self.server.uploads.pop(upload_id, None)
        self._write_status_patch(session["runId"], {"currentUpload": None, "lastUploadError": reason})
        self.send_json(HTTPStatus.OK, {"ok": True, "uploadId": upload_id, "aborted": True})

    def _legacy_file(self):
        run_id = self.headers.get("X-Run-Id", "")
        file_name = safe_filename(self.headers.get("X-File-Name", "file.bin"))
        expected = (self.headers.get("X-File-Sha256") or self.headers.get("X-Expected-Sha256") or "").lower()
        mime = self.headers.get("X-File-Mime", "application/octet-stream")
        run_dir = self.server.run_dir(run_id)
        if not (run_dir / "result.json").is_file():
            raise FileNotFoundError("run not found")
        data = self._read_bytes()
        if not data:
            raise ValueError("empty file")
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"ok": False, "error": "sha256 mismatch", "expected": expected, "actual": digest})
            return
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_destination(files_dir, file_name)
        tmp = dest.with_name("." + uuid.uuid4().hex + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        session = {"runId": run_id, "fileName": dest.name, "dest": dest, "received": len(data), "mimeType": mime}
        info = self._record_completed(session, digest)
        self.send_json(HTTPStatus.OK, {"ok": True, "runId": run_id, "fileName": dest.name, "bytes": len(data), "sha256": digest, "file": info})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8867)
    p.add_argument("--data-dir", default="/home/ext_disk/prompt_automation_pro2/data")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("CLAUDE_RECEIVER_TOKEN", "").strip()
    if not token:
        raise SystemExit("CLAUDE_RECEIVER_TOKEN is required")
    server = ReceiverServer((args.host, args.port), Handler, Path(args.data_dir), token)
    print(f"Prompt Automation Pro 2 receiver {VERSION} listening on {args.host}:{args.port}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
