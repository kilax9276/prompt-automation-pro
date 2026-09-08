# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Review 14: single-flight per tab, authorization order, and the chunk lease.

All three findings are the same shape as the ones before them. A job was
retired while its outcome was still owed; a terminal state answered instead of
an authorization check; and an operation that never saved anything was written
as though it renewed a lease. In each case the state that could not be
accounted for was replaced by one that could.

Every persisted job here is produced by `DeliveryManager.create_job`, every
lease by a real `CLAIM`, and the paused state by the real restart path. Only
after such a state exists does a test damage exactly the one field it is about.
The first version of this file assembled `job.json` by hand and claimed the
lease properly — which is precisely the half-measure the fixture invariant was
written against: the lease shape was proven, the job shape was invented.
"""
from __future__ import annotations

import copy
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

from console_server import ConsoleServer, REQUIRED_EXTENSION_VERSION
from delivery_manager import DeliveryError, DeliveryManager, ROLLOUT_BARRIER

PAGE = "https://chatgpt.com/c/abc"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def make_job(manager, *, tab=7, run_id="run1", endpoint_id=None):
    """A delivery job through the product writer, with its real attachment."""
    return manager.create_job(
        run_id,
        {"papSource": {"tabId": tab, "url": PAGE, "chatType": "chatgpt", "endpointId": endpoint_id or f"ep-{tab}", "browserEpoch": "epoch-1", "conversationId": "fixture"},
         "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat"},
        {"steps": []},
        {"steps": {}},
        "message",
        "open",
        8 * 1024 * 1024,
        120,
    )


class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        (self.data / "run1" / "executor").mkdir(parents=True)
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.dm = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_job(self, *, tab=7, run_id="run1", manager=None):
        return make_job(manager or self.dm, tab=tab, run_id=run_id)

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

    def attachment_of(self, job):
        attachments = job.get("attachments") or []
        self.assertTrue(attachments, "create_job always materialises the terminal log")
        return attachments[0]["attachmentId"]


class SingleFlightPerTab(DeliveryFixture):
    """A new Prepare must not retire a delivery that is still in flight.

    The sequence that produced a permanently refused barrier: j1 is claimed, a
    second job for the same tab appears, supersede marks j1 terminal under its
    live lease, RELEASE is then dropped by the terminal early return,
    `recover_expired_leases` skips terminal jobs, and the drain sees a finished
    job holding a lease — a contradiction with no path back.
    """

    def test_a_claimed_job_is_not_superseded(self):
        j1 = self.new_job()
        self.claim(j1)
        j2 = self.new_job()

        self.assertEqual(j2["supersededOlderJobs"], 0)
        stored = self.stored(j1)
        self.assertNotEqual(stored["status"], "SUPERSEDED")
        self.assertEqual(self.dm.classify_lease(stored)[0], self.dm.LEASE_ACTIVE,
                         "the lease must survive: its outcome is not yet known")

    def test_release_still_reaches_the_claimed_job(self):
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()

        self.dm.update_from_client(j1["runId"], j1["jobId"], {
            "event": "RELEASE", "tabId": 7, "leaseToken": "tok"})

        self.assertEqual(self.dm.classify_lease(self.stored(j1))[0], self.dm.LEASE_NONE)

    def test_the_barrier_can_still_close_afterwards(self):
        """The end of the chain: the boundary must not be refused for ever."""
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()
        self.dm.update_from_client(j1["runId"], j1["jobId"], {
            "event": "RELEASE", "tabId": 7, "leaseToken": "tok"})

        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertTrue(status["barrierAllowed"], status["outstanding"])
        self.assertEqual(self.dm.enter_barrier()["mode"], ROLLOUT_BARRIER)

    def test_poll_does_not_hand_out_the_newer_job_while_the_older_is_claimed(self):
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()

        self.assertIsNone(self.dm.poll_for_tab(7, PAGE),
                          "two deliveries must not be in flight in one tab")

    def test_the_newer_job_becomes_available_after_release(self):
        j1 = self.new_job()
        self.claim(j1)
        j2 = self.new_job()
        self.dm.update_from_client(j1["runId"], j1["jobId"], {
            "event": "RELEASE", "tabId": 7, "leaseToken": "tok"})

        offered = self.dm.poll_for_tab(7, PAGE)
        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], j2["jobId"])

    def test_another_tab_is_unaffected(self):
        j1 = self.new_job()
        self.claim(j1)
        other = self.new_job(tab=9)

        offered = self.dm.poll_for_tab(9, PAGE)
        self.assertIsNotNone(offered)
        self.assertEqual(offered["jobId"], other["jobId"])

    def test_an_unleased_older_job_is_still_superseded(self):
        """The ordinary path is unchanged: nothing is owed, so it is retired."""
        j1 = self.new_job()
        j2 = self.new_job()

        self.assertEqual(j2["supersededOlderJobs"], 1)
        self.assertEqual(self.stored(j1)["status"], "SUPERSEDED")
        self.assertEqual(self.dm.poll_for_tab(7, PAGE)["jobId"], j2["jobId"])

    def test_an_expired_lease_is_recovered_before_the_decision(self):
        """Recovery first, then the decision — not a decision over the trace."""
        j1 = self.new_job()
        self.claim(j1)
        self.damage(j1, "claimExpiresAt", iso(datetime.now(timezone.utc) - timedelta(seconds=1)))
        j2 = self.new_job()

        stored = self.stored(j1)
        self.assertIn("leaseRecoveredAt", stored, "the expiry must be recovered, not stepped over")
        self.assertEqual(self.dm.classify_lease(stored)[0], self.dm.LEASE_NONE)
        self.assertEqual(j2["supersededOlderJobs"], 1)
        self.assertEqual(stored["status"], "SUPERSEDED")

    def test_an_invalid_lease_is_neither_superseded_nor_cleared(self):
        """Contradictory evidence outlives the arrival of new work."""
        j1 = self.new_job()
        self.claim(j1)
        # Canonical state first, then exactly one field damaged: a stored time
        # with no offset is the case that used to crash comparison code.
        self.damage(j1, "claimExpiresAt", "2026-01-01T00:00:00")
        j2 = self.new_job()

        stored = self.stored(j1)
        self.assertEqual(j2["supersededOlderJobs"], 0)
        self.assertNotEqual(stored["status"], "SUPERSEDED")
        self.assertEqual(self.dm.classify_lease(stored)[0], self.dm.LEASE_INVALID)
        self.assertIsNone(self.dm.poll_for_tab(7, PAGE),
                          "an unexplained lease needs an operator, not more work")

    def test_a_claimed_job_still_blocks_the_barrier(self):
        """Not superseding must not become a way of hiding outstanding work."""
        j1 = self.new_job()
        self.claim(j1)
        self.new_job()

        self.dm.begin_drain()
        status = self.dm.drain_status()
        self.assertFalse(status["barrierAllowed"])
        self.assertIn("claimed", [x["reason"] for x in status["outstanding"]])


class AuthorizationBeforeTerminal(DeliveryFixture):
    """A terminal job is a reason to do nothing, not a reason to skip the check."""

    def sent_job(self, *, tab=7):
        """A genuinely finished delivery, reached the way the product reaches it."""
        job = self.new_job(tab=tab)
        self.claim(job, tab=tab)
        sent = self.dm.update_from_client(job["runId"], job["jobId"], {
            "event": "SEND_STATE", "tabId": tab, "leaseToken": "tok", "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")
        return sent

    def paused_job(self):
        """Paused by the real restart path, not by writing a status.

        A second manager over the same data directory is what a restarted
        console is: a new dispatch epoch meeting jobs of the previous one.
        """
        job = self.new_job()
        restarted = DeliveryManager(self.root, self.data, lambda run_id: "terminal log\n", "epoch-2")
        changed = restarted.pause_unfinished_jobs_after_restart()
        self.assertEqual([x["jobId"] for x in changed], [job["jobId"]])
        self.assertEqual(restarted.get_job(job["runId"], job["jobId"])["status"],
                         "PAUSED_AFTER_RESTART")
        return job, restarted

    def test_a_foreign_tab_cannot_no_op_on_a_terminal_job(self):
        job = self.sent_job()
        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client(job["runId"], job["jobId"], {
                "event": "HEARTBEAT", "tabId": 8, "leaseToken": "tok"})
        self.assertIn("wrong tabId", str(cm.exception))

    def test_a_foreign_tab_cannot_no_op_on_a_paused_job(self):
        job, restarted = self.paused_job()
        with self.assertRaises(DeliveryError) as cm:
            restarted.update_from_client(job["runId"], job["jobId"], {
                "event": "HEARTBEAT", "tabId": 8, "leaseToken": "tok"})
        self.assertIn("wrong tabId", str(cm.exception))

    def test_the_owning_tab_still_gets_the_idempotent_return(self):
        job = self.sent_job()
        again = self.dm.update_from_client(job["runId"], job["jobId"], {
            "event": "RELEASE", "tabId": 7, "leaseToken": "tok"})
        self.assertEqual(again["status"], "SENT")


class AuthorizationBeforeTerminalOverHttp(unittest.TestCase):
    """The same refusal on the route the browser actually calls.

    The endpoint identity is validated by the barrier and the tab is taken from
    it, so this is the whole path an extension can reach: a real endpoint of
    tab 8 naming a finished delivery addressed to tab 7.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data/run1/executor", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data",
                                     self.root / "runtime" / "token.txt")
        # The console injects the executor's log builder into the manager; the
        # test injects a fixed one. Same writer, same persisted shape — only
        # the text of the terminal log differs, and no test here reads it.
        self.writer = DeliveryManager(self.root, self.root / "data",
                                      lambda run_id: "terminal log\n",
                                      self.console.delivery.dispatch_epoch)
        self.own("e1")
        self.observe("ep-1", tab=7)
        self.observe("ep-2", tab=8)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def poll(self, query):
        import asyncio
        req = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                             "rel_url": type("U", (), {"query": query})()})()
        return asyncio.run(self.console.api_delivery_poll(req))

    def own(self, epoch):
        self.poll({"pollKind": "CONTROL_AGENT", "browserEpoch": epoch,
                   "extensionVersion": REQUIRED_EXTENSION_VERSION})

    def observe(self, endpoint_id, *, tab, epoch="e1"):
        self.poll({"pollKind": "ENDPOINT", "browserEpoch": epoch, "endpointId": endpoint_id,
                   "tabId": str(tab), "page": PAGE,
                   "chatType": "chatgpt", "conversationId": "abc",
                   "extensionVersion": REQUIRED_EXTENSION_VERSION})

    def sent_job_for_tab_7(self):
        job = make_job(self.writer, tab=7, endpoint_id="ep-1")
        self.writer.update_from_client(job["runId"], job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE})
        sent = self.writer.update_from_client(job["runId"], job["jobId"], {
            "event": "SEND_STATE", "tabId": 7, "leaseToken": "tok", "state": "SENT"})
        self.assertEqual(sent["status"], "SENT")
        return sent

    def event(self, endpoint_id, job, body):
        import asyncio
        console = self.console

        class R:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": job["runId"], "job_id": job["jobId"]}
            rel_url = type("U", (), {"query": {
                "extensionVersion": REQUIRED_EXTENSION_VERSION,
                "browserEpoch": "e1", "endpointId": endpoint_id}})()

            async def json(self):
                return body

        return asyncio.run(console.api_delivery_event(R()))

    def test_foreign_endpoint_is_refused_on_a_terminal_job(self):
        job = self.sent_job_for_tab_7()
        response = self.event("ep-2", job, {"event": "HEARTBEAT", "leaseToken": "tok"})
        self.assertEqual(response.status, 409)
        self.assertIn("wrong tabId", json.loads(response.body)["error"])

    def test_the_owning_endpoint_is_answered(self):
        job = self.sent_job_for_tab_7()
        response = self.event("ep-1", job, {"event": "HEARTBEAT", "leaseToken": "tok"})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["job"]["status"], "SENT")


class ChunkLeaseContract(DeliveryFixture):
    """Reading bytes proves a lease; it does not renew one.

    The contract chosen for this block: HEARTBEAT and delivery events are the
    only persisted renewal path. `attachment_chunk` used the mutating helper and
    never saved the job, so it read as a renewal and kept nothing — the kind of
    difference no black-box assertion can see, which is why it survived thirteen
    rounds. The split makes it structural.
    """

    def claimed_job(self):
        job = self.new_job()
        self.claim(job)
        return job

    def chunk(self, job, **kwargs):
        return self.dm.attachment_chunk(job["runId"], job["jobId"], self.attachment_of(job),
                                        kwargs.pop("offset", 0), kwargs.pop("limit", 1024),
                                        **kwargs)

    def test_chunk_returns_bytes_to_the_holder_of_the_lease(self):
        job = self.claimed_job()
        out = self.chunk(job, tab_id=7, lease_token="tok")
        self.assertEqual(out["bytes"], len("terminal log\n"))
        self.assertTrue(out["eof"])

    def test_chunk_does_not_renew_the_persisted_lease(self):
        job = self.claimed_job()
        before = self.stored(job)["claimExpiresAt"]
        self.chunk(job, tab_id=7, lease_token="tok")
        self.assertEqual(self.stored(job)["claimExpiresAt"], before,
                         "the chosen contract: chunk validates, it does not extend")

    def test_the_validation_helper_leaves_the_job_untouched(self):
        job = self.claimed_job()
        loaded = self.stored(job)
        snapshot = copy.deepcopy(loaded)
        self.dm._require_live_lease(loaded, "tok")
        self.assertEqual(loaded, snapshot,
                         "a validation-only check must not write a renewal nobody saves")

    def test_the_renewal_helper_is_the_one_that_writes(self):
        job = self.claimed_job()
        loaded = self.stored(job)
        before = loaded["claimExpiresAt"]
        self.dm._touch_lease(loaded, "tok")
        self.assertNotEqual(loaded["claimExpiresAt"], before)

    def test_chunk_does_not_call_the_mutating_helper(self):
        """Structural, because the mutation was invisible from outside."""
        src = (CONSOLE / "delivery_manager.py").read_text("utf-8")
        body = src.split("    def attachment_chunk(", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("_require_live_lease", body)
        self.assertNotIn("_touch_lease(", body,
                         "chunk never saves the job, so it cannot renew anything")

    def test_heartbeat_is_the_persisted_renewal_path(self):
        job = self.claimed_job()
        before = self.stored(job)["claimExpiresAt"]
        self.dm.update_from_client(job["runId"], job["jobId"], {
            "event": "HEARTBEAT", "tabId": 7, "leaseToken": "tok"})
        self.assertNotEqual(self.stored(job)["claimExpiresAt"], before)

    def test_chunk_refuses_without_a_live_lease_of_its_own(self):
        job = self.claimed_job()
        for token in ("", "other"):
            with self.subTest(token=token):
                with self.assertRaises(DeliveryError) as cm:
                    self.chunk(job, tab_id=7, lease_token=token)
                self.assertIn("token mismatch", str(cm.exception))

    def test_chunk_refuses_on_an_expired_lease(self):
        job = self.claimed_job()
        self.damage(job, "claimExpiresAt", iso(datetime.now(timezone.utc) - timedelta(seconds=1)))
        with self.assertRaises(DeliveryError) as cm:
            self.chunk(job, tab_id=7, lease_token="tok")
        self.assertIn("expired", str(cm.exception))

    def test_chunk_refuses_a_foreign_tab(self):
        job = self.claimed_job()
        with self.assertRaises(DeliveryError) as cm:
            self.chunk(job, tab_id=8, lease_token="tok")
        self.assertIn("wrong tabId", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
