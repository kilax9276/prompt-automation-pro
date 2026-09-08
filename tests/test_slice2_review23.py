# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 23: an existing replay that cannot be identified is not a missing one.

`create_recovery_replay` asks whether it has already made a replay for this
source, so that repeating the request does not produce a second delivery. The
question was answered with a job or `None`, and `None` covered both "there is no
such replay" and "there is a replay whose identity I cannot read". The second
reading let the caller act: a new job written to disk, and the existing replay
marked `SUPERSEDED` — a terminal mutation decided by a hole in the evidence.

The writer marks its replays with `recoveryReplay: True`, so an ordinary
delivery without `recoveryOf` is not damaged, it is simply not a replay. That
distinction is what keeps this fail-closed rule from stopping everything.
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

    def sent_source(self, *, tab=7, token="tok"):
        job = self.dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})
        return self.dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": token, "state": "SENT"})

    def replay_for(self, source, *, tab=7):
        return self.dm.create_recovery_replay(
            tab_id=tab, page_url=PAGE,
            source_run_id=source["runId"], source_job_id=source["jobId"],
            reason="test")

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def job_count(self):
        return len(list((self.data / "run1" / "executor" / "delivery").iterdir()))

    def damage(self, job, field, value):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        if value is None:
            body.pop(field, None)
        else:
            body[field] = value
        path.write_text(json.dumps(body), encoding="utf-8")


class RepeatingTheRequestIsIdempotent(RecoveryReplayFixture):
    def test_the_canonical_repeat_returns_the_same_replay(self):
        source = self.sent_source()
        first = self.replay_for(source)
        before = self.job_count()

        again = self.replay_for(source)

        self.assertEqual(again["jobId"], first["jobId"])
        self.assertEqual(self.job_count(), before, "no second replay was written")


class AnUnprovableReplayIdentityStopsEverything(RecoveryReplayFixture):
    def assert_refused_without_touching_anything(self, replay, source):
        before = self.job_count()

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)

        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))
        self.assertEqual(self.job_count(), before, "nothing new may be written")
        self.assertNotEqual(self.stored(replay)["status"], "SUPERSEDED",
                            "and nothing may be retired on evidence with a hole in it")

    def test_a_missing_recovery_of_is_not_a_missing_replay(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "recoveryOf", None)          # exactly the field under test

        self.assert_refused_without_touching_anything(replay, source)

    def test_a_malformed_recovery_of_is_not_a_missing_replay(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "recoveryOf", "not-an-object")

        self.assert_refused_without_touching_anything(replay, source)

    def test_a_recovery_of_without_a_source_job_is_not_a_missing_replay(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = dict(self.stored(replay)["recoveryOf"])
        body.pop("jobId")
        self.damage(replay, "recoveryOf", body)

        self.assert_refused_without_touching_anything(replay, source)

    def test_the_repeat_finds_the_replay_again_once_it_is_repaired(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        original = self.stored(replay)["recoveryOf"]
        self.damage(replay, "recoveryOf", None)
        with self.assertRaises(DeliveryError):
            self.replay_for(source)

        self.damage(replay, "recoveryOf", original)

        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])


class OrdinaryJobsAreNotDamagedReplays(RecoveryReplayFixture):
    """The discriminator earns its place: most jobs have no `recoveryOf`."""

    def test_a_plain_delivery_without_recovery_of_is_simply_not_a_replay(self):
        source = self.sent_source()
        self.dm.create_job(
            "run1",
            {"papSource": {"tabId": 7, "url": PAGE, "chatType": "chatgpt"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "another", "open", 8 * 1024 * 1024, 120)

        replay = self.replay_for(source)

        self.assertTrue(replay.get("recoveryReplay"))
        self.assertEqual(replay["recoveryOf"]["jobId"], source["jobId"])

    def test_a_replay_for_another_source_is_still_only_a_skip(self):
        first_source = self.sent_source()
        first_replay = self.replay_for(first_source)
        second_source = self.sent_source(token="tok2")

        second_replay = self.replay_for(second_source)

        self.assertNotEqual(second_replay["jobId"], first_replay["jobId"])
        self.assertEqual(second_replay["recoveryOf"]["jobId"], second_source["jobId"])


if __name__ == "__main__":
    unittest.main()
