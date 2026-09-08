# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 25: replay identity is one writer contract, not four loose filters.

A recovery replay is written atomically with recoveryReplay=True, recoveryOf,
target and dispatchEpoch.  Once any half of that persisted proof says that a
row is (or may be) the replay for the requested source, a damaged companion
field cannot be treated as evidence that the replay is absent: the caller would
write a second delivery and can terminally supersede the first one.

Fixtures here are writer-produced only.  Each negative case corrupts exactly
one persisted field after create_job/CLAIM/SEND_STATE/create_recovery_replay.
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

from delivery_manager import DeliveryError, DeliveryManager, PAUSED_JOB_STATE

PAGE = "https://chatgpt.com/c/abc"
MISSING = object()


class RecoveryReplayWriterContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sent_source(self, *, token="source-token", tab_id=7, page=PAGE):
        job = self.dm.create_job(
            "run1",
            {"papSource": {"tabId": tab_id, "url": page, "chatType": "chatgpt", "endpointId": f"ep-{tab_id}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": page, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab_id, "leaseToken": token, "url": page})
        return self.dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab_id, "leaseToken": token, "state": "SENT"})

    def replay_for(self, source, *, manager=None):
        manager = manager or self.dm
        target = source["target"]
        return manager.create_recovery_replay(
            tab_id=target["tabId"], page_url=target["url"],
            source_run_id=source["runId"], source_job_id=source["jobId"],
            reason="review25")

    def stored(self, job, *, manager=None):
        manager = manager or self.dm
        return manager.get_job(job["runId"], job["jobId"])

    def damage(self, job, field, value=MISSING):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        if value is MISSING:
            body.pop(field, None)
        else:
            body[field] = value
        path.write_text(json.dumps(body), encoding="utf-8")

    def job_count(self):
        return len(list((self.data / "run1" / "executor" / "delivery").iterdir()))

    def delivery_bytes(self):
        delivery = self.data / "run1" / "executor" / "delivery"
        return {
            path.relative_to(delivery).as_posix(): path.read_bytes()
            for path in sorted(delivery.rglob("*"))
            if path.is_file()
        }

    def assert_unprovable_without_mutation(self, source, replay):
        count_before = self.job_count()
        status_before = self.stored(replay)["status"]
        bytes_before = self.delivery_bytes()

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)

        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))
        self.assertEqual(self.job_count(), count_before, "no second job directory may be created")
        self.assertEqual(self.stored(replay)["status"], status_before,
                         "the existing replay must not be terminally mutated")
        self.assertEqual(self.delivery_bytes(), bytes_before,
                         "the refusal must happen before every persisted write")


class ReplayMarkerIsPartOfTheProof(RecoveryReplayWriterContract):
    def test_a_missing_recovery_replay_marker_is_not_absence(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "recoveryReplay")
        self.assert_unprovable_without_mutation(source, replay)

    def assert_bad_marker_is_unprovable(self, damaged):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "recoveryReplay", damaged)
        self.assert_unprovable_without_mutation(source, replay)

    def test_recovery_replay_integer_one_is_not_true(self):
        self.assert_bad_marker_is_unprovable(1)

    def test_recovery_replay_string_true_is_not_true(self):
        self.assert_bad_marker_is_unprovable("true")

    def test_recovery_replay_false_is_not_a_plain_job(self):
        self.assert_bad_marker_is_unprovable(False)

    def test_repairing_the_marker_restores_idempotence(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "recoveryReplay")
        with self.assertRaises(DeliveryError):
            self.replay_for(source)
        self.damage(replay, "recoveryReplay", True)
        before = self.job_count()
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])
        self.assertEqual(self.job_count(), before)


class RecoveryOfIdentityIsStrict(RecoveryReplayWriterContract):
    def assert_bad_recovery_of_is_unprovable(self, field, damaged):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = self.stored(replay)
        recovery_of = dict(body["recoveryOf"])
        recovery_of[field] = damaged
        self.damage(replay, "recoveryOf", recovery_of)
        self.assert_unprovable_without_mutation(source, replay)

    def test_numeric_recovery_of_run_id_is_not_another_source(self):
        self.assert_bad_recovery_of_is_unprovable("runId", 7)

    def test_numeric_recovery_of_job_id_is_not_another_source(self):
        self.assert_bad_recovery_of_is_unprovable("jobId", 7)


class DispatchEpochMustMatchTheLifecycle(RecoveryReplayWriterContract):
    def test_an_active_replay_with_a_foreign_epoch_is_contradictory(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "dispatchEpoch", "epoch-zzz")
        self.assert_unprovable_without_mutation(source, replay)

    def assert_bad_epoch_is_unprovable(self, damaged):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "dispatchEpoch", damaged)
        self.assert_unprovable_without_mutation(source, replay)

    def test_an_active_replay_without_dispatch_epoch_is_unprovable(self):
        self.assert_bad_epoch_is_unprovable(MISSING)

    def test_an_active_replay_with_null_dispatch_epoch_is_unprovable(self):
        self.assert_bad_epoch_is_unprovable(None)

    def test_an_active_replay_with_numeric_dispatch_epoch_is_unprovable(self):
        self.assert_bad_epoch_is_unprovable(1)

    def test_an_active_replay_with_empty_dispatch_epoch_is_unprovable(self):
        self.assert_bad_epoch_is_unprovable("")

    def test_a_canonical_restart_pause_is_still_the_existing_replay(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        restarted = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-2")
        changed = restarted.pause_unfinished_jobs_after_restart()
        self.assertIn(replay["jobId"], {job["jobId"] for job in changed})
        paused = self.stored(replay, manager=restarted)
        self.assertEqual(paused["status"], PAUSED_JOB_STATE)
        self.assertIsNone(paused["dispatchEpoch"])

        before = self.job_count()
        again = self.replay_for(source, manager=restarted)
        self.assertEqual(again["jobId"], replay["jobId"])
        self.assertEqual(self.job_count(), before, "a restart must not manufacture a duplicate replay")

    def test_repairing_the_epoch_restores_idempotence(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "dispatchEpoch", "epoch-zzz")
        with self.assertRaises(DeliveryError):
            self.replay_for(source)
        self.damage(replay, "dispatchEpoch", "epoch-1")
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])


class StatusCannotBeCoercedIntoAValidLifecycle(RecoveryReplayWriterContract):
    def test_a_non_string_status_is_unprovable(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "status", 42)
        self.assert_unprovable_without_mutation(source, replay)

    def test_an_unknown_status_is_unprovable(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.damage(replay, "status", "READY")
        self.assert_unprovable_without_mutation(source, replay)


class TheTwoProvenNonMatchesStayLegal(RecoveryReplayWriterContract):
    def test_a_plain_writer_job_is_not_a_replay(self):
        source = self.sent_source()
        plain = self.dm.create_job(
            "run1",
            {"papSource": {"tabId": 7, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{7}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "plain", "open", 8 * 1024 * 1024, 120)
        stored_plain = self.stored(plain)
        self.assertNotIn("recoveryReplay", stored_plain)
        self.assertNotIn("recoveryOf", stored_plain)

        replay = self.replay_for(source)
        self.assertEqual(replay["recoveryOf"]["jobId"], source["jobId"])

    def test_a_replay_proven_to_name_another_source_is_skipped(self):
        first_source = self.sent_source(token="first")
        first_replay = self.replay_for(first_source)
        second_source = self.sent_source(token="second")
        second_replay = self.replay_for(second_source)
        self.assertNotEqual(second_replay["jobId"], first_replay["jobId"])
        self.assertEqual(second_replay["recoveryOf"]["jobId"], second_source["jobId"])

    def test_a_foreign_replay_with_an_unreadable_target_is_not_silently_skipped(self):
        first_source = self.sent_source(token="first")
        second_source = self.sent_source(token="second", tab_id=8)
        first_replay = self.replay_for(first_source)
        self.damage(first_replay, "target", "broken")

        count_before = self.job_count()
        status_before = self.stored(first_replay)["status"]
        bytes_before = self.delivery_bytes()
        state, found, why = self.dm._existing_recovery_replay(
            second_source["runId"], second_source["jobId"],
            second_source["target"]["tabId"], second_source["target"]["url"])
        self.assertEqual(state, self.dm.REPLAY_UNPROVABLE)
        self.assertIsNone(found)
        self.assertIn("target", why)

        # The public path may fail even earlier in source resolution because
        # that layer is fail-closed on unreadable targets too. Either way the
        # operation must stop before every persisted mutation.
        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(second_source)
        self.assertIn("UNPROVABLE", str(cm.exception))
        self.assertEqual(self.job_count(), count_before)
        self.assertEqual(self.stored(first_replay)["status"], status_before)
        self.assertEqual(self.delivery_bytes(), bytes_before)

    def test_a_foreign_active_replay_with_a_broken_epoch_is_not_silently_skipped(self):
        first_source = self.sent_source(token="first")
        second_source = self.sent_source(token="second", tab_id=8)
        first_replay = self.replay_for(first_source)
        self.damage(first_replay, "dispatchEpoch", "epoch-zzz")
        self.assert_unprovable_without_mutation(second_source, first_replay)

    def test_a_foreign_replay_with_a_bad_status_is_not_silently_skipped(self):
        first_source = self.sent_source(token="first")
        second_source = self.sent_source(token="second", tab_id=8)
        first_replay = self.replay_for(first_source)
        self.damage(first_replay, "status", 42)
        self.assert_unprovable_without_mutation(second_source, first_replay)

    def test_the_canonical_repeat_is_idempotent(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        before = self.job_count()
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])
        self.assertEqual(self.job_count(), before)


if __name__ == "__main__":
    unittest.main()
