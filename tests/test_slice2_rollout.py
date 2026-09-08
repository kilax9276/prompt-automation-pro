# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""DRAIN, the unsafe latch, and BARRIER.

The invariant worth the most here is negative: an empty queue is not evidence
that every outcome is known. A lease that existed and expired during the drain
leaves a delivery nobody can report on, and clearing its trace afterwards must
not turn that into permission to close the boundary.
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

from delivery_manager import DeliveryError, DeliveryManager, ROLLOUT_BARRIER, ROLLOUT_DRAIN


PAGE = "https://chatgpt.com/c/abc"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


class DrainBarrier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_job(self, *, lease_seconds=None, status="READY", manager=None):
        """A delivery job from the product writer, then the state under test.

        The skeleton used to be assembled here by hand while only the lease came
        from the real writer. That half-measure is what the fixture invariant
        was written against, and it showed: the invented shape carried no
        `createdAt`, so the moment Prepare order became a validated decision the
        fixture stopped describing anything the product can produce.
        """
        dm = manager or self.dm
        job = dm.create_job(
            "run1",
            {"papSource": {"tabId": 7, "url": PAGE, "chatType": "chatgpt", "endpointId": f"ep-{7}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
             "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
            {"steps": []}, {"steps": {}}, "message", "open", 8 * 1024 * 1024, 120)
        if status == "SENT":
            dm.update_from_client("run1", job["jobId"], {
                "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
            job = dm.update_from_client("run1", job["jobId"], {
                "event": "SEND_STATE", "tabId": 7, "leaseToken": "tok", "state": "SENT"})
        if lease_seconds is not None:
            job = dm.update_from_client(
                "run1", job["jobId"],
                {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
            if lease_seconds != 60:
                # One field of a canonical state, the one under test.
                job["claimExpiresAt"] = iso(datetime.now(timezone.utc)
                                            + timedelta(seconds=lease_seconds))
                dm.job_path("run1", job["jobId"]).write_text(json.dumps(job), encoding="utf-8")
        return job

    def test_clean_drain_allows_barrier(self):
        self.write_job(status="SENT")
        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertTrue(status["barrierAllowed"])
        self.assertEqual(self.dm.enter_barrier()["mode"], ROLLOUT_BARRIER)

    def test_active_claim_blocks_barrier(self):
        self.write_job(lease_seconds=60)
        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertFalse(status["barrierAllowed"])
        self.assertEqual(status["outstanding"][0]["reason"], "claimed")
        with self.assertRaises(DeliveryError) as cm:
            self.dm.enter_barrier()
        self.assertIn("BARRIER_REFUSED", str(cm.exception))

    def expire_lease_now(self, job):
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body["claimExpiresAt"] = iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_lease_expiring_during_drain_latches_unsafe_and_blocks_barrier(self):
        """The dangerous sequence, end to end, with no help from the caller.

        A live lease -> the drain begins -> the lease expires during the pass ->
        enter_barrier is called directly. Nothing ran recovery first, and the
        expired lease already stopped counting as active, so a barrier that
        trusted the queue would close over an outcome nobody recorded.
        """
        job = self.write_job(lease_seconds=60)    # alive when the drain starts
        self.dm.begin_drain()
        self.assertFalse(self.dm.rollout_state()["unsafe"])

        self.expire_lease_now(job)                # expires mid-pass

        with self.assertRaises(DeliveryError) as cm:
            self.dm.enter_barrier()               # no manual recovery beforehand
        self.assertIn("BARRIER_REFUSED", str(cm.exception))

        state = self.dm.rollout_state()
        self.assertTrue(state["unsafe"])
        self.assertIn("lease expired during drain", state["unsafeReasons"][0])

        status = self.dm.drain_status()
        self.assertEqual(status["outstanding"], [], "the trace is gone, as it would be in practice")
        self.assertFalse(status["barrierAllowed"], "an empty queue is not proof of a known outcome")

    def test_latch_is_monotonic_within_a_pass(self):
        job = self.write_job(lease_seconds=60)
        self.dm.begin_drain()
        self.expire_lease_now(job)
        self.dm.recover_expired_leases()
        self.assertTrue(self.dm.rollout_state()["unsafe"])

        # Every automatic route that could look like "it is fine now".
        self.dm.recover_expired_leases()
        self.dm.poll_for_tab(7, "https://chatgpt.com/c/abc")
        reloaded = DeliveryManager(self.root, self.data, lambda run_id: "", "epoch-1")  # restart
        self.assertTrue(reloaded.rollout_state()["unsafe"],
                        "a restart must not clear what was lost")
        self.assertFalse(reloaded.drain_status()["barrierAllowed"])

    def test_only_a_new_drain_pass_clears_the_latch(self):
        job = self.write_job(lease_seconds=60)
        self.dm.begin_drain()
        first = self.dm.rollout_state()["drainId"]
        self.expire_lease_now(job)
        self.dm.recover_expired_leases()
        self.assertTrue(self.dm.rollout_state()["unsafe"])

        second = self.dm.begin_drain()
        self.assertNotEqual(second["drainId"], first, "a new pass has its own identity")
        self.assertFalse(second["unsafe"])

    def test_drain_hands_out_no_new_work(self):
        self.write_job(status="READY")
        self.assertIsNotNone(self.dm.poll_for_tab(7, ""),
                             "before the drain the job is handed out normally")
        self.dm.begin_drain()
        self.assertIsNone(self.dm.poll_for_tab(7, ""),
                          "during the drain no new work is handed out")


    def test_claim_is_refused_outside_open(self):
        """A new claim is new work, and the event route is not a way around that."""
        job = self.write_job(status="READY")
        path = self.dm.job_path(job["runId"], job["jobId"])
        before = path.read_bytes()
        self.dm.begin_drain()
        with self.assertRaises(DeliveryError) as cm:
            # An otherwise valid claim, so the refusal proves the rollout mode
            # and not some unrelated complaint answering first.
            self.dm.update_from_client("run1", job["jobId"],
                                       {"event": "CLAIM", "leaseToken": "new", "tabId": 7})
        self.assertIn("DELIVERY_CLAIM_REFUSED", str(cm.exception))
        self.assertEqual(path.read_bytes(), before, "a refused claim must not touch the job")

    def test_incomplete_rollout_state_is_unsafe(self):
        """This writer never produces a DRAIN without its own bookkeeping."""
        self.write_job(status="SENT")
        (self.root / "runtime" / "delivery-rollout.json").write_text(
            json.dumps({"mode": "DRAIN"}), encoding="utf-8")
        state = self.dm.rollout_state()
        self.assertTrue(state["unsafe"])
        self.assertFalse(self.dm.drain_status()["barrierAllowed"])
        with self.assertRaises(DeliveryError):
            self.dm.enter_barrier()

    def test_unreadable_job_blocks_the_barrier(self):
        """An unreadable delivery job is an unknown outcome, not an absent one."""
        self.write_job(status="SENT")
        broken = self.data / "run1" / "executor" / "delivery" / "broken"
        broken.mkdir(parents=True)
        (broken / "job.json").write_text("{broken", encoding="utf-8")
        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertTrue(any("unreadable job" in o["reason"] for o in status["outstanding"]))
        self.assertFalse(status["barrierAllowed"])
        with self.assertRaises(DeliveryError):
            self.dm.enter_barrier()

    def test_outstanding_reports_the_real_job_id(self):
        job = self.write_job(lease_seconds=60)
        self.dm.begin_drain()
        outstanding = self.dm.drain_status()["outstanding"]
        self.assertEqual(outstanding[0]["jobId"], job["jobId"])


    def test_restart_between_drain_start_and_expiry_still_latches(self):
        """The console may restart mid-drain; the outstanding work does not go away.

        recover_expired_leases skips jobs of a previous dispatchEpoch, so after a
        restart the lease being waited on stopped being seen: alive it blocked
        the barrier, and the moment it expired it vanished from the check and the
        barrier opened over an outcome nobody recorded.
        """
        job = self.write_job(lease_seconds=60)
        self.dm.begin_drain()

        restarted = DeliveryManager(self.root, self.data, lambda run_id: "", "epoch-2")
        self.expire_lease_now(job)

        with self.assertRaises(DeliveryError) as cm:
            restarted.enter_barrier()
        self.assertIn("BARRIER_REFUSED", str(cm.exception))
        state = restarted.rollout_state()
        self.assertTrue(state["unsafe"])
        self.assertTrue(any("lease expired during drain" in r for r in state["unsafeReasons"]))

    def test_contradictory_lease_traces_are_unknown_not_absent(self):
        """A half-written lease is an unknown outcome, not an empty queue."""
        cases = {
            "token without expiry": {"claimLeaseToken": "tok"},
            "expiry without token": {"claimExpiresAt": iso(datetime.now(timezone.utc))},
            "claimedBy alone": {"claimedBy": {"tabId": 7, "url": "u",
                                              "at": iso(datetime.now(timezone.utc)),
                                              "leaseToken": "tok"}},
            "heartbeat alone": {"claimHeartbeatAt": iso(datetime.now(timezone.utc))},

        }
        for label, over in cases.items():
            with self.subTest(case=label):
                shutil.rmtree(self.data, ignore_errors=True)
                self.data.mkdir(parents=True)
                (self.root / "runtime" / "delivery-rollout.json").unlink(missing_ok=True)
                (self.data / "run1" / "executor").mkdir(parents=True)
                dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n",
                                     "epoch-1")
                created = self.write_job(status="READY", manager=dm)
                path = dm.job_path(created["runId"], created["jobId"])
                job = json.loads(path.read_text("utf-8"))
                job.update({k: v for k, v in over.items() if v is not None})
                path.write_text(json.dumps(job), encoding="utf-8")

                dm.begin_drain()
                status = dm.drain_status()
                self.assertFalse(status["barrierAllowed"], f"{label} must not read as an empty queue")
                with self.assertRaises(DeliveryError):
                    dm.enter_barrier()
                self.assertTrue(dm.rollout_state()["unsafe"])

    def test_lease_classification_tells_the_four_cases_apart(self):
        dm = self.dm
        future = iso(datetime.now(timezone.utc) + timedelta(seconds=60))
        past = iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        self.assertEqual(dm.classify_lease({})[0], "NO_LEASE")
        full = {"claimHeartbeatAt": iso(datetime.now(timezone.utc)),
                "claimedBy": {"tabId": 7, "url": "u", "at": iso(datetime.now(timezone.utc)),
                              "leaseToken": "t"}}
        self.assertEqual(dm.classify_lease({"claimLeaseToken": "t", "claimExpiresAt": future, **full})[0], "ACTIVE")
        self.assertEqual(dm.classify_lease({"claimLeaseToken": "t", "claimExpiresAt": past, **full})[0], "EXPIRED")
        self.assertEqual(dm.classify_lease({"claimedBy": full["claimedBy"]})[0], "INVALID")
        # claimedBy must agree with the token it was recorded under.
        mismatched = dict(full, claimedBy=dict(full["claimedBy"], leaseToken="other"))
        self.assertEqual(
            dm.classify_lease({"claimLeaseToken": "t", "claimExpiresAt": future, **mismatched})[0],
            "INVALID")
        self.assertEqual(
            dm.classify_lease({"claimLeaseToken": "t", "claimExpiresAt": future,
                               **dict(full, claimedBy={"tabId": "7", "url": "u",
                                                       "at": iso(datetime.now(timezone.utc)),
                                                       "leaseToken": "t"})})[0],
            "INVALID")
        self.assertEqual(dm.classify_lease({"claimLeaseToken": "t"})[0], "INVALID")
        self.assertEqual(dm.classify_lease({"claimExpiresAt": future})[0], "INVALID")
        self.assertEqual(dm.classify_lease({"claimLeaseToken": "t", "claimExpiresAt": "nope"})[0], "INVALID")


    def test_non_claim_events_cannot_conjure_a_lease(self):
        """Blocking CLAIM alone left every other event as a way in.

        The old token check matched an empty stored token against an empty
        requested one and then wrote a fresh expiry, so unclaimed work kept
        moving during a drain through MESSAGE_STATE, CONSUMED and the rest.
        """
        job = self.write_job(status="READY")
        path = self.dm.job_path(job["runId"], job["jobId"])
        before = path.read_bytes()
        self.dm.begin_drain()
        for event in ("MESSAGE_STATE", "CONSUMED", "HEARTBEAT", "RELEASE"):
            with self.subTest(event=event):
                with self.assertRaises(DeliveryError) as cm:
                    self.dm.update_from_client("run1", job["jobId"], {"event": event, "tabId": 7})
                self.assertIn("DELIVERY_NOT_LEASED", str(cm.exception))
                self.assertEqual(path.read_bytes(), before, "the job must not have moved")

    def test_release_cannot_erase_invalid_lease_evidence(self):
        """A direct latch bypass: erase the trace, and the barrier opens over it."""
        job = self.write_job(status="READY")
        path = self.dm.job_path(job["runId"], job["jobId"])
        job = json.loads(path.read_text("utf-8"))
        job["claimLeaseToken"] = "tok"          # token with no expiry: INVALID
        path.write_text(json.dumps(job), encoding="utf-8")

        self.dm.begin_drain()
        self.assertFalse(self.dm.drain_status()["barrierAllowed"])
        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"],
                                       {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        self.assertIn("DELIVERY_LEASE_INVALID", str(cm.exception))
        state = self.dm.rollout_state()
        self.assertTrue(state["unsafe"])
        self.assertFalse(self.dm.drain_status()["barrierAllowed"])
        with self.assertRaises(DeliveryError):
            self.dm.enter_barrier()

    def test_claim_does_not_overwrite_invalid_evidence(self):
        job = self.write_job(status="READY")
        path = self.dm.job_path(job["runId"], job["jobId"])
        job = json.loads(path.read_text("utf-8"))
        job["claimLeaseToken"] = "tok"
        path.write_text(json.dumps(job), encoding="utf-8")
        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"],
                                       {"event": "CLAIM", "tabId": 7, "leaseToken": "fresh"})
        self.assertIn("DELIVERY_LEASE_INVALID", str(cm.exception))

    def test_naive_lease_timestamp_gives_a_lease_verdict_not_a_crash(self):
        job = self.write_job(status="READY")
        path = self.dm.job_path(job["runId"], job["jobId"])
        job = json.loads(path.read_text("utf-8"))
        job = self.dm.update_from_client(
            "run1", job["jobId"], {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": "u"})
        job["claimExpiresAt"] = "2026-09-07T10:00:00"     # exactly one field spoiled
        path.write_text(json.dumps(job), encoding="utf-8")
        self.assertEqual(self.dm.classify_lease(job)[0], "INVALID")
        self.assertFalse(self.dm._lease_is_active(job))
        self.assertIsNone(self.dm.poll_for_tab(7, ""))   # a verdict, not a TypeError

    def test_rollout_state_values_are_validated(self):
        self.write_job(status="SENT")
        cases = {
            "garbage startedAt": {"mode": "DRAIN", "drainId": "d", "startedAt": "garbage",
                                  "unsafe": False, "unsafeReasons": []},
            "naive startedAt": {"mode": "DRAIN", "drainId": "d",
                                "startedAt": "2026-09-07T10:00:00",
                                "unsafe": False, "unsafeReasons": []},
            "flag contradicts reasons": {"mode": "DRAIN", "drainId": "d",
                                         "startedAt": "2026-09-07T10:00:00+00:00",
                                         "unsafe": False,
                                         "unsafeReasons": ["lease expired during drain"]},
            "reasons contradict flag": {"mode": "DRAIN", "drainId": "d",
                                        "startedAt": "2026-09-07T10:00:00+00:00",
                                        "unsafe": True, "unsafeReasons": []},
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                (self.root / "runtime" / "delivery-rollout.json").write_text(
                    json.dumps(body), encoding="utf-8")
                self.assertTrue(self.dm.rollout_state()["unsafe"], label)
                self.assertFalse(self.dm.drain_status()["barrierAllowed"], label)
                with self.assertRaises(DeliveryError):
                    self.dm.enter_barrier()


    def test_attachments_in_flight_block_the_barrier(self):
        """Browser quiet is not only about leases."""
        for state in ("FETCHING", "CHAT_UPLOADING", "CLAUDE_UPLOADING"):
            with self.subTest(state=state):
                shutil.rmtree(self.data, ignore_errors=True)
                self.data.mkdir(parents=True)
                (self.root / "runtime" / "delivery-rollout.json").unlink(missing_ok=True)
                (self.data / "run1" / "executor").mkdir(parents=True)
                dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n",
                                     "epoch-1")
                created = self.write_job(status="READY", manager=dm)
                path = dm.job_path(created["runId"], created["jobId"])
                job = json.loads(path.read_text("utf-8"))
                job["status"] = "UPLOADING"
                job["attachments"][0]["state"] = state    # the field under test
                path.write_text(json.dumps(job), encoding="utf-8")
                dm.begin_drain()
                status = dm.drain_status()
                self.assertFalse(status["barrierAllowed"], state)
                self.assertTrue(any(state in o["reason"] for o in status["outstanding"]))
                with self.assertRaises(DeliveryError):
                    dm.enter_barrier()

    def test_claim_over_an_expired_lease_is_refused(self):
        """Recovery first, then a new claim: the lease term stays a server boundary."""
        job = self.write_job(lease_seconds=-1)
        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client("run1", job["jobId"],
                                       {"event": "CLAIM", "tabId": 7, "leaseToken": "fresh"})
        self.assertIn("DELIVERY_LEASE_EXPIRED", str(cm.exception))
        job = self.dm.get_job("run1", job["jobId"])
        self.assertEqual(job["claimLeaseToken"], "tok", "the expired trace must survive")


    def test_real_claim_lifecycle_is_active_then_released(self):
        """The lifecycle the product actually performs, with no hand-built lease."""
        created = self.write_job(status="READY")
        job = self.dm.get_job("run1", created["jobId"])
        self.assertEqual(self.dm.classify_lease(job)[0], "NO_LEASE")

        job = self.dm.update_from_client(
            "run1", job["jobId"], {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": "u"})
        self.assertIsInstance(job["claimedBy"], dict)
        self.assertEqual(self.dm.classify_lease(job)[0], "ACTIVE")

        job = self.dm.update_from_client(
            "run1", job["jobId"], {"event": "HEARTBEAT", "tabId": 7, "leaseToken": "tok"})
        self.assertEqual(self.dm.classify_lease(job)[0], "ACTIVE")

        job = self.dm.update_from_client(
            "run1", job["jobId"], {"event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        self.assertEqual(self.dm.classify_lease(job)[0], "NO_LEASE")

    def test_stored_open_is_not_a_canonical_state(self):
        """Damaging one word of a valid BARRIER must not reopen the plane."""
        self.write_job(status="SENT")
        self.dm.begin_drain()
        self.dm.enter_barrier()
        path = self.root / "runtime" / "delivery-rollout.json"
        body = json.loads(path.read_text("utf-8"))
        self.assertEqual(body["mode"], "BARRIER")
        body["mode"] = "OPEN"
        path.write_text(json.dumps(body), encoding="utf-8")

        state = self.dm.rollout_state()
        self.assertFalse(state["valid"])
        self.assertTrue(state["unsafe"])
        self.assertIn("OPEN", state["stateError"])

    def test_contradictory_attachment_state_is_not_quiet(self):
        """A finished job cannot still be uploading."""
        created = self.write_job(status="SENT")
        path = self.dm.job_path(created["runId"], created["jobId"])
        job = json.loads(path.read_text("utf-8"))
        job["attachments"][0]["state"] = "FETCHING"       # the field under test
        path.write_text(json.dumps(job), encoding="utf-8")
        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertFalse(status["barrierAllowed"])
        self.assertTrue(any("in flight" in o["reason"] for o in status["outstanding"]))
        with self.assertRaises(DeliveryError):
            self.dm.enter_barrier()

    def test_malformed_attachments_do_not_crash_the_drain(self):
        for label, attachments in {"not a list": "oops", "non-object entry": [7]}.items():
            with self.subTest(case=label):
                shutil.rmtree(self.data, ignore_errors=True)
                self.data.mkdir(parents=True)
                (self.root / "runtime" / "delivery-rollout.json").unlink(missing_ok=True)
                (self.data / "run1" / "executor").mkdir(parents=True)
                dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n",
                                     "epoch-1")
                created = self.write_job(status="READY", manager=dm)
                path = dm.job_path(created["runId"], created["jobId"])
                job = json.loads(path.read_text("utf-8"))
                job["attachments"] = attachments          # the field under test
                path.write_text(json.dumps(job), encoding="utf-8")
                dm.begin_drain()
                status = dm.drain_status()          # a verdict, not an AttributeError
                self.assertFalse(status["barrierAllowed"])


    def test_expiry_corruption_on_a_real_lease_is_invalid(self):
        """One field spoiled on a genuine claim, so the verdict is about expiry.

        Building the whole lease by hand made the classifier answer INVALID for
        the wrong reason — a wrong claimedBy shape — before it ever looked at
        the timestamp these cases are named after.
        """
        for label, value in {"unreadable": "not-a-time",
                             "naive": "2026-09-07T10:00:00"}.items():
            with self.subTest(case=label):
                shutil.rmtree(self.data, ignore_errors=True)
                self.data.mkdir(parents=True)
                (self.root / "runtime" / "delivery-rollout.json").unlink(missing_ok=True)
                (self.data / "run1" / "executor").mkdir(parents=True)
                dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n",
                                     "epoch-1")
                created = self.write_job(status="READY", manager=dm)
                job = dm.update_from_client("run1", created["jobId"],
                                            {"event": "CLAIM", "tabId": 7,
                                             "leaseToken": "tok", "url": "u"})
                self.assertEqual(dm.classify_lease(job)[0], "ACTIVE")
                job["claimExpiresAt"] = value
                kind, detail = dm.classify_lease(job)
                self.assertEqual(kind, "INVALID")
                self.assertIn("claimExpiresAt", detail)

    def test_successful_send_ends_the_lease(self):
        """The ordinary happy path, not a damaged state.

        RELEASE arrives after the job is terminal and is ignored by the early
        return, so a send that worked used to leave an ACTIVE lease behind and
        the drain read that terminal job as quiet.
        """
        job = self.write_job(status="READY")
        self.dm.update_from_client("run1", job["jobId"],
                                   {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": "u"})
        job = self.dm.update_from_client("run1", job["jobId"],
                                         {"event": "SEND_STATE", "tabId": 7,
                                          "leaseToken": "tok", "state": "SENT"})
        self.assertEqual(self.dm.classify_lease(job)[0], "NO_LEASE")

        self.dm.begin_drain()
        self.assertTrue(self.dm.drain_status()["barrierAllowed"])

    def test_terminal_job_holding_a_lease_blocks_the_barrier(self):
        job = self.write_job(status="READY")
        self.dm.update_from_client("run1", job["jobId"],
                                   {"event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": "u"})
        path = self.dm.job_path(job["runId"], job["jobId"])
        body = json.loads(path.read_text("utf-8"))
        body["status"] = "SUPERSEDED"                     # terminated under a live lease
        path.write_text(json.dumps(body), encoding="utf-8")

        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertFalse(status["barrierAllowed"])
        self.assertTrue(any("terminal job still holding" in o["reason"] for o in status["outstanding"]))

    def test_barrier_downgraded_to_drain_is_not_a_valid_drain(self):
        self.write_job(status="SENT")
        self.dm.begin_drain()
        self.dm.enter_barrier()
        path = self.root / "runtime" / "delivery-rollout.json"
        body = json.loads(path.read_text("utf-8"))
        body["mode"] = "DRAIN"                            # one word changed
        path.write_text(json.dumps(body), encoding="utf-8")
        state = self.dm.rollout_state()
        self.assertFalse(state["valid"])
        self.assertIn("enteredAt", state["stateError"])

    def test_unreadable_rollout_state_is_treated_as_unsafe(self):
        self.dm.begin_drain()
        (self.root / "runtime" / "delivery-rollout.json").write_text("{broken", encoding="utf-8")
        state = self.dm.rollout_state()
        self.assertEqual(state["mode"], ROLLOUT_DRAIN)
        self.assertTrue(state["unsafe"], "state that cannot be read is not state that is safe")
        self.assertFalse(self.dm.drain_status()["barrierAllowed"])
