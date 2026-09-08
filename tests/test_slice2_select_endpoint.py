# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""MAP-028: explicit endpoint choice is a ProfileSession x ChatBinding relation."""
from __future__ import annotations

import asyncio
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

from console_server import ConsoleServer, create_app


def profile_body(profile_id: str = "p1") -> dict:
    role = "source"
    return {
        "id": profile_id,
        "name": profile_id,
        "enabled": True,
        "paths": {"workDir": "/tmp/pap2", "tempDir": "/tmp/pap2"},
        "variables": {"MODE": "slice2"},
        "secretRefs": {},
        "roles": {role: {"promptPath": f"prompts/roles/{role}.md", "basePromptRequired": True}},
        "delivery": {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 3600},
        "directives": {"COMMAND_TEST": {"kind": "baseline"}},
        "errorDetection": {"enabled": True, "disabledBuiltins": [], "customSignatures": []},
        "promptTexts": {"base": "BASE", "roles": {role: "ROLE"}},
    }


class Req:
    def __init__(self, session_id: str, binding_id: str, endpoint_id: str | None, *, token: str = "ctok"):
        self.headers = {"Authorization": f"Bearer {token}", "X-PAP-Operator": "tester"}
        self.match_info = {"session_id": session_id, "binding_id": binding_id}
        self._body = {} if endpoint_id is None else {"endpointId": endpoint_id}

    async def json(self):
        return dict(self._body)


class SelectEndpointContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        self.console.profiles.save_profile(profile_body(), actor="test", create=True)
        self.binding = self.console.bindings.create({
            "bindingId": "b1",
            "name": "B1",
            "chatType": "chatgpt",
            "conversationId": "abc",
            "profileId": "p1",
            "role": "source",
            "enabled": True,
        }, "test")["binding"]
        self.session = self.console.sessions.ensure("p1", ["b1"], restart_generation=0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def observe(self, endpoint_id: str, tab: int, *, conversation_id: str = "abc", project_id=None):
        return self.console.endpoints.observe(
            tab,
            f"https://chatgpt.com/c/{conversation_id}",
            endpoint_id=endpoint_id,
            title=endpoint_id,
            browser_epoch="epoch-1",
            chat_type="chatgpt",
            conversation_id=conversation_id,
            project_id=project_id,
        )

    def call(self, endpoint_id: str | None, *, binding_id: str = "b1", session_id: str | None = None):
        return asyncio.run(self.console.api_select_endpoint(
            Req(session_id or self.session["sessionId"], binding_id, endpoint_id)
        ))

    @staticmethod
    def payload(response):
        return json.loads(response.body.decode("utf-8"))

    def session_path(self):
        return self.root / "runtime" / "profile-sessions" / self.session["sessionId"] / "session.json"

    def session_bytes(self):
        return self.session_path().read_bytes()

    def make_offline(self, endpoint_id: str):
        path = self.root / "runtime" / "browser-endpoints.json"
        body = json.loads(path.read_text("utf-8"))
        row = next(x for x in body["endpoints"] if x["endpointId"] == endpoint_id)
        row["lastSeenAt"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_route_is_registered_and_writes_only_session_selection(self):
        self.observe("ep-1", 7)
        endpoint_before = (self.root / "runtime" / "browser-endpoints.json").read_bytes()
        binding_before = (self.root / "config" / "chat-bindings.json").read_bytes()

        response = self.call("ep-1")
        self.assertEqual(response.status, 200)
        body = self.payload(response)
        self.assertEqual(body["selection"]["status"], "SELECTED")
        self.assertEqual(body["selection"]["endpointId"], "ep-1")
        self.assertEqual(body["selection"]["reason"], "OPERATOR")
        self.assertEqual(body["selection"]["selectedBy"], "tester")
        self.assertEqual((self.root / "runtime" / "browser-endpoints.json").read_bytes(), endpoint_before)
        self.assertEqual((self.root / "config" / "chat-bindings.json").read_bytes(), binding_before)
        self.assertNotIn("approvedEndpointId", next(x for x in self.console.endpoints.list()["endpoints"] if x["endpointId"] == "ep-1"))

        app = create_app(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        paths = {route.resource.canonical for route in app.router.routes() if hasattr(route.resource, "canonical")}
        self.assertIn("/api/profile-sessions/{session_id}/bindings/{binding_id}/select-endpoint", paths)

    def test_identity_refusal_is_before_session_mutation(self):
        self.observe("ep-wrong", 8, conversation_id="other")
        before = self.session_bytes()
        response = self.call("ep-wrong")
        self.assertEqual(response.status, 409)
        self.assertEqual(self.payload(response)["code"], "ENDPOINT_SELECTION_REFUSED")
        self.assertEqual(self.session_bytes(), before)

    def test_terminal_endpoint_refusal_is_before_session_mutation(self):
        self.observe("ep-1", 7)
        self.console.endpoints.close("ep-1", "epoch-1")
        before = self.session_bytes()
        response = self.call("ep-1")
        self.assertEqual(response.status, 409)
        self.assertEqual(self.session_bytes(), before)

    def test_offline_endpoint_refusal_preserves_existing_relation(self):
        self.observe("ep-1", 7)
        self.assertEqual(self.call("ep-1").status, 200)
        relation_before = self.console.sessions.selection(self.session["sessionId"], "b1")
        self.make_offline("ep-1")
        response = self.call("ep-1")
        self.assertEqual(response.status, 409)
        self.assertIn("OFFLINE", self.payload(response)["error"])
        self.assertEqual(self.console.sessions.selection(self.session["sessionId"], "b1"), relation_before)

    def test_disabled_profile_is_live_authorization_refusal(self):
        self.observe("ep-1", 7)
        body = profile_body()
        body["enabled"] = False
        body["revision"] = self.console.profiles.get_profile("p1", include_prompts=False)["revision"]
        self.console.profiles.save_profile(body, actor="test", create=False)
        before = self.session_bytes()
        response = self.call("ep-1")
        self.assertEqual(response.status, 409)
        self.assertIn("profile is disabled", self.payload(response)["error"])
        self.assertEqual(self.session_bytes(), before)

    def test_binding_outside_session_is_refused(self):
        self.console.bindings.create({
            "bindingId": "b2", "name": "B2", "chatType": "chatgpt", "conversationId": "def",
            "profileId": "p1", "role": "source", "enabled": True,
        }, "test")
        self.observe("ep-2", 8, conversation_id="def")
        before = self.session_bytes()
        response = self.call("ep-2", binding_id="b2")
        self.assertEqual(response.status, 409)
        self.assertEqual(self.session_bytes(), before)

    def test_stopped_session_is_refused_before_write(self):
        self.observe("ep-1", 7)
        row = json.loads(self.session_path().read_text("utf-8"))
        row["state"] = "STOPPED"
        self.session_path().write_text(json.dumps(row), encoding="utf-8")
        before = self.session_bytes()
        response = self.call("ep-1")
        self.assertEqual(response.status, 409)
        self.assertEqual(self.session_bytes(), before)

    def test_operator_can_replace_relation_with_another_live_candidate(self):
        self.observe("ep-1", 7)
        self.observe("ep-2", 8)
        self.assertEqual(self.call("ep-1").status, 200)
        first = self.console.sessions.selection(self.session["sessionId"], "b1")
        self.assertEqual(first["endpointId"], "ep-1")
        self.assertEqual(self.call("ep-2").status, 200)
        second = self.console.sessions.selection(self.session["sessionId"], "b1")
        self.assertEqual(second["endpointId"], "ep-2")
        self.assertEqual(second["reason"], "OPERATOR")

    def test_missing_endpoint_id_is_400_and_writes_nothing(self):
        before = self.session_bytes()
        response = self.call(None)
        self.assertEqual(response.status, 400)
        self.assertEqual(self.payload(response)["code"], "ENDPOINT_ID_REQUIRED")
        self.assertEqual(self.session_bytes(), before)


if __name__ == "__main__":
    unittest.main()
