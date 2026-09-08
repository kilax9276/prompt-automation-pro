# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 16: the supersede that was correctly skipped is never applied later.

Refusing to retire a claimed job was right. What was missing is the other half:
the refusal is a postponement, not a cancellation. `supersede_older_jobs_for_tab`
runs once, while the newer job is being created, and at that moment the older
job is protected by its lease — so nothing retires it, and nothing ever comes
back to it. The older delivery therefore sits in the queue behind the newer one
and becomes eligible again the moment the newer one finishes.

Both legitimate ways out of a lease are covered: RELEASE, and expiry followed by
recovery. The scenario is played to the end each time — a delivery that finishes
successfully must not leave its predecessor waiting to be delivered afterwards.
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

from delivery_manager import DeliveryManager

PAGE = "https://chatgpt.com/c/abc"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class DeferredRetirement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- fixtures, all through the product writer -------------------------

    def new_job(self, *, tab=7):
        return self.dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{tab}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)

    def event(self, job, body):
        return self.dm.update_from_client(job["runId"], job["jobId"], body)

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def claim(self, job, *, tab=7, token="tok"):
        return self.event(job, {"event": "CLAIM", "tabId": tab, "leaseToken": token, "url": PAGE})

    def deliver_successfully(self, job, *, tab=7, token="tok"):
        """The whole ordinary success path, not a shortcut to SENT."""
        self.claim(job, tab=tab, token=token)
        for attachment in self.stored(job).get("attachments") or []:
            self.event(job, {"event": "ATTACHMENT_STATE", "tabId": tab, "leaseToken": token,
                             "attachmentId": attachment["attachmentId"], "state": "UPLOADED"})
        self.event(job, {"event": "MESSAGE_STATE", "tabId": tab, "leaseToken": token,
                         "state": "INSERTED"})
        self.dm.request_send(job["runId"], job["jobId"])
        sent = self.event(job, {"event": "SEND_STATE", "tabId": tab, "leaseToken": token,
                                "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")
        return sent

    def expire_lease(self, job):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body["claimExpiresAt"] = iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        path.write_text(json.dumps(body), encoding="utf-8")

    # ---- the defect -------------------------------------------------------

    def test_release_then_a_finished_newer_delivery_does_not_revive_the_old_one(self):
        j1 = self.new_job()
        self.claim(j1)
        j2 = self.new_job()
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED",
                            "a claimed job is still not superseded")

        self.event(j1, {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})

        first = self.dm.poll_for_tab(7, PAGE)
        self.assertEqual(first["jobId"], j2["jobId"])
        self.assertEqual(
            self.stored(j1)["status"], "SUPERSEDED",
            "the postponed retirement must be applied once the lease is gone")

        self.deliver_successfully(j2)

        second = self.dm.poll_for_tab(7, PAGE)
        self.assertIsNone(
            second,
            "the older delivery must not become eligible again after the newer one is sent")

    def test_expiry_and_recovery_then_a_finished_newer_delivery_does_not_revive_the_old_one(self):
        j1 = self.new_job()
        self.claim(j1)
        j2 = self.new_job()
        self.expire_lease(j1)

        first = self.dm.poll_for_tab(7, PAGE)
        self.assertIn("leaseRecoveredAt", self.stored(j1), "recovery runs before the decision")
        self.assertEqual(first["jobId"], j2["jobId"])
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")

        self.deliver_successfully(j2)

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

    def test_retirement_happens_at_the_poll_not_at_the_release(self):
        """The lease ending is not itself the retirement; the next poll is.

        Stated so the mechanism is pinned: nothing retires the older job in the
        RELEASE handler, so a reader is not left thinking the event path does it.
        """
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()
        self.event(j1, {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})

        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.dm.poll_for_tab(7, PAGE)
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")

    # ---- what must not be broken by the fix -------------------------------

    def test_an_active_lease_is_still_never_retired(self):
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))
        stored = self.stored(j1)
        self.assertNotEqual(stored["status"], "SUPERSEDED")
        self.assertEqual(self.dm.classify_lease(stored)[0], self.dm.LEASE_ACTIVE)

    def test_an_invalid_lease_is_still_never_retired(self):
        j1 = self.new_job()
        self.claim(j1)
        path = self.dm.job_path(j1["runId"], j1["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body["claimExpiresAt"] = "2026-01-01T00:00:00"      # one field, no offset
        path.write_text(json.dumps(body), encoding="utf-8")
        self.new_job()

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))
        stored = self.stored(j1)
        self.assertNotEqual(stored["status"], "SUPERSEDED")
        self.assertEqual(self.dm.classify_lease(stored)[0], self.dm.LEASE_INVALID)

    def test_a_single_job_is_never_retired_by_itself(self):
        j1 = self.new_job()
        offered = self.dm.poll_for_tab(7, PAGE)
        self.assertEqual(offered["jobId"], j1["jobId"])
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")

    def test_another_tab_is_not_retired_by_this_tabs_poll(self):
        other = self.new_job(tab=9)
        j1 = self.new_job()
        self.new_job()

        self.dm.poll_for_tab(7, PAGE)
        self.assertNotEqual(self.stored(other)["status"], "SUPERSEDED")
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.assertEqual(self.dm.poll_for_tab(9, PAGE)["jobId"], other["jobId"])


if __name__ == "__main__":
    unittest.main()
