# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 26 audit: two writer-produced replay states the new contract mishandles.

Nothing here is corrupted by hand. Every state below is written by the product
itself — `create_job`, `CLAIM`, `SEND_STATE`, `create_recovery_replay`,
`pause_unfinished_jobs_after_restart` and the supersede inside `create_job` —
which is what makes both findings fail-always rather than fail-closed.

Place at tests/test_slice2_review26_audit.py and run from the tree root.
"""
from __future__ import annotations

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


class ReplayLifecycleAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda r: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def prepare(self, manager=None, message="m", tab=7):
        dm = manager or self.dm
        return dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, message, "open", 8 * 1024 * 1024, 120)

    def sent(self, manager=None, message="m", token="tok", tab=7):
        dm = manager or self.dm
        job = self.prepare(dm, message, tab)
        dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})
        return dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": token, "state": "SENT"})

    def replay_for(self, source, manager=None):
        dm = manager or self.dm
        return dm.create_recovery_replay(
            tab_id=7, page_url=PAGE, source_run_id=source["runId"],
            source_job_id=source["jobId"], reason="audit")

    # ---- finding 1 -------------------------------------------------------

    def test_a_paused_then_superseded_replay_does_not_kill_recovery(self):
        """Restart pauses the replay (epoch null); a later Prepare retires it.

        Both writes are the product's own. The result is a terminal replay
        whose stored epoch is null, which the new lifecycle rule reads as a
        contradiction — and the scan reports it before it reaches the source
        it was asked about, so every recovery request in the tree refuses.
        """
        source = self.sent()
        self.replay_for(source)

        restarted = DeliveryManager(self.root, self.data, lambda r: "terminal log\n", "epoch-2")
        restarted.pause_unfinished_jobs_after_restart()
        self.prepare(restarted, "a new prepare for the same tab")

        state, _job, why = restarted._existing_recovery_replay(
            source["runId"], source["jobId"], 7, PAGE)
        self.assertNotEqual(state, restarted.REPLAY_UNPROVABLE,
                            f"a writer-produced state must not be a contradiction: {why}")

    def test_an_unrelated_source_can_still_be_recovered(self):
        """The blast radius: the refusal is not scoped to the damaged row."""
        source = self.sent()
        self.replay_for(source)
        restarted = DeliveryManager(self.root, self.data, lambda r: "terminal log\n", "epoch-2")
        restarted.pause_unfinished_jobs_after_restart()
        self.prepare(restarted, "a new prepare for the same tab")

        other = self.sent(restarted, "unrelated", token="tok2")
        try:
            restarted.create_recovery_replay(
                tab_id=7, page_url=PAGE, source_run_id=other["runId"],
                source_job_id=other["jobId"], reason="audit")
        except DeliveryError as exc:
            self.fail(f"recovery for an unrelated source was refused: {exc}")

    # ---- finding 2 -------------------------------------------------------

    def test_a_replay_retired_before_delivery_does_not_end_recovery_for_ever(self):
        """A replay superseded while still PENDING was never delivered.

        Returning it as the existing replay means the source can never get
        another one: the answer is terminal, and the delivery it was created
        for never happened.
        """
        source = self.sent()
        first = self.replay_for(source)
        self.prepare(self.dm, "a new prepare for the same tab")
        retired = self.dm.get_job(first["runId"], first["jobId"])
        self.assertEqual(retired["status"], "SUPERSEDED")
        self.assertEqual(retired["messageState"], "PENDING",
                         "the retired replay was never inserted into the chat")

        again = self.replay_for(source)

        self.assertNotEqual(
            again["jobId"], first["jobId"],
            "an undelivered retired replay must not be returned as the existing one")


if __name__ == "__main__":
    unittest.main()
