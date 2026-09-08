# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 24: a replay that names this source cannot silently acquire another target.

`recoveryOf` identifies the source delivery. The replay writer derives the replay
target from that source, so a persisted replay that names the exact source but
claims another tab/page is contradictory evidence. It is not a legitimate replay
for somebody else and must not be skipped or returned as a match.
"""
from __future__ import annotations

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

from delivery_manager import DeliveryError, DeliveryManager

PAGE = "https://chatgpt.com/c/abc"
OTHER_PAGE = "https://chatgpt.com/c/other"


class RecoveryReplayFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sent_source(self, *, token="source-token"):
        job = self.dm.create_job(
            "run1",
            {"papSource": {"tabId": 7, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{7}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": token, "url": PAGE})
        return self.dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": 7, "leaseToken": token, "state": "SENT"})

    def replay_for(self, source):
        return self.dm.create_recovery_replay(
            tab_id=7, page_url=PAGE,
            source_run_id=source["runId"], source_job_id=source["jobId"],
            reason="test")

    def job_count(self):
        return len(list((self.data / "run1" / "executor" / "delivery").iterdir()))

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def write_body(self, job, body):
        self.dm.job_path(job["runId"], job["jobId"]).write_text(
            json.dumps(body), encoding="utf-8")

    def damage_target(self, replay, **changes):
        body = self.stored(replay)
        body["target"].update(changes)
        self.write_body(replay, body)

    def assert_unprovable_without_new_job(self, source, replay):
        before = self.job_count()
        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)
        self.assertIn("UNPROVABLE", str(cm.exception))
        self.assertEqual(self.job_count(), before)
        self.assertNotEqual(self.stored(replay)["status"], "SUPERSEDED")


class SameSourceCannotAcquireAnotherTarget(RecoveryReplayFixture):
    def test_same_source_with_another_tab_is_corrupt_not_absent(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage_target(replay, tabId=8)
        self.assert_unprovable_without_new_job(source, replay)

    def test_same_source_with_another_page_is_corrupt_not_a_match(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage_target(replay, url=OTHER_PAGE)
        self.assert_unprovable_without_new_job(source, replay)

    def test_the_repeat_finds_the_replay_after_the_page_is_repaired(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        original = self.stored(replay)["target"]["url"]
        self.damage_target(replay, url=OTHER_PAGE)
        with self.assertRaises(DeliveryError):
            self.replay_for(source)

        self.damage_target(replay, url=original)
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])


class ExistingFailClosedCasesStayClosed(RecoveryReplayFixture):
    def test_a_missing_url_is_still_unprovable(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = self.stored(replay)
        body["target"].pop("url")
        self.write_body(replay, body)
        self.assert_unprovable_without_new_job(source, replay)

    def test_the_canonical_pending_repeat_is_idempotent(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        before = self.job_count()
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])
        self.assertEqual(self.job_count(), before)

    def test_a_replay_for_another_source_is_still_a_legal_skip(self):
        first_source = self.sent_source(token="source-one")
        first_replay = self.replay_for(first_source)
        second_source = self.sent_source(token="source-two")
        second_replay = self.replay_for(second_source)
        self.assertNotEqual(second_replay["jobId"], first_replay["jobId"])
        self.assertEqual(second_replay["recoveryOf"]["jobId"], second_source["jobId"])


if __name__ == "__main__":
    unittest.main()
