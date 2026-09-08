# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 20: which tab a persisted job belongs to is also a proof.

Time and readability are guarded now. The target was not: it was read through a
shrug — a non-object became `{}`, a missing `tabId` became `-1`, and that `-1`
was then compared with the tab being asked about. A delivery whose address
cannot be established was therefore announced to be somebody else's, and the
older delivery behind it was named the proven latest. The same shrug turned an
unusable `tabId` into a bare `ValueError`, which escapes the three-valued answer
altogether.

A proven different tab is a fact and stays a skip. Everything else about the
target is UNKNOWN, and UNKNOWN blocks the conclusion.
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
OTHER_PAGE = "https://chatgpt.com/c/zzz"


class TargetProofFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_job(self, *, tab=7, page=PAGE):
        return self.dm.create_job(
            "run1",
            {"papSource": {"tabId": tab, "url": page, "chatType": "chatgpt", "endpointId": f"ep-{tab}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": page, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)

    def sent_job(self, *, tab=7, page=PAGE, token="tok"):
        job = self.new_job(tab=tab, page=page)
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": tab, "leaseToken": token, "url": page})
        sent = self.dm.update_from_client("run1", job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": token, "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")
        return sent

    def stored(self, job):
        return self.dm.get_job(job["runId"], job["jobId"])

    def damage_target(self, job, value):
        """Replace the whole target, or one of its fields, and nothing else."""
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        if value is None:
            body.pop("target", None)
        else:
            body["target"] = value
        path.write_text(json.dumps(body), encoding="utf-8")

    def damage_target_field(self, job, field, value):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        if value is None:
            body["target"].pop(field, None)
        else:
            body["target"][field] = value
        path.write_text(json.dumps(body), encoding="utf-8")


class AnUnprovableTargetBlocksTheConclusion(TargetProofFixture):
    def assert_unprovable(self, older, fragment):
        state, job, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(job)
        self.assertIn(fragment, reason)
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=older["runId"], source_job_id=older["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_an_unusable_tab_id_is_unprovable_not_an_exception(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage_target_field(j2, "tabId", "bad")     # exactly one field
        self.assert_unprovable(j1, "tabId")

    def test_a_missing_target_is_unprovable_not_another_tab(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage_target(j2, None)
        self.assert_unprovable(j1, "target")

    def test_a_target_that_is_not_an_object_is_unprovable(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage_target(j2, "not-an-object")
        self.assert_unprovable(j1, "target")

    def test_a_missing_tab_id_is_unprovable(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage_target_field(j2, "tabId", None)
        self.assert_unprovable(j1, "tabId")

    def test_a_url_of_the_wrong_type_is_unprovable(self):
        """A number is not a page, and coercing it to text invents one."""
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        self.damage_target_field(j2, "url", 7)
        self.assert_unprovable(j1, "url")

    def test_the_named_source_with_an_unprovable_target_is_refused(self):
        """The explicit path takes the same decision, so it needs the same rule."""
        j1 = self.sent_job()
        self.damage_target_field(j1, "tabId", "bad")
        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_the_lookup_recovers_once_the_target_is_repaired(self):
        j1 = self.sent_job()
        j2 = self.sent_job(token="tok2")
        original = self.stored(j2)["target"]["tabId"]
        self.damage_target_field(j2, "tabId", "bad")
        self.assertEqual(self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)[0],
                         self.dm.SUBMITTED_UNPROVABLE)

        self.damage_target_field(j2, "tabId", original)

        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], j2["jobId"])
        self.assertNotEqual(found["jobId"], j1["jobId"])


class AProvenDifferentTargetIsStillASkip(TargetProofFixture):
    """The fact, as opposed to the gap: known to be elsewhere, so not a candidate."""

    def test_another_tab_is_skipped(self):
        j1 = self.sent_job()
        self.sent_job(tab=9, token="tok9")

        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], j1["jobId"])

    def test_another_page_on_the_same_tab_is_skipped(self):
        j1 = self.sent_job()
        self.sent_job(page=OTHER_PAGE, token="tok3")

        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], j1["jobId"])

    def test_a_canonical_empty_url_still_matches(self):
        """The writer's own contract for a target with no page recorded.

        Written by the writer, not by damaging one: `create_job` with no source
        url and no page stores the empty string itself. The earlier version of
        this test asserted a writer contract while producing the state by hand,
        which is the one thing the fixture invariant asks not to do.
        """
        j1 = self.sent_job()
        j2 = self.dm.create_job(
            "run1",
            {"papSource": {"tabId": 7, "url": "", "chatType": "chatgpt", "endpointId": f"ep-{7}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": "", "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)
        self.assertEqual(j2["target"]["url"], "", "the writer stores the empty string")
        self.dm.update_from_client("run1", j2["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok2", "url": PAGE})
        self.dm.update_from_client("run1", j2["jobId"], {
            "event": "SEND_STATE", "tabId": 7, "leaseToken": "tok2", "state": "SENT"})

        state, found, _reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)

        self.assertEqual(state, self.dm.SUBMITTED_FOUND)
        self.assertEqual(found["jobId"], j2["jobId"])
        self.assertNotEqual(found["jobId"], j1["jobId"])


class AMissingUrlIsNotAWildcard(TargetProofFixture):
    """The writer always stores a url, so an absent one is damage.

    An empty stored url and an absent key were answered the same way. They are
    not the same: the empty string is the writer's own record of a target with
    no page, while a missing key is a target whose page cannot be established.
    Treating the second as the first turned a delivery addressed to one page
    into a proven match for another — the same substitution of a default for
    an unknown, one field further in.
    """

    def test_a_delivery_for_another_page_does_not_become_this_page(self):
        j1 = self.sent_job()                                  # page A
        j2 = self.sent_job(page=OTHER_PAGE, token="tok2")     # page B
        self.damage_target_field(j2, "url", None)             # exactly one field

        verdict, why = self.dm.classify_target(self.stored(j2), tab_id=7, page_url=PAGE)
        self.assertEqual(verdict, self.dm.TARGET_UNPROVABLE)
        self.assertIn("url", why)

        state, found, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIsNone(found)
        self.assertIn("url", reason)

        with self.assertRaises(DeliveryError) as cm:
            self.dm.resolve_recovery_source(
                tab_id=7, page_url=PAGE,
                source_run_id=j1["runId"], source_job_id=j1["jobId"])
        self.assertIn("RECOVERY_SOURCE_UNPROVABLE", str(cm.exception))

    def test_a_null_url_is_unprovable_too(self):
        j1 = self.sent_job()
        j2 = self.sent_job(page=OTHER_PAGE, token="tok2")
        self.damage_target_field(j2, "url", "__null__")
        path = self.dm.job_path(j2["runId"], j2["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body["target"]["url"] = None
        path.write_text(json.dumps(body), encoding="utf-8")

        state, _found, reason = self.dm.find_latest_submitted_job(tab_id=7, page_url=PAGE)
        self.assertEqual(state, self.dm.SUBMITTED_UNPROVABLE)
        self.assertIn("url", reason)
        del j1

    def test_a_queued_delivery_for_another_page_is_not_offered_here(self):
        """The same helper, so the same hole reached the ordinary hand-out."""
        j1 = self.new_job(page=OTHER_PAGE)
        self.damage_target_field(j1, "url", None)

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

    def test_the_page_decision_recovers_once_the_url_is_restored(self):
        j1 = self.new_job(page=OTHER_PAGE)
        self.damage_target_field(j1, "url", None)
        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

        self.damage_target_field(j1, "url", OTHER_PAGE)

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE),
                          "restored: proven to be another page, so still not offered here")
        offered = self.dm.poll_for_tab(7, OTHER_PAGE)
        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], j1["jobId"])


class TheDeliveryPlaneTakesTheSameDecision(TargetProofFixture):
    """The same helper answers where a delivery is handed out and retired.

    Not part of the reported finding, and included because the answer must not
    depend on which caller asks: an unprovable target left a queued job out of
    the Prepare order, and a job left out of the order is one that cannot
    protect anything from being retired around it.
    """

    def queued_pair_with_a_damaged_newer_target(self):
        """Two open jobs, the newer one with an address nobody can read.

        The lease on the older job is what keeps the retirement inside
        `create_job` from running, so the decision falls to the poll — which is
        where the deferred retirement lives and where the damaged target has to
        be noticed.
        """
        j1 = self.new_job()
        self.dm.update_from_client("run1", j1["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        j2 = self.new_job()
        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.damage_target_field(j2, "tabId", "bad")
        self.dm.update_from_client("run1", j1["jobId"], {
            "event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        return j1, j2

    def test_an_unprovable_target_stops_the_poll(self):
        self.queued_pair_with_a_damaged_newer_target()

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

    def test_an_unprovable_target_retires_nothing(self):
        j1, j2 = self.queued_pair_with_a_damaged_newer_target()

        self.dm.poll_for_tab(7, PAGE)

        self.assertNotEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.assertNotEqual(self.stored(j2)["status"], "SUPERSEDED")

    def test_the_tab_resumes_once_the_target_is_repaired(self):
        j1, j2 = self.queued_pair_with_a_damaged_newer_target()
        self.assertIsNone(self.dm.poll_for_tab(7, PAGE))

        self.damage_target_field(j2, "tabId", 7)

        offered = self.dm.poll_for_tab(7, PAGE)
        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], j2["jobId"])
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")


class BrowserFacingPathsUseTheSameProof(TargetProofFixture):
    """Authorization of an event or a byte read is the same question.

    `update_from_client` and `attachment_chunk` kept their own reading of the
    stored target, and `int()` answers where the classifier refuses: `int(True)`
    is 1, so a corrupted tabId became a perfectly good tab number and the tab it
    named could act on the job. The other shape of the same remainder is
    `int('bad')`, which leaves through an exception rather than a refusal — past
    the three-valued answer, and in the chunk route past the only exception the
    handler catches.
    """

    def corrupted_tab_job(self, value, *, terminal=False):
        job = self.new_job()
        if terminal:
            self.dm.update_from_client("run1", job["jobId"], {
                "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
            job = self.dm.update_from_client("run1", job["jobId"], {
                "event": "SEND_STATE", "tabId": 7, "leaseToken": "tok", "state": "SENT"})
            self.assertEqual(job["status"], "SENT")
        self.damage_target_field(job, "tabId", value)   # exactly one field
        return job

    def test_a_boolean_tab_id_does_not_become_tab_one(self):
        job = self.corrupted_tab_job(True)

        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"], {
                "event": "CLAIM", "tabId": 1, "leaseToken": "tok", "url": PAGE})

        self.assertIn("wrong tabId", str(cm.exception))
        self.assertEqual(self.dm.classify_lease(self.stored(job))[0], self.dm.LEASE_NONE,
                         "a refused claim leaves no lease behind")

    def test_a_terminal_job_with_a_corrupted_target_is_not_a_no_op(self):
        job = self.corrupted_tab_job(True, terminal=True)

        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"], {
                "event": "HEARTBEAT", "tabId": 1, "leaseToken": "tok"})

        self.assertIn("wrong tabId", str(cm.exception))

    def test_an_unusable_tab_id_is_a_refusal_not_an_exception(self):
        job = self.corrupted_tab_job("bad")

        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"], {
                "event": "HEARTBEAT", "tabId": 7, "leaseToken": "tok"})

        self.assertIn("wrong tabId", str(cm.exception))

    def test_chunk_refuses_a_corrupted_target_before_reading_bytes(self):
        job = self.new_job()
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        attachment = self.stored(job)["attachments"][0]["attachmentId"]
        self.damage_target_field(job, "tabId", True)

        for tab in (1, 7):
            with self.subTest(tab=tab):
                with self.assertRaises(DeliveryError) as cm:
                    self.dm.attachment_chunk("run1", job["jobId"], attachment, 0, 1024,
                                             tab_id=tab, lease_token="tok")
                self.assertIn("wrong tabId", str(cm.exception))

    def test_chunk_with_an_unusable_tab_id_refuses_rather_than_raising(self):
        job = self.new_job()
        self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        attachment = self.stored(job)["attachments"][0]["attachmentId"]
        self.damage_target_field(job, "tabId", "bad")

        with self.assertRaises(DeliveryError) as cm:
            self.dm.attachment_chunk("run1", job["jobId"], attachment, 0, 1024,
                                     tab_id=7, lease_token="tok")
        self.assertIn("wrong tabId", str(cm.exception))

    def test_the_canonical_tab_still_works_everywhere(self):
        """Nothing above may cost the ordinary path."""
        job = self.new_job()
        claimed = self.dm.update_from_client("run1", job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        self.assertEqual(self.dm.classify_lease(claimed)[0], self.dm.LEASE_ACTIVE)
        attachment = self.stored(job)["attachments"][0]["attachmentId"]
        out = self.dm.attachment_chunk("run1", job["jobId"], attachment, 0, 1024,
                                       tab_id=7, lease_token="tok")
        self.assertGreater(out["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
