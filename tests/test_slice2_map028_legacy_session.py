# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""MAP-028 audit: the legacy-session obligation that has no regression yet.

`MAP-088` states it plainly — an existing session without `endpointSelections`
reads as empty, and legacy pins or approved values are not carried into the new
relation. The nine shipped tests never build such a session, so nothing would
notice if a future change decided to be helpful and import the old value.

The behaviour is correct on this candidate; these tests are what keeps it
correct. State is produced by the real writers — `save_profile`, `create`,
`ensure`, `observe` — and only the two legacy fields are added on top, which is
exactly the shape a session written before slice 2 has.

Place at tests/test_slice2_map028_legacy_session.py and run from the tree root.
"""
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
sys.path.insert(0, str(ROOT / "tests"))

from console_server import ConsoleServer
from test_slice2_select_endpoint import Req, profile_body


class LegacySessionHasNoSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data",
                                     self.root / "runtime" / "token.txt")
        self.console.profiles.save_profile(profile_body(), actor="test", create=True)
        self.console.bindings.create({
            "bindingId": "b1", "name": "B1", "chatType": "chatgpt",
            "conversationId": "abc", "profileId": "p1", "role": "source",
            "enabled": True}, "test")
        self.session = self.console.sessions.ensure("p1", ["b1"], restart_generation=0)
        self.console.endpoints.observe(
            7, "https://chatgpt.com/c/abc", endpoint_id="ep-1", title="ep-1",
            browser_epoch="epoch-1", chat_type="chatgpt", conversation_id="abc",
            project_id=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self):
        return (self.root / "runtime" / "profile-sessions"
                / self.session["sessionId"] / "session.json")

    def make_legacy(self):
        """A session as it looked before slice 2: no selections, an old pin."""
        row = json.loads(self.path().read_text("utf-8"))
        row.pop("endpointSelections", None)
        row["approvedEndpointId"] = "ep-legacy"
        row["pin"] = {"endpointId": "ep-legacy", "pinnedAt": "2026-01-01T00:00:00Z"}
        self.path().write_text(json.dumps(row), encoding="utf-8")

    def select(self, endpoint_id):
        return asyncio.run(self.console.api_select_endpoint(
            Req(self.session["sessionId"], "b1", endpoint_id)))

    def test_a_session_without_the_field_reads_as_empty(self):
        self.make_legacy()
        self.assertIsNone(self.console.sessions.selection(self.session["sessionId"], "b1"))
        self.assertEqual(
            self.console.sessions.get(self.session["sessionId"])["endpointSelections"], {},
            "the absent field must read as an empty relation, not as an error")

    def test_a_legacy_pin_never_becomes_a_selection(self):
        self.make_legacy()

        self.assertIsNone(self.console.sessions.selection(self.session["sessionId"], "b1"))
        response = self.select("ep-1")
        self.assertEqual(response.status, 200)

        relation = self.console.sessions.selection(self.session["sessionId"], "b1")
        self.assertEqual(relation["endpointId"], "ep-1")
        self.assertNotEqual(relation["endpointId"], "ep-legacy",
                            "the old approved value must never reach the new relation")
        self.assertEqual(relation["status"], "SELECTED")
        self.assertEqual(relation["reason"], "OPERATOR")

    def test_the_legacy_fields_are_left_alone_rather_than_reinterpreted(self):
        """Not migrated, and not quietly deleted either.

        Dropping a stored field nobody understands is as much a decision as
        importing it; the writer does neither, and this pins that down.
        """
        self.make_legacy()
        self.select("ep-1")

        row = json.loads(self.path().read_text("utf-8"))
        self.assertEqual(row["approvedEndpointId"], "ep-legacy")
        self.assertEqual(row["pin"]["endpointId"], "ep-legacy")
        self.assertNotIn("ep-legacy",
                         json.dumps(row["endpointSelections"]),
                         "no legacy value may appear anywhere in the selection state")


if __name__ == "__main__":
    unittest.main()
