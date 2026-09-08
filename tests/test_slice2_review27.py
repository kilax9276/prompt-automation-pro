# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 27: replay lifecycle must distinguish history from delivered result."""
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


class RecoveryReplayLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda _r: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def prepare(self, manager=None, message="m", tab=7):
        dm = manager or self.dm
        return dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{tab}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, message, "open", 8 * 1024 * 1024, 120)

    def sent_source(self, manager=None, token="tok", tab=7):
        dm = manager or self.dm
        job = self.prepare(dm, "source", tab)
        dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})
        return dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": token, "state": "SENT"})

    def replay_for(self, source, manager=None):
        dm = manager or self.dm
        return dm.create_recovery_replay(
            tab_id=7, page_url=PAGE,
            source_run_id=source["runId"], source_job_id=source["jobId"],
            reason="review27")

    def supersede_same_logical(self, replay, manager=None, message="replacement"):
        """Retire a replay through the Slice-4 writer, not an unrelated Prepare."""
        dm = manager or self.dm
        target = replay["target"]
        return dm.create_job(
            replay["runId"],
            {"papSource": {
                "tabId": target["tabId"],
                "url": target["url"],
                "chatType": target["chatType"],
                "endpointId": target["endpointId"],
                "browserEpoch": target["browserEpoch"],
                "conversationId": target["conversationId"],
                "projectId": target.get("projectId"),
            }, "page": target["url"], "chatType": target["chatType"], "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, message, "open", 8 * 1024 * 1024, 120,
            delivery_session_id=replay.get("deliverySessionId"),
            logical_delivery_id=replay["logicalDeliveryId"],
            side_effect_key=replay["sideEffectKey"],
        )

    def write(self, job, body):
        self.dm.job_path(job["runId"], job["jobId"]).write_text(
            json.dumps(body), encoding="utf-8")

    def test_bare_null_epoch_on_terminal_replay_is_still_unprovable(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = self.dm.get_job(replay["runId"], replay["jobId"])
        body["status"] = "SUPERSEDED"
        body["dispatchEpoch"] = None
        self.write(replay, body)

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)
        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))

    def test_null_epoch_requires_usable_pause_provenance(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        restarted = DeliveryManager(self.root, self.data, lambda _r: "terminal log\n", "epoch-2")
        restarted.pause_unfinished_jobs_after_restart()
        self.supersede_same_logical(replay, manager=restarted, message="retire paused replay")

        body = restarted.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(body["status"], "SUPERSEDED")
        self.assertIsNone(body["dispatchEpoch"])
        body["pausedAt"] = "not-a-time"
        restarted.job_path(replay["runId"], replay["jobId"]).write_text(
            json.dumps(body), encoding="utf-8")

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source, manager=restarted)
        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))

    def test_retired_replay_with_unknown_send_state_is_not_treated_as_absent(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.supersede_same_logical(replay, message="retire pending replay")
        body = self.dm.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(body["status"], "SUPERSEDED")
        body["sendState"] = "MYSTERY"
        self.write(replay, body)

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)
        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))

    def test_retired_replay_with_unresolved_send_request_is_unprovable(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        token = "replay-request-token"
        self.dm.update_from_client(replay["runId"], replay["jobId"], {
            "event": "CLAIM", "tabId": 7, "endpointId": "ep-7",
            "leaseToken": token, "url": PAGE})
        for attachment in replay.get("attachments") or []:
            self.dm.update_from_client(replay["runId"], replay["jobId"], {
                "event": "ATTACHMENT_STATE", "tabId": 7, "endpointId": "ep-7",
                "leaseToken": token, "attachmentId": attachment["attachmentId"],
                "state": "UPLOADED"})
        self.dm.update_from_client(replay["runId"], replay["jobId"], {
            "event": "MESSAGE_STATE", "tabId": 7, "endpointId": "ep-7",
            "leaseToken": token, "state": "INSERTED"})
        requested = self.dm.request_send(replay["runId"], replay["jobId"])
        self.assertEqual(requested["sendState"], "SEND_REQUESTED")
        self.dm.update_from_client(replay["runId"], replay["jobId"], {
            "event": "RELEASE", "tabId": 7, "endpointId": "ep-7",
            "leaseToken": token, "url": PAGE})
        self.supersede_same_logical(replay, message="retire send-requested replay")

        stored = self.dm.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(stored["status"], "SUPERSEDED")
        self.assertEqual(stored["sendState"], "SEND_REQUESTED")
        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)
        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))

    def test_paused_replay_is_not_superseded_by_unrelated_logical_delivery(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        restarted = DeliveryManager(self.root, self.data, lambda _r: "terminal log\n", "epoch-2")
        restarted.pause_unfinished_jobs_after_restart()
        self.prepare(restarted, "unrelated prepare")

        body = restarted.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(body["status"], "PAUSED_AFTER_RESTART")
        self.assertIsNone(body["dispatchEpoch"])
        again = restarted.create_recovery_replay(
            tab_id=7, page_url=PAGE, source_run_id=source["runId"],
            source_job_id=source["jobId"], reason="test")
        self.assertEqual(again["jobId"], replay["jobId"])

    def test_pending_replay_survives_unrelated_prepare(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.prepare(self.dm, "unrelated prepare")
        body = self.dm.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(body["status"], "QUEUED")
        again = self.replay_for(source)
        self.assertEqual(again["jobId"], replay["jobId"])

    def test_unrelated_prepare_cannot_terminalize_replay_with_outstanding_state(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = self.dm.get_job(replay["runId"], replay["jobId"])
        body["sendState"] = "SEND_REQUESTED"
        body["status"] = "SEND_REQUESTED"
        self.write(replay, body)
        self.prepare(self.dm, "unrelated prepare")

        stored = self.dm.get_job(replay["runId"], replay["jobId"])
        self.assertEqual(stored["status"], "SEND_REQUESTED")
        self.assertEqual(stored["sendState"], "SEND_REQUESTED")

    def test_sent_or_consumed_cannot_carry_null_epoch_via_pause_provenance(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        body = self.dm.get_job(replay["runId"], replay["jobId"])
        body.update({
            "status": "SENT",
            "sendState": "SENT",
            "dispatchEpoch": None,
            "pauseReason": "BACKEND_RESTART",
            "pausedAt": body["createdAt"],
            "pausedFromDispatchEpoch": "epoch-1",
        })
        self.write(replay, body)

        with self.assertRaises(DeliveryError) as cm:
            self.replay_for(source)
        self.assertIn("RECOVERY_REPLAY_UNPROVABLE", str(cm.exception))

    def test_sent_replay_is_a_delivered_result_and_can_become_the_next_source(self):
        source = self.sent_source()
        replay = self.replay_for(source)
        self.dm.update_from_client("run1", replay["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "replay-token", "url": PAGE})
        sent = self.dm.update_from_client("run1", replay["jobId"], {
            "event": "SEND_STATE", "tabId": 7, "leaseToken": "replay-token", "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")

        restarted = DeliveryManager(self.root, self.data, lambda _r: "terminal log\n", "epoch-2")
        restarted.pause_unfinished_jobs_after_restart()
        state, existing, why = restarted._existing_recovery_replay(
            source["runId"], source["jobId"], 7, PAGE)
        self.assertEqual((state, why), (restarted.REPLAY_FOUND, ""))
        self.assertEqual(existing["jobId"], replay["jobId"])

        # Public recovery resolves the newest submitted delivery first; once the
        # replay itself was sent, it is that next source rather than a reason to
        # clone the original source again.
        next_replay = self.replay_for(source, manager=restarted)
        self.assertNotEqual(next_replay["jobId"], replay["jobId"])
        self.assertEqual(next_replay["recoveryOf"]["jobId"], replay["jobId"])


if __name__ == "__main__":
    unittest.main()
