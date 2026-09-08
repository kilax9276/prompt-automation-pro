# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 15: the lease boundary race, and the chunk authorization bypass.

Both findings are the previous ones seen from one step further out. Review 14
established that an outstanding delivery must block the tab; this file
establishes that "outstanding" has to include the moment a lease stops being
ACTIVE and has not yet been recovered — the classification is taken twice from
two different clock readings, and between them a lease can change state.

The second finding is the same shape at the level of a signature: an obligation
that only holds when the caller passes the right arguments is not an
obligation. The HTTP route passes them; the method must not depend on that.

Every persisted job here comes from `create_job`, the real writer, and every
lease from a real `CLAIM`. Only the one field a test is about is damaged
afterwards.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s2")
sys.path.insert(0, str(CONSOLE))

import delivery_manager as dm_module
from delivery_manager import DeliveryError, DeliveryManager

PAGE = "https://chatgpt.com/c/abc"


class Clock:
    """A clock the test advances by hand.

    Sleeping to reach a lease boundary makes a test that is slow when it works
    and flaky when it does not. What the defect needs is not real time, it is
    two different readings around one decision — so the readings are controlled
    and the code under test is untouched.
    """

    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self):
        return self.now


class WriterFixture(unittest.TestCase):
    """Jobs produced by the product writer, never assembled by hand."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create_job(self, *, tab=7, run_id="run1", manager=None):
        dm = manager or self.dm
        return dm.create_job(
            run_id,
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{tab}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []},
            {"steps": {}},
            "message",
            "open",
            8 * 1024 * 1024,
            120,
        )

    def claim(self, job, *, tab=7, token="tok", manager=None):
        dm = manager or self.dm
        return dm.update_from_client(job["runId"], job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})

    def stored(self, job, *, manager=None):
        dm = manager or self.dm
        return dm.get_job(job["runId"], job["jobId"])

    def damage(self, job, field, value, *, manager=None):
        """Damage exactly one field of a state the real writer produced."""
        dm = manager or self.dm
        path = dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body[field] = value
        path.write_text(json.dumps(body), encoding="utf-8")
        return body


class LeaseBoundaryRace(WriterFixture):
    """A lease that expires between the recovery pass and the decision.

    `poll_for_tab` recovers first and classifies afterwards, and each
    classification reads the clock again. A lease that was ACTIVE during
    recovery — and so was left alone, correctly — can be EXPIRED by the time
    the decision is taken. An EXPIRED lease that has not been through recovery
    is an outcome nobody has accounted for, and it must not open the tab.
    """

    def poll_with_time_passing_after_recovery(self, seconds=20):
        clock = Clock()
        real_now_dt = dm_module.utc_now_dt
        real_recover = self.dm.recover_expired_leases

        def recover_then_time_passes():
            result = real_recover()
            clock.advance(seconds)
            return result

        dm_module.utc_now_dt = clock
        self.dm.recover_expired_leases = recover_then_time_passes
        try:
            return self.dm.poll_for_tab(7, PAGE)
        finally:
            dm_module.utc_now_dt = real_now_dt
            del self.dm.recover_expired_leases

    def test_a_lease_expiring_after_recovery_does_not_open_the_tab(self):
        j1 = self.create_job()
        self.claim(j1)
        j2 = self.create_job()
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")

        offered = self.poll_with_time_passing_after_recovery()

        self.assertIsNone(
            offered,
            "an unrecovered EXPIRED lease is an unknown outcome, not a free tab")


    def test_the_expired_job_itself_is_not_handed_out_either(self):
        """The old job is not the safe answer: its own outcome is unknown too."""
        j1 = self.create_job()
        self.claim(j1)
        offered = self.poll_with_time_passing_after_recovery()
        self.assertIsNone(offered)

    def test_the_next_poll_recovers_first_and_then_proceeds(self):
        """Blocking one iteration is not a deadlock: recovery runs next time."""
        j1 = self.create_job()
        self.claim(j1)
        j2 = self.create_job()
        self.assertIsNone(self.poll_with_time_passing_after_recovery())

        # Real time now, lease genuinely past its term: the ordinary path.
        self.damage(j1, "claimExpiresAt",
                    (datetime.now(timezone.utc) - timedelta(seconds=1))
                    .isoformat().replace("+00:00", "Z"))
        offered = self.dm.poll_for_tab(7, PAGE)

        self.assertIn("leaseRecoveredAt", self.stored(j1))
        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], j2["jobId"])

    def test_an_expired_lease_is_reported_by_outstanding_lease_for_tab(self):
        j1 = self.create_job()
        self.claim(j1)
        self.damage(j1, "claimExpiresAt",
                    (datetime.now(timezone.utc) - timedelta(seconds=1))
                    .isoformat().replace("+00:00", "Z"))
        outstanding = self.dm.outstanding_lease_for_tab(7)
        self.assertIsNotNone(outstanding, "EXPIRED must be visible as outstanding")
        self.assertEqual(outstanding["lease"], self.dm.LEASE_EXPIRED)


class ChunkAuthorizationIsUnconditional(WriterFixture):
    """The obligation cannot depend on the caller passing the right arguments.

    `MAP-085` and `ACC-S2-035` say reading attachment bytes requires a trusted
    tab and an ACTIVE lease. With both parameters optional the manager handed
    out bytes to a caller that named neither, and the contract held only
    because the one route that exists happens to pass them.
    """

    def attachment_of(self, job):
        attachments = job.get("attachments") or []
        self.assertTrue(attachments, "create_job always materialises the terminal log")
        return attachments[0]["attachmentId"]

    def test_reading_without_tab_and_lease_is_impossible(self):
        job = self.create_job()
        self.assertEqual(self.dm.classify_lease(self.stored(job))[0], self.dm.LEASE_NONE)
        with self.assertRaises(TypeError):
            self.dm.attachment_chunk(job["runId"], job["jobId"], self.attachment_of(job), 0, 1024)

    def test_reading_without_a_lease_is_refused_even_with_the_right_tab(self):
        job = self.create_job()
        with self.assertRaises(DeliveryError) as cm:
            self.dm.attachment_chunk(job["runId"], job["jobId"], self.attachment_of(job),
                                     0, 1024, tab_id=7, lease_token="tok")
        self.assertIn("DELIVERY_NOT_LEASED", str(cm.exception))

    def test_the_holder_of_the_lease_still_reads(self):
        job = self.create_job()
        self.claim(job)
        out = self.dm.attachment_chunk(job["runId"], job["jobId"], self.attachment_of(job),
                                       0, 1024, tab_id=7, lease_token="tok")
        self.assertGreater(out["bytes"], 0)
        self.assertTrue(out["eof"])

    def test_the_signature_offers_no_bypass(self):
        """Structural: an optional check is the defect, not the wording of it."""
        src = (CONSOLE / "delivery_manager.py").read_text("utf-8")
        head = src.split("    def attachment_chunk(", 1)[1].split("-> dict[str, Any]:", 1)[0]
        self.assertNotIn("tab_id: int | None = None", head)
        self.assertNotIn("lease_token: str = ''", head)
        body = src.split("    def attachment_chunk(", 1)[1].split("\n    def ", 1)[0]
        self.assertNotIn("if tab_id is not None:", body,
                         "authorization must not be conditional on the caller")


if __name__ == "__main__":
    unittest.main()
