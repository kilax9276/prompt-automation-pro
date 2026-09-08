# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 17: the time that decides which delivery is destroyed.

Deferred retirement writes `SUPERSEDED`, which is terminal, and it picks the job
to keep by comparing `createdAt` as a string. That is the same defect the time
invariant was written for, in the one place where getting it wrong is not a
misordering but a destroyed delivery: a malformed value sorts above every real
ISO timestamp, so the stale job becomes the keeper and the genuinely newer one
is retired.

Two shapes of the same hole are covered: unprovable time, and provable time that
does not establish an order. Neither may be resolved by guessing — not by
lexicographic luck, and not by the order `Path.iterdir` happens to return.
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


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class PrepareOrderFixture(unittest.TestCase):
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

    def event(self, job, body):
        return self.dm.update_from_client(job["runId"], job["jobId"], body)

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def damage(self, job, field, value):
        """Damage exactly one field of a state the real writer produced."""
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        if value is None:
            body.pop(field, None)
        else:
            body[field] = value
        path.write_text(json.dumps(body), encoding="utf-8")

    def released_pair(self):
        """The canonical situation the retirement was built for."""
        j1 = self.new_job()
        self.event(j1, {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        j2 = self.new_job()
        self.event(j1, {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        return j1, j2


class UnprovableCreatedAt(PrepareOrderFixture):
    """A timestamp that cannot be proven decides nothing, and destroys nothing."""

    def assert_nothing_was_decided(self, j1, j2):
        offered = self.dm.poll_for_tab(7, PAGE)
        self.assertIsNone(offered, "an unprovable Prepare order must not hand out work")
        self.assertNotEqual(self.stored(j2)["status"], "SUPERSEDED",
                            "the newer delivery must not be destroyed on unprovable evidence")
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")

    def test_malformed_created_at_is_not_an_order(self):
        j1, j2 = self.released_pair()
        self.damage(j1, "createdAt", "not-a-time")
        self.assert_nothing_was_decided(j1, j2)

    def test_naive_created_at_is_not_an_order(self):
        j1, j2 = self.released_pair()
        self.damage(j1, "createdAt", "2026-01-01T00:00:00")
        self.assert_nothing_was_decided(j1, j2)

    def test_missing_created_at_is_not_an_order(self):
        j1, j2 = self.released_pair()
        self.damage(j1, "createdAt", None)
        self.assert_nothing_was_decided(j1, j2)

    def test_damage_to_the_newer_job_blocks_the_tab_as_well(self):
        j1, j2 = self.released_pair()
        self.damage(j2, "createdAt", "not-a-time")
        self.assert_nothing_was_decided(j1, j2)

    def test_the_tab_resumes_once_the_damage_is_repaired(self):
        """Fail-closed is a stop, not a grave: an operator can still resolve it."""
        j1, j2 = self.released_pair()
        original = self.stored(j1)["createdAt"]
        self.damage(j1, "createdAt", "not-a-time")
        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

        self.damage(j1, "createdAt", original)
        offered = self.dm.poll_for_tab(7, PAGE)

        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], j2["jobId"])
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")


class AmbiguousPrepareOrder(PrepareOrderFixture):
    """Two provable timestamps that are equal do not establish an order.

    Produced by freezing the product clock across both `create_job` calls, so
    both persisted states are genuine writer output — no `job.json` is touched.
    """

    def two_jobs_created_at_the_same_instant(self):
        """Both writer-produced, both with the same valid createdAt.

        `j1` is claimed before `j2` is created, so the retirement that runs
        inside `create_job` is skipped for the lease — which is exactly how a
        pair of open jobs reaches the deferred retirement. There the keeper is
        no longer named by the caller and has to be derived from stored time.
        """
        frozen = dm_module.utc_now()
        real = dm_module.utc_now
        dm_module.utc_now = lambda: frozen
        try:
            j1 = self.new_job()
            self.event(j1, {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
            j2 = self.new_job()
        finally:
            dm_module.utc_now = real
        self.event(j1, {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        self.assertEqual(self.stored(j1)["createdAt"], self.stored(j2)["createdAt"])
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED",
                            "the claimed job is not retired at creation time")
        return j1, j2

    def test_an_ambiguous_order_retires_nothing(self):
        j1, j2 = self.two_jobs_created_at_the_same_instant()

        offered = self.dm.poll_for_tab(7, PAGE)

        self.assertNotEqual(self.stored(j2)["status"], "SUPERSEDED",
                            "the older job must not destroy the newer one by iteration order")
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.assertIsNone(offered, "neither can be proven newest, so neither is handed out")


class SubmittedAtIsAlsoADecision(PrepareOrderFixture):
    """The recovery source is chosen by the same kind of stored time.

    Not part of the reported finding — found while applying the rule to every
    ordering decision in this file. `find_latest_submitted_job` compared a
    parsed value against `utc_now_dt()` without checking it carried an offset,
    so a naive stored time raised a bare `TypeError` from inside recovery
    instead of a stated refusal.
    """

    def sent_job(self):
        job = self.new_job()
        self.event(job, {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        return self.event(job, {"event": "SEND_STATE", "tabId": 7, "leaseToken": "tok",
                                "state": "SENT"})

    def test_a_naive_submitted_time_is_refused_not_crashed(self):
        job = self.sent_job()
        self.damage(job, "sentAt", "2026-01-01T00:00:00")
        self.damage(job, "updatedAt", "2026-01-01T00:00:00")
        self.damage(job, "createdAt", "2026-01-01T00:00:00")

        state, found, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE,
                         "unprovable time is UNKNOWN, so no source is named")
        self.assertIsNone(found)
        self.assertIn("sentAt", reason)

    def test_a_canonical_submitted_job_is_still_found(self):
        job = self.sent_job()
        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], job["jobId"])

    def test_the_helper_reports_no_time_without_calling_it_a_reason(self):
        """Absent and unprovable are different answers at the helper level.

        This branch had no test, and a broken edit of mine sat in it unnoticed
        through the whole suite: `return None, ''` had lost its second value.
        `git diff --check` caught it; 154 tests did not.

        A dict passed straight to the helper is not a persisted fixture — it
        never goes near disk — so this says nothing about what the writer
        produces. What the *lookup* does with a submitted job that has no time
        at all is a separate question, answered in review 18: not absence.
        """
        self.assertEqual(self.dm._job_submitted_at({}), (None, ""))
        self.assertEqual(self.dm._job_submitted_at({"sentAt": ""}), (None, ""))

    def test_dropping_one_timestamp_falls_through_to_the_next(self):
        """One field damaged, and the answer comes from the next field down."""
        job = self.sent_job()
        self.damage(job, "sentAt", None)          # exactly the field under test

        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], job["jobId"])


if __name__ == "__main__":
    unittest.main()
