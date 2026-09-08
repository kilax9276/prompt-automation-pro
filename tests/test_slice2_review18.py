# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 18: the recovery source loses UNKNOWN, and resolves ties by iteration.

The same two holes as the Prepare order, one path over. Refusing to name a
latest submitted delivery was right; answering that refusal with `None` was not,
because the caller reads `None` as "there is nothing" and falls back to the
source the browser named — an older delivery, chosen because a newer one could
not be read. UNKNOWN became absence, and absence became permission.

The second hole needs no damage at all: two deliveries sent at the same instant
are both provable and establish no order, and the sort simply took whichever
`Path.iterdir` yielded first.

Every state here comes from `create_job`, a real `CLAIM` and a real
`SEND_STATE`. Where a test needs damage it damages exactly one field, and where
it needs an equal instant it freezes the product clock instead of writing one.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s2")
sys.path.insert(0, str(CONSOLE))

import delivery_manager as dm_module
from delivery_manager import DeliveryError, DeliveryManager

PAGE = "https://chatgpt.com/c/abc"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class RecoverySourceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_job(self, *, tab=7):
        return self.dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)

    def sent_job(self, *, tab=7, token="tok"):
        job = self.new_job(tab=tab)
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})
        sent = self.dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": token, "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")
        return sent

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def damage(self, job, field, value):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body[field] = value
        path.write_text(json.dumps(body), encoding="utf-8")


class UnprovableIsNotAbsent(RecoverySourceFixture):
    def test_an_unreadable_submitted_time_is_reported_as_unprovable(self):
        self.sent_job()
        j2 = self.sent_job()
        self.damage(j2, "sentAt", "not-a-time")

        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn("sentAt", reason)

    def test_the_named_source_is_not_used_over_an_unprovable_latest(self):
        """The defect, end to end: an older explicit source chosen by fallback."""
        j1 = self.sent_job()
        j2 = self.sent_job()
        self.damage(j2, "sentAt", "not-a-time")

        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])

        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_a_named_source_with_an_unusable_time_is_refused_too(self):
        j1 = self.sent_job()
        self.damage(j1, "sentAt", "2026-01-01T00:00:00")     # naive, one field

        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])

        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_absent_is_still_absent(self):
        """The two answers must stay apart in both directions."""
        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_ABSENT)
        self.assertIsNone(job)
        self.assertEqual(reason, "")
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(tab_id=7, page_url=PAGE)
        self.assertIn("no submitted PAP delivery found", str(cm.exception))

    def test_the_lookup_works_again_once_the_damage_is_repaired(self):
        self.sent_job()
        j2 = self.sent_job()
        original = self.stored(j2)["sentAt"]
        self.damage(j2, "sentAt", "not-a-time")
        self.assertEqual(self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)[0],
                         self.dm.SUBMITTED_UNPROVABLE)

        self.damage(j2, "sentAt", original)

        state, job, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(job["jobId"], j2["jobId"])


class EveryUnknownBranchFailsClosed(RecoverySourceFixture):
    """The three remaining ways a hole in the evidence became empty space.

    Each one skipped a candidate and let an older delivery be called the
    latest. Only one skip is legitimate — a delivery proven older than the
    recovery window — because that is a fact about the delivery rather than a
    gap in what is known about it.
    """

    def test_a_future_submitted_time_is_unprovable_not_a_skip(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage(j2, "sentAt", iso(dm_module.utc_now_dt() + timedelta(hours=1)))

        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn("future", reason)
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_an_unreadable_delivery_job_is_unprovable_not_a_skip(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.dm.job_path(j2["runId"], j2["jobId"]).write_text("{broken", encoding="utf-8")

        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn("unreadable", reason)
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_a_submitted_job_with_no_time_evidence_is_unprovable(self):
        """A damaged state, not a shape the writer produces.

        No single field reaches it: the status still proves the delivery was
        submitted while every timestamp that could place it in time is gone.
        That is the point — the job is plainly not absent, so the lookup must
        not answer as though it were.
        """
        self.sent_job()
        j2 = self.sent_job(token="tok2")
        for field in ("consumedAt", "sentAt", "updatedAt", "createdAt"):
            self.damage(j2, field, None)

        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn("no timestamp", reason)

    def test_a_delivery_proven_older_than_the_window_is_still_excluded(self):
        """The one legitimate skip, kept: proven old is a fact, not a gap."""
        old_job = self.sent_job()
        self.damage(old_job, "sentAt", iso(dm_module.utc_now_dt() - timedelta(hours=3)))
        self.damage(old_job, "updatedAt", iso(dm_module.utc_now_dt() - timedelta(hours=3)))
        self.damage(old_job, "createdAt", iso(dm_module.utc_now_dt() - timedelta(hours=3)))

        state, job, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_ABSENT)
        self.assertIsNone(job)


class EqualSubmittedInstantsAreNotAnOrder(RecoverySourceFixture):
    def two_sent_at_the_same_instant(self):
        """Two deliveries the writer itself stamped with one instant.

        The clock is held still across both `SEND_STATE` calls, so both values
        are written by the product. An earlier version of this fixture froze
        the clock and then copied one `sentAt` onto the other by hand, which
        proved rather less than it claimed.
        """
        j1 = self.new_job()
        self.dm.update_from_client("run1", j1["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        frozen = dm_module.utc_now()
        real = dm_module.utc_now
        dm_module.utc_now = lambda: frozen
        try:
            j1 = self.dm.update_from_client("run1", j1["jobId"], {
                "event": "SEND_STATE", "tabId": 7, "leaseToken": "tok", "state": "SENT"})
            j2 = self.sent_job(token="tok2")
        finally:
            dm_module.utc_now = real
        self.assertEqual(self.stored(j1)["sentAt"], self.stored(j2)["sentAt"],
                         "both instants written by the writer, neither by the test")
        return j1, j2

    def test_a_tie_is_unprovable_not_the_first_one_found(self):
        self.two_sent_at_the_same_instant()

        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn("share the newest instant", reason)

    def test_a_tie_produces_no_automatic_recovery_source(self):
        j1, _j2 = self.two_sent_at_the_same_instant()
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_a_clear_newest_is_still_resolved(self):
        """The ordinary path stays: one proven latest wins over an older name."""
        j1 = self.sent_job()
        j2 = self.sent_job()

        source, reason = self.dm.resolve_recovery_source(
            tab_id=7, page_url=PAGE,
            source_run_id=j1["runId"], source_job_id=j1["jobId"])

        self.assertEqual(source["jobId"], j2["jobId"])
        self.assertEqual(reason, "LATEST_SUBMITTED_SAME_TAB_PAGE")


if __name__ == "__main__":
    unittest.main()
