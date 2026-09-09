# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Slice 2 CONTROL_AGENT reconciliation plan (MAP-090).

The browser may cache profile-session reasons, but the console is their source
of truth.  These tests therefore use the real Profile/Binding/Session writers
and exercise the CONTROL_AGENT poll boundary.  Corruption tests start from a
writer-produced state and alter only the field under test.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s2")
sys.path.insert(0, str(CONSOLE))
sys.path.insert(0, str(ROOT / "tests"))

from console_server import ConsoleServer, REQUIRED_EXTENSION_VERSION
from profile_store import canonical_json_bytes
from test_slice2_select_endpoint import profile_body


class Req:
    headers = {"Authorization": "Bearer ctok"}
    def __init__(self, **query):
        self.rel_url = type("U", (), {"query": {k: str(v) for k, v in query.items() if v is not None}})()


class ReconcilePlanContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def poll(self, epoch="e1"):
        r = asyncio.run(self.console.api_delivery_poll(Req(
            pollKind="CONTROL_AGENT", browserEpoch=epoch,
            extensionVersion=REQUIRED_EXTENSION_VERSION)))
        return r, json.loads(r.body)

    def create_profile(self, profile_id="p1"):
        self.console.profiles.save_profile(profile_body(profile_id), actor="test", create=True)

    def create_binding(self, binding_id="b1", profile_id="p1", conversation_id="abc", *, enabled=True, project_id=None):
        return self.console.bindings.create({
            "bindingId": binding_id, "name": binding_id, "chatType": "chatgpt",
            "conversationId": conversation_id, "projectId": project_id,
            "profileId": profile_id, "role": "source", "enabled": enabled,
        }, "test")["binding"]

    def create_session(self, profile_id="p1", binding_ids=("b1",), generation=0):
        return self.console.sessions.ensure(profile_id, list(binding_ids), restart_generation=generation)

    def session_path(self, session_id):
        return self.root / "runtime" / "profile-sessions" / session_id / "session.json"

    def test_owner_gets_canonical_read_only_plan_and_no_delivery(self):
        self.create_profile("p2")
        self.create_binding("z-bind", "p2", "z")
        s2 = self.create_session("p2", ("z-bind",), 0)
        self.create_profile("p1")
        self.create_binding("b2", "p1", "b")
        self.create_binding("b1", "p1", "a", project_id="proj")
        s1 = self.create_session("p1", ("b2", "b1"), 0)
        before_sessions = {p.as_posix(): p.read_bytes() for p in (self.root / "runtime" / "profile-sessions").rglob("session.json")}
        before_bindings = (self.root / "config" / "chat-bindings.json").read_bytes()

        r, body = self.poll()
        self.assertEqual(r.status, 200)
        self.assertEqual(body["controlState"], "OWNER")
        self.assertNotIn("job", body)
        plan = body["reconcilePlan"]
        self.assertEqual([x["sessionId"] for x in plan["sessions"]], sorted([s1["sessionId"], s2["sessionId"]]))
        p1 = next(x for x in plan["sessions"] if x["sessionId"] == s1["sessionId"])
        self.assertEqual([x["bindingId"] for x in p1["bindings"]], ["b1", "b2"])
        self.assertEqual(p1["bindings"][0]["projectId"], "proj")
        material = {"sessions": plan["sessions"]}
        expected = "sha256:" + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        self.assertEqual(plan["revision"], expected)
        self.assertEqual({p.as_posix(): p.read_bytes() for p in (self.root / "runtime" / "profile-sessions").rglob("session.json")}, before_sessions)
        self.assertEqual((self.root / "config" / "chat-bindings.json").read_bytes(), before_bindings)

        # Same semantic state => same digest and same canonical order.
        r2, body2 = self.poll()
        self.assertEqual(r2.status, 200)
        self.assertEqual(body2["reconcilePlan"], plan)

    def test_stopped_session_is_absent(self):
        self.create_profile()
        self.create_binding()
        old = self.create_session(generation=0)
        new = self.create_session(generation=1)
        _r, body = self.poll()
        ids = [x["sessionId"] for x in body["reconcilePlan"]["sessions"]]
        self.assertNotIn(old["sessionId"], ids)
        self.assertIn(new["sessionId"], ids)

    def test_deleted_or_disabled_binding_is_not_a_reason(self):
        self.create_profile()
        self.create_binding("b1", conversation_id="a")
        self.create_binding("b2", conversation_id="b")
        session = self.create_session(binding_ids=("b1", "b2"))
        self.console.bindings.delete("b1", "test")
        b2 = self.console.bindings.get("b2")
        self.console.bindings.update("b2", {**b2, "enabled": False}, "test")
        _r, body = self.poll()
        row = next(x for x in body["reconcilePlan"]["sessions"] if x["sessionId"] == session["sessionId"])
        self.assertEqual(row["bindings"], [])

    def test_binding_profile_drift_makes_whole_plan_unprovable(self):
        self.create_profile("p1")
        self.create_profile("p2")
        self.create_binding("b1", "p1")
        self.create_session("p1", ("b1",))
        current = self.console.bindings.get("b1")
        self.console.bindings.update("b1", {**current, "profileId": "p2"}, "test")
        before_session = {p.as_posix(): p.read_bytes() for p in (self.root / "runtime" / "profile-sessions").rglob("session.json")}
        before_binding = (self.root / "config" / "chat-bindings.json").read_bytes()
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertEqual(body["controlState"], "OWNER")
        self.assertNotIn("reconcilePlan", body)
        self.assertEqual({p.as_posix(): p.read_bytes() for p in (self.root / "runtime" / "profile-sessions").rglob("session.json")}, before_session)
        self.assertEqual((self.root / "config" / "chat-bindings.json").read_bytes(), before_binding)

    def test_malformed_session_is_not_silently_skipped(self):
        self.create_profile()
        self.create_binding()
        session = self.create_session()
        self.session_path(session["sessionId"]).write_text("{not-json", encoding="utf-8")
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertNotIn("reconcilePlan", body)

    def test_ambiguous_live_sessions_for_one_profile_fail_whole_plan(self):
        self.create_profile()
        self.create_binding()
        old = self.create_session(generation=0)
        self.create_session(generation=1)
        path = self.session_path(old["sessionId"])
        row = json.loads(path.read_text("utf-8"))
        self.assertEqual(row["state"], "STOPPED")
        row["state"] = "RUNNING"  # one-field corruption over a writer state
        path.write_text(json.dumps(row), encoding="utf-8")
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertNotIn("reconcilePlan", body)

    def test_malformed_binding_store_fails_whole_plan(self):
        self.create_profile()
        self.create_binding()
        self.create_session()
        path = self.root / "config" / "chat-bindings.json"
        body = json.loads(path.read_text("utf-8"))
        body["digest"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(body), encoding="utf-8")
        r, response = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(response["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertNotIn("reconcilePlan", response)

    def test_conflicting_epoch_gets_no_plan_and_does_not_change_control_state(self):
        self.create_profile()
        self.create_binding()
        self.create_session()
        first, body1 = self.poll("e1")
        self.assertEqual(first.status, 200)
        registry = self.root / "runtime" / "browser-endpoints.json"
        before = registry.read_bytes()
        second, body2 = self.poll("e2")
        self.assertEqual(second.status, 409)
        self.assertEqual(body2["code"], "CONTROL_AGENT_CONFLICT")
        self.assertNotIn("reconcilePlan", body2)
        self.assertEqual(registry.read_bytes(), before)
        self.assertEqual(body1["reconcilePlan"]["revision"], self.poll("e1")[1]["reconcilePlan"]["revision"])

    def test_empty_plan_is_valid_and_has_deterministic_revision(self):
        r, body = self.poll()
        self.assertEqual(r.status, 200)
        self.assertEqual(body["reconcilePlan"]["sessions"], [])
        expected = "sha256:" + hashlib.sha256(canonical_json_bytes({"sessions": []})).hexdigest()
        self.assertEqual(body["reconcilePlan"]["revision"], expected)

    def test_session_binding_ids_wrong_shape_is_unprovable(self):
        self.create_profile()
        self.create_binding()
        session = self.create_session()
        path = self.session_path(session["sessionId"])
        row = json.loads(path.read_text("utf-8"))
        row["bindingIds"] = "b1"
        path.write_text(json.dumps(row), encoding="utf-8")
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")

    def test_schema_values_are_not_string_coerced(self):
        self.create_profile()
        self.create_binding()
        session = self.create_session()
        path = self.session_path(session["sessionId"])
        row = json.loads(path.read_text("utf-8"))
        row["schemaVersion"] = "1"
        path.write_text(json.dumps(row), encoding="utf-8")
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")

    def test_ambiguous_binding_identity_fails_whole_plan(self):
        self.create_profile("p1")
        self.create_profile("p2")
        self.create_binding("b1", "p1", "abc")
        self.create_binding("b2", "p2", "def")
        self.create_session("p1", ("b1",))
        self.create_session("p2", ("b2",))
        path = self.root / "config" / "chat-bindings.json"
        state = json.loads(path.read_text("utf-8"))
        row = next(x for x in state["bindings"] if x["bindingId"] == "b2")
        row["conversationId"] = "abc"  # one-field corruption over writer state
        state["digest"] = ""
        state["digest"] = self.console.bindings._digest(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertNotIn("reconcilePlan", body)


    def test_session_directory_without_row_is_unprovable_not_absent(self):
        self.create_profile()
        self.create_binding()
        session = self.create_session()
        self.session_path(session["sessionId"]).unlink()
        r, body = self.poll()
        self.assertEqual(r.status, 409)
        self.assertEqual(body["code"], "RECONCILE_PLAN_UNPROVABLE")
        self.assertNotIn("reconcilePlan", body)



if __name__ == "__main__":
    unittest.main()
