from __future__ import annotations

import asyncio
import hashlib
import http.client
import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from yarl import URL

import os
import sys

ROOT = Path(__file__).resolve().parents[1]
# Releases are versioned directories; the slice under test is selected here so
# the suite cannot silently exercise the previous release.
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s1")
RECEIVER = ROOT / "receivers" / os.environ.get("PAP_RECEIVER_RELEASE", "2.11.0-s1") / "server.py"
if not CONSOLE.is_dir():
    raise SystemExit(f"console release directory not found: {CONSOLE}")
if not RECEIVER.is_file():
    raise SystemExit(f"receiver release not found: {RECEIVER}")
sys.path.insert(0, str(CONSOLE))

from chat_bindings import ChatBindingsStore
from console_server import ConsoleServer
from profile_store import ProfileActivationStore, ProfileSessionStore, ProfileSnapshotStore, ProfileStore
from run_profile_context import ProfileAuthorizationError

spec = importlib.util.spec_from_file_location("pap2_receiver", RECEIVER)
receiver = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(receiver)


def profile_body(profile_id: str, name: str | None = None) -> dict:
    role = "source"
    return {
        "id": profile_id,
        "name": name or profile_id,
        "enabled": True,
        "paths": {"workDir": "/tmp/pap2", "tempDir": "/tmp/pap2"},
        "variables": {"MODE": "slice1"},
        "secretRefs": {"API": f"{profile_id}-secret"},
        "roles": {role: {"promptPath": f"prompts/roles/{role}.md", "basePromptRequired": True}},
        "delivery": {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 3600},
        "directives": {"COMMAND_TEST": {"kind": "baseline"}},
        "errorDetection": {"enabled": True, "disabledBuiltins": [], "customSignatures": []},
        "promptTexts": {"base": f"BASE {profile_id}", "roles": {role: f"ROLE {profile_id}"}},
    }


class ReceiverHarness:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.server = receiver.ReceiverServer(("127.0.0.1", 0), receiver.Handler, self.data, "tok")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post_json(self, path: str, body: dict):
        raw = json.dumps(body).encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=raw, headers={
            "Authorization": "Bearer tok",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        })
        r = c.getresponse()
        payload = json.loads(r.read().decode("utf-8"))
        status = r.status
        c.close()
        return status, payload

    def upload_legacy(self, intake_id: str, name: str, data: bytes):
        digest = hashlib.sha256(data).hexdigest()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/chat-file", body=data, headers={
            "Authorization": "Bearer tok",
            "Content-Length": str(len(data)),
            "X-Run-Id": intake_id,
            "X-File-Name": name,
            "X-File-Sha256": digest,
            "X-File-Mime": "application/octet-stream",
        })
        r = c.getresponse()
        payload = json.loads(r.read().decode("utf-8"))
        status = r.status
        c.close()
        return status, payload


class Slice1Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.token_file = self.root / "console.token"
        self.token_file.write_text("ctok", encoding="utf-8")
        self.profiles = ProfileStore(self.root)
        self.p1 = self.profiles.save_profile(profile_body("p1"), actor="test", create=True)
        (self.root / "config" / "secrets" / "p1-secret").write_text("SUPER-SECRET-VALUE", encoding="utf-8")
        self.bindings = ChatBindingsStore(self.root, self.profiles)
        self.bindings.create({
            "bindingId": "b1", "name": "B1", "chatType": "chatgpt", "conversationId": "c1",
            "profileId": "p1", "role": "source", "enabled": True,
        }, actor="test")

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, conversation="c1", expected=0, generated="t1"):
        return {
            "page": f"https://chatgpt.com/c/{conversation}",
            "chatType": "chatgpt",
            "chatConversationId": conversation,
            "generatedAt": generated,
            "turnId": None,
            "messages": [{"role": "assistant", "text": "same parse"}],
            "commands": [],
            "fileTransfer": {"expectedFiles": expected, "requiredPaths": ["/tmp/a.bin"] if expected else []},
        }

    def test_receiver_stages_until_full_hash_and_deduplicates(self):
        h = ReceiverHarness(self.root)
        try:
            status, first = h.post_json("/api/chat-result", self.payload(expected=1, generated="time-a"))
            self.assertEqual(status, 200)
            intake1 = first["runId"]
            self.assertTrue(intake1.startswith("intake-"))
            self.assertEqual([p for p in self.data.iterdir() if p.is_dir()], [])

            console = ConsoleServer(self.root, self.data, self.token_file)
            self.assertEqual(console.list_runs(), [], "staging intake leaked into public Run list")

            blob = "файл payload".encode("utf-8")
            digest = hashlib.sha256(blob).hexdigest()
            self.assertEqual(h.upload_legacy(intake1, "a.bin", blob)[0], 200)
            status, final1 = h.post_json("/api/chat-status", {
                "runId": intake1, "status": "DONE", "expectedFiles": 1, "completedFiles": 1,
                "files": [{"name": "a.bin", "requiredPath": "/tmp/a.bin", "byteLength": len(blob), "sha256": digest}],
            })
            self.assertEqual(status, 200)
            canonical = final1["canonicalRunId"]
            self.assertFalse(final1["duplicate"])
            self.assertTrue((self.data / canonical / "result.json").is_file())

            status, second = h.post_json("/api/chat-result", self.payload(expected=1, generated="time-b"))
            intake2 = second["runId"]
            self.assertTrue(intake2.startswith("intake-"))
            self.assertEqual(h.upload_legacy(intake2, "a.bin", blob)[0], 200)
            status, final2 = h.post_json("/api/chat-status", {
                "runId": intake2, "status": "DONE", "expectedFiles": 1, "completedFiles": 1,
                "files": [{"name": "a.bin", "requiredPath": "/tmp/a.bin", "byteLength": len(blob), "sha256": digest}],
            })
            self.assertEqual(status, 200)
            self.assertTrue(final2["duplicate"])
            self.assertEqual(final2["canonicalRunId"], canonical)
            public = [p for p in self.data.iterdir() if p.is_dir()]
            self.assertEqual([p.name for p in public], [canonical])
            meta = json.loads((self.data / canonical / "intake-meta.json").read_text("utf-8"))
            self.assertEqual(meta["duplicateCount"], 1)
            self.assertTrue((self.data / canonical / "duplicate-journal.jsonl").is_file())
        finally:
            h.close()

    def test_binding_identity_changes_fingerprint_and_malformed_is_not_guessed(self):
        h = ReceiverHarness(self.root)
        try:
            _, one = h.post_json("/api/chat-result", self.payload())
            canonical1 = one["runId"]
            self.bindings.delete("b1", actor="test")
            self.bindings.create({
                "bindingId": "b2", "name": "B2", "chatType": "chatgpt", "conversationId": "c1",
                "profileId": "p1", "role": "source", "enabled": True,
            }, actor="test")
            _, two = h.post_json("/api/chat-result", self.payload(generated="other"))
            self.assertNotEqual(two["runId"], canonical1)
            path = self.root / "config" / "chat-bindings.json"
            body = json.loads(path.read_text("utf-8")); body["digest"] = "sha256:" + "0" * 64
            path.write_text(json.dumps(body), encoding="utf-8")
            state = h.server.read_binding_identity("chatgpt", "c1")
            self.assertEqual(state["state"], "MALFORMED")
            self.assertIsNone(state["bindingId"])
        finally:
            h.close()

    def test_snapshot_atomic_secret_free_and_session_restart_generation(self):
        snapshots = ProfileSnapshotStore(self.root, self.profiles)
        a = snapshots.publish_current("p1")
        snap_dir = snapshots.path(a["snapshotDigest"])
        all_bytes = b"".join(p.read_bytes() for p in snap_dir.rglob("*") if p.is_file())
        self.assertNotIn(b"SUPER-SECRET-VALUE", all_bytes)
        loaded = snapshots.load(a["snapshotDigest"])
        self.assertEqual(loaded["profile"]["variables"]["MODE"], "slice1")
        self.assertIn("COMMAND_TEST", loaded["profile"]["directives"])
        self.assertEqual(loaded["profile"]["secretRefs"]["API"], "p1-secret")
        self.assertEqual(list(snapshots.staging_root.iterdir()), [])

        sessions = ProfileSessionStore(self.root, snapshots)
        s1 = sessions.ensure("p1", ["b1"], restart_generation=0)
        edited = self.profiles.get_profile("p1", include_prompts=True)
        edited["name"] = "edited after start"
        self.profiles.save_profile(edited, actor="test", expected_id="p1")
        s2 = sessions.ensure("p1", ["b1"], restart_generation=0)
        self.assertEqual(s2["sessionId"], s1["sessionId"])
        self.assertEqual(s2["snapshotDigest"], s1["snapshotDigest"])
        s3 = sessions.ensure("p1", ["b1"], restart_generation=1)
        self.assertNotEqual(s3["sessionId"], s1["sessionId"])
        self.assertNotEqual(s3["snapshotDigest"], s1["snapshotDigest"])

        activation = ProfileActivationStore(self.root)
        self.assertEqual(activation.get("p1")["effectiveDesiredState"], "INACTIVE")
        row = activation.put("p1", config_intent="ACTIVE", changed_by="config")
        self.assertEqual(row["effectiveDesiredState"], "ACTIVE")
        # Foundation only: creating intent/session did not create browser endpoint data beyond baseline store use.
        self.assertFalse((self.root / "runtime" / "browser-endpoints.json").exists())

    def test_run_snapshot_is_immutable_and_live_profile_binding_gate_remains_live(self):
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        ctx1 = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(ctx1["resolutionStatus"], "RESOLVED")
        self.assertTrue(ctx1["snapshotDigest"].startswith("sha256:"))
        old_snapshot = ctx1["snapshotDigest"]
        self.assertFalse((self.data / run_id / ".snapshot-capture").exists())

        edited = self.profiles.get_profile("p1", include_prompts=True)
        edited["variables"]["MODE"] = "changed-live"
        edited["promptTexts"]["base"] = "NEW BASE"
        self.profiles.save_profile(edited, actor="test", expected_id="p1")
        ctx2 = console.profile_context.get(run_id)
        self.assertEqual(ctx2["snapshotDigest"], old_snapshot)
        loaded = console.snapshots.load(old_snapshot)
        self.assertEqual(loaded["profile"]["variables"]["MODE"], "slice1")
        self.assertEqual(loaded["promptTexts"]["base"], "BASE p1")
        self.assertEqual(console.profile_context.authorize_execution(run_id)["snapshotDigest"], old_snapshot)

        disabled = self.profiles.get_profile("p1", include_prompts=True)
        disabled["enabled"] = False
        self.profiles.save_profile(disabled, actor="test", expected_id="p1")
        with self.assertRaises(ProfileAuthorizationError) as cm:
            console.profile_context.authorize_execution(run_id)
        self.assertEqual(cm.exception.code, "PROFILE_DISABLED")
        self.assertEqual(console.profile_context.get(run_id)["snapshotDigest"], old_snapshot)

    def test_binding_gate_is_live_and_tab_state_is_not_a_server_precondition(self):
        """ACC-S1-006, binding half plus the negative half about manual tab state."""
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        ctx = console.profile_context.ensure_run_context(run_id)
        snapshot = ctx["snapshotDigest"]

        # No endpoint was ever observed and no tab is enabled anywhere: the
        # server-owned gate must still pass. Manual/effective tab-enabled is
        # extension-owned and is not a server-side precondition.
        self.assertEqual(console.endpoints.list()["endpoints"], [])
        self.assertEqual(console.profile_context.authorize_execution(run_id)["snapshotDigest"], snapshot)

        def refuses(code):
            with self.assertRaises(ProfileAuthorizationError) as cm:
                console.profile_context.authorize_execution(run_id)
            self.assertEqual(cm.exception.code, code)
            self.assertEqual(console.profile_context.get(run_id)["snapshotDigest"], snapshot)

        binding = dict(self.bindings.get("b1"))

        disabled = dict(binding); disabled["enabled"] = False
        self.bindings.update("b1", disabled, actor="test")
        refuses("CHAT_DISABLED")

        self.bindings.update("b1", binding, actor="test")
        self.assertEqual(console.profile_context.authorize_execution(run_id)["snapshotDigest"], snapshot)

        # The whole identity gate, not just profileId: every pinned field that
        # authorize_execution compares must revoke the next step on its own.
        self.profiles.save_profile(profile_body("p2"), actor="test", create=True)
        (self.root / "config" / "secrets" / "p2-secret").write_text("X", encoding="utf-8")
        # A second role must exist in the live profile before a binding may
        # carry it; editing the live profile does not touch the Run snapshot.
        with_role = self.profiles.get_profile("p1", include_prompts=True)
        with_role["roles"]["reviewer"] = {"promptPath": "prompts/roles/reviewer.md",
                                          "basePromptRequired": True}
        with_role["promptTexts"]["roles"]["reviewer"] = "ROLE reviewer"
        self.profiles.save_profile(with_role, actor="test", expected_id="p1")
        self.assertEqual(
            console.profile_context.authorize_execution(run_id)["snapshotDigest"], snapshot)

        for field, value in [
            ("profileId", "p2"),
            ("role", "reviewer"),
            ("chatType", "claude"),
            ("conversationId", "c-other"),
        ]:
            changed = dict(binding); changed[field] = value
            self.bindings.update("b1", changed, actor="test")
            with self.subTest(field=field):
                refuses("CHAT_BINDING_CHANGED")
            self.bindings.update("b1", binding, actor="test")
            self.assertEqual(
                console.profile_context.authorize_execution(run_id)["snapshotDigest"], snapshot)

        self.bindings.delete("b1", actor="test")
        refuses("CHAT_NOT_BOUND")

    def test_pinned_project_identity_change_revokes_execution(self):
        """The projectId branch of the identity gate needs a project-scoped intake."""
        self.bindings.create({
            "bindingId": "bp", "name": "BP", "chatType": "claude", "conversationId": "c9",
            "projectId": "proj-7", "profileId": "p1", "role": "source", "enabled": True,
        }, actor="test")
        h = ReceiverHarness(self.root)
        try:
            payload = self.payload(conversation="c9", generated="proj-1")
            payload["page"] = "https://claude.ai/project/proj-7"
            payload["chatType"] = "claude"
            _, created = h.post_json("/api/chat-result", payload)
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        ctx = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(ctx.get("projectId"), "proj-7",
                         "intake must pin a projectId or this branch is untested")
        snapshot = ctx["snapshotDigest"]

        binding = dict(self.bindings.get("bp"))
        moved = dict(binding); moved["projectId"] = "proj-8"
        self.bindings.update("bp", moved, actor="test")
        with self.assertRaises(ProfileAuthorizationError) as cm:
            console.profile_context.authorize_execution(run_id)
        self.assertEqual(cm.exception.code, "CHAT_BINDING_CHANGED")
        self.assertEqual(console.profile_context.get(run_id)["snapshotDigest"], snapshot)

    def test_session_snapshot_survives_session_directory_deletion(self):
        snapshots = ProfileSnapshotStore(self.root, self.profiles)
        sessions = ProfileSessionStore(self.root, snapshots)
        session = sessions.ensure("p1", ["b1"], restart_generation=0)
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        shutil.rmtree(self.root / "runtime" / "profile-sessions" / session["sessionId"])
        console = ConsoleServer(self.root, self.data, self.token_file)
        ctx = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(ctx["sessionId"], session["sessionId"])
        self.assertEqual(ctx["snapshotDigest"], session["snapshotDigest"])
        self.assertEqual(console.snapshots.load(ctx["snapshotDigest"])["profile"]["id"], "p1")

    def test_server_side_profile_filter_and_repeat_as_new(self):
        self.profiles.save_profile(profile_body("p2"), actor="test", create=True)
        self.bindings.create({
            "bindingId": "b2", "name": "B2", "chatType": "chatgpt", "conversationId": "c2",
            "profileId": "p2", "role": "source", "enabled": True,
        }, actor="test")
        h = ReceiverHarness(self.root)
        try:
            _, r1 = h.post_json("/api/chat-result", self.payload("c1"))
            _, r2 = h.post_json("/api/chat-result", self.payload("c2"))
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        all_rows = console.list_runs()
        self.assertEqual({x["runId"] for x in all_rows}, {r1["runId"], r2["runId"]})
        self.assertEqual([x["runId"] for x in console.list_runs("p1")], [r1["runId"]])

        req = SimpleNamespace(headers={"Authorization": "Bearer ctok"}, rel_url=URL("/api/runs?profileId=p1"))
        response = asyncio.run(console.api_runs(req))
        body = json.loads(response.body)
        self.assertEqual(body["profileId"], "p1")
        self.assertEqual([x["runId"] for x in body["runs"]], [r1["runId"]])

        repeated = console.repeat_as_new(r1["runId"])
        new_id = repeated["runId"]
        self.assertNotEqual(new_id, r1["runId"])
        meta = json.loads((self.data / new_id / "intake-meta.json").read_text("utf-8"))
        self.assertTrue(meta["dedupeBypass"])
        self.assertEqual(meta["repeatOf"], r1["runId"])
        self.assertTrue(repeated["profileContext"]["snapshotDigest"].startswith("sha256:"))

    def test_context_creation_is_explicit_idempotent_and_get_never_writes(self):
        """Creator condition 1: readiness is a named operation, not a read side effect."""
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        ctx_path = self.data / run_id / "profile-context.json"
        self.assertFalse(ctx_path.exists())

        # Reading does not create, and reports not-ready rather than a verdict.
        read = console.profile_context.get(run_id)
        self.assertEqual(read["resolutionStatus"], "RUN_CONTEXT_NOT_READY")
        self.assertFalse(ctx_path.exists())

        # The named creator is the only writer, and it is idempotent.
        first = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(first["resolutionStatus"], "RESOLVED")
        self.assertTrue(ctx_path.exists())
        first_bytes = ctx_path.read_bytes()
        second = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(second, first)
        self.assertEqual(ctx_path.read_bytes(), first_bytes)
        self.assertEqual(console.profile_context.get(run_id)["snapshotDigest"], first["snapshotDigest"])

    def test_execution_readiness_does_not_depend_on_listing_or_ui(self):
        """Creator condition 1: a Run never listed is still executable-ready."""
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        self.assertFalse((self.data / run_id / "profile-context.json").exists())
        # No list_runs, no run_detail, no UI call of any kind before this.
        ctx = console.profile_context.authorize_execution(run_id)
        self.assertEqual(ctx["resolutionStatus"], "RESOLVED")

    def test_missing_context_is_fail_closed_and_never_masked_as_identity_failure(self):
        """Creator condition 2 and the promotion window."""
        run_id = "20260906T101010.000000Z_window"
        run_dir = self.data / run_id
        run_dir.mkdir(parents=True)
        # A Run directory that exists but carries no result.json yet is the
        # window between receiver promotion and a usable context.
        console = ConsoleServer(self.root, self.data, self.token_file)
        read = console.profile_context.get(run_id)
        self.assertEqual(read["resolutionStatus"], "RUN_CONTEXT_NOT_READY")
        self.assertNotEqual(read["blockReason"], "CHAT_IDENTITY_INVALID")
        ensured = console.profile_context.ensure_run_context(run_id)
        self.assertEqual(ensured["resolutionStatus"], "RUN_CONTEXT_NOT_READY")
        self.assertFalse((run_dir / "profile-context.json").exists())

        with self.assertRaises(ProfileAuthorizationError) as cm:
            console.profile_context.authorize_execution(run_id)
        self.assertEqual(cm.exception.code, "RUN_CONTEXT_NOT_READY")

        # Snapshot failure gets its own status too, not a fabricated identity error.
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload(conversation="c1", generated="t-snapfail"))
            broken_id = created["runId"]
        finally:
            h.close()
        capture = self.data / broken_id / ".snapshot-capture"
        if capture.is_dir():
            shutil.rmtree(capture)
        broken = console.profile_context.ensure_run_context(broken_id)
        self.assertIn(broken["resolutionStatus"], {"PROFILE_SNAPSHOT_UNAVAILABLE", "RUN_CONTEXT_UNAVAILABLE"})
        self.assertNotEqual(broken["resolutionStatus"], "CHAT_IDENTITY_INVALID")
        with self.assertRaises(ProfileAuthorizationError) as cm2:
            console.profile_context.authorize_execution(broken_id)
        self.assertNotEqual(cm2.exception.code, "CHAT_IDENTITY_INVALID")

    def test_log_truncation_utf8_safe_and_full_source_unchanged(self):
        small = "абв"
        shown, omitted = ConsoleServer.truncate_log_text(small)
        self.assertEqual((shown, omitted), (small, 0))
        full = ("Ж" * 40000) + "TAIL"
        raw = full.encode("utf-8")
        self.assertGreater(len(raw), 50 * 1024)
        shown, omitted = ConsoleServer.truncate_log_text(full)
        shown.encode("utf-8")  # must remain valid UTF-8
        self.assertIn(f"{omitted} BYTES OMITTED", shown)
        self.assertTrue(shown.endswith("TAIL"))
        kept_without_marker = len(shown.split("--- PAP2 LOG TRUNCATED:", 1)[0].encode("utf-8"))
        self.assertGreater(omitted, 0)
        self.assertEqual(full.encode("utf-8"), raw, "presentation truncation mutated full source text")

    def test_execute_business_gate_rejects_before_executor(self):
        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        disabled = self.profiles.get_profile("p1", include_prompts=True)
        disabled["enabled"] = False
        self.profiles.save_profile(disabled, actor="test", expected_id="p1")
        console.executor.execute_step = AsyncMock(return_value={"unexpected": True})

        class Req:
            headers = {"Authorization": "Bearer ctok", "X-PAP-Operator": "test"}
            match_info = {"run_id": run_id, "step_id": "step-1"}
            can_read_body = False
            remote = "127.0.0.1"
            async def json(self): return {}

        response = asyncio.run(console.api_execute_step(Req()))
        self.assertEqual(response.status, 409)
        console.executor.execute_step.assert_not_awaited()
        self.assertFalse(console.executor.state_path(run_id).exists())

    def test_execute_step_in_promotion_window_changes_no_step_state(self):
        """api_execute_step arriving before the context is usable must not run."""
        run_id = "20260906T111111.000000Z_window"
        (self.data / run_id).mkdir(parents=True)
        console = ConsoleServer(self.root, self.data, self.token_file)
        console.executor.execute_step = AsyncMock(return_value={"unexpected": True})

        class Req:
            headers = {"Authorization": "Bearer ctok", "X-PAP-Operator": "test"}
            match_info = {"run_id": run_id, "step_id": "step-1"}
            can_read_body = False
            remote = "127.0.0.1"
            async def json(self): return {}

        response = asyncio.run(console.api_execute_step(Req()))
        self.assertEqual(response.status, 409)
        body = json.loads(response.body)
        self.assertEqual(body["code"], "RUN_CONTEXT_NOT_READY")
        self.assertNotEqual(body["code"], "CHAT_IDENTITY_INVALID")
        console.executor.execute_step.assert_not_awaited()
        self.assertFalse(console.executor.state_path(run_id).exists())
        self.assertFalse((self.data / run_id / "profile-context.json").exists())

    def test_presentation_log_shape_and_full_log_download_stays_complete(self):
        """ACC-S1-008 and ACC-S1-009 proven over the real routes, not the helper."""
        full = ("Ж" * 40000) + "TAIL"
        raw_full = full.encode("utf-8")
        edge = 25 * 1024

        shown, omitted = ConsoleServer.truncate_log_text(full)
        head_text, _, tail_text = shown.partition(f"\n\n--- PAP2 LOG TRUNCATED: {omitted} BYTES OMITTED ---\n\n")
        head_bytes = head_text.encode("utf-8")
        tail_bytes = tail_text.encode("utf-8")
        # head and tail are each at most 25 KiB and lose at most one partial
        # character at the cut, which is what keeps the result valid UTF-8.
        self.assertLessEqual(head_bytes, raw_full[:edge])
        self.assertGreater(len(head_bytes), edge - 4)
        self.assertLessEqual(len(head_bytes), edge)
        self.assertGreater(len(tail_bytes), edge - 4)
        self.assertLessEqual(len(tail_bytes), edge)
        self.assertEqual(omitted, len(raw_full) - len(head_bytes) - len(tail_bytes))
        shown.encode("utf-8")

        h = ReceiverHarness(self.root)
        try:
            _, created = h.post_json("/api/chat-result", self.payload())
            run_id = created["runId"]
        finally:
            h.close()
        console = ConsoleServer(self.root, self.data, self.token_file)
        console.executor.build_full_run_log = lambda rid: full
        materialized = self.root / "full.log"
        materialized.write_text(full, encoding="utf-8")
        console.executor.materialize_full_run_log = lambda rid: materialized

        class Req:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": run_id}

        presented = asyncio.run(console.api_full_run_log(Req()))
        self.assertEqual(presented.headers["X-PAP-Log-Truncated"], "1")
        self.assertEqual(int(presented.headers["X-PAP-Log-Omitted-Bytes"]), omitted)
        self.assertLess(len(presented.text.encode("utf-8")), len(raw_full))

        download = asyncio.run(console.api_full_run_log_download(Req()))
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(Path(download._path).read_bytes(), raw_full,
                         "full log download must not inherit presentation truncation")

    def test_multi_file_hash_vector_is_ordered_and_duplicate_never_enters_repeat_path(self):
        """ACC-S1-015 and ACC-S1-018."""
        a, b = b"AAA", b"BBB"
        sa, sb = hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()

        def rows(order):
            return [{"name": n, "requiredPath": f"/tmp/{n}", "byteLength": len(d), "sha256": h}
                    for n, d, h in order]

        def intake(generated, order):
            payload = self.payload(expected=2, generated=generated)
            payload["fileTransfer"]["requiredPaths"] = ["/tmp/a.bin", "/tmp/b.bin"]
            _, staged = h.post_json("/api/chat-result", payload)
            iid = staged["runId"]
            self.assertTrue(iid.startswith("intake-"))
            for name, data, _ in order:
                self.assertEqual(h.upload_legacy(iid, name, data)[0], 200)
            _, final = h.post_json("/api/chat-status", {
                "runId": iid, "status": "DONE", "expectedFiles": 2, "completedFiles": 2,
                "files": rows(order),
            })
            return final

        ab = [("a.bin", a, sa), ("b.bin", b, sb)]
        ba = [("b.bin", b, sb), ("a.bin", a, sa)]

        h = ReceiverHarness(self.root)
        try:
            first = intake("multi-1", ab)
            canonical = first["canonicalRunId"]
            self.assertFalse(first["duplicate"])

            # Same parse, same bytes, same order -> duplicate of the same Run.
            second = intake("multi-2", ab)
            self.assertTrue(second["duplicate"])
            self.assertEqual(second["canonicalRunId"], canonical)

            # Same bytes, different order -> the hash vector is ordered, so this
            # is a different Run and must not dedupe onto the first.
            third = intake("multi-3", ba)
            self.assertFalse(third["duplicate"])
            self.assertNotEqual(third["canonicalRunId"], canonical)
        finally:
            h.close()

        # ACC-S1-015: order and hashes come from completed uploads / final status.
        status_rows = json.loads((self.data / canonical / "status.json").read_text("utf-8"))["files"]
        self.assertEqual([r["name"] for r in status_rows], ["a.bin", "b.bin"])
        self.assertEqual([r["sha256"] for r in status_rows], [sa, sb])

        # ACC-S1-018: an ordinary duplicate never acquires repeat provenance.
        meta = json.loads((self.data / canonical / "intake-meta.json").read_text("utf-8"))
        self.assertEqual(meta["duplicateCount"], 1)
        self.assertFalse(meta.get("dedupeBypass"))
        self.assertIsNone(meta.get("repeatOf"))

        # Only the explicit route sets it.
        console = ConsoleServer(self.root, self.data, self.token_file)
        repeated = console.repeat_as_new(canonical)
        repeat_meta = json.loads((self.data / repeated["runId"] / "intake-meta.json").read_text("utf-8"))
        self.assertTrue(repeat_meta["dedupeBypass"])
        self.assertEqual(repeat_meta["repeatOf"], canonical)
        self.assertEqual(json.loads((self.data / canonical / "intake-meta.json").read_text("utf-8"))["duplicateCount"], 1)

    def test_ui_persists_profile_filter_selection(self):
        """ACC-S1-007 UI half: the selection survives reload."""
        js = (CONSOLE / "static" / "app.js").read_text("utf-8")
        self.assertIn("localStorage.getItem('pap:run-profile-filter:v1')", js)
        self.assertIn("localStorage.setItem('pap:run-profile-filter:v1'", js)

    def test_files_ui_is_explicit_not_ready_scaffold_and_filter_is_server_query(self):
        html = (CONSOLE / "static" / "index.html").read_text("utf-8")
        js = (CONSOLE / "static" / "app.js").read_text("utf-8")
        self.assertIn('data-view="files"', html)
        self.assertIn('id="viewFiles"', html)
        self.assertIn('NOT READY · slice 3a', html)
        self.assertIn('?profileId=', js)
        self.assertNotIn('/api/files', js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
