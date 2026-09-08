# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Slice 4: delivery authorization, endpoint policy and logical-delivery identity."""
from __future__ import annotations

import asyncio
import base64
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
sys.path.insert(0, str(ROOT / "tests"))

from console_server import ConsoleServer
from delivery_manager import DeliveryError, DeliveryManager
from endpoint_registry import EndpointRegistry
from run_profile_context import ProfileAuthorizationError
from test_slice1 import ReceiverHarness
from test_slice2_select_endpoint import profile_body

PAGE = "https://chatgpt.com/c/abc"


def intake_payload():
    return {
        "page": PAGE,
        "chatType": "chatgpt",
        "chatConversationId": "abc",
        "generatedAt": "slice4",
        "turnId": None,
        "messages": [{"role": "assistant", "text": "slice4"}],
        "commands": [],
        "fileTransfer": {"expectedFiles": 0, "requiredPaths": []},
    }


class AuthorizationHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        self.data.mkdir(parents=True)
        (self.root / "runtime").mkdir()
        self.token = self.root / "runtime" / "token.txt"
        self.token.write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.data, self.token)
        self.console.profiles.save_profile(profile_body(), actor="test", create=True)
        self.console.bindings.create({
            "bindingId": "b1", "name": "B1", "chatType": "chatgpt",
            "conversationId": "abc", "profileId": "p1", "role": "source",
            "enabled": True,
        }, "test")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create_run(self, with_session=True):
        session = self.console.sessions.ensure("p1", ["b1"], restart_generation=0) if with_session else None
        h = ReceiverHarness(self.root)
        try:
            status, body = h.post_json("/api/chat-result", intake_payload())
            self.assertEqual(status, 200)
        finally:
            h.close()
        run_id = body["runId"]
        ctx = self.console.profile_context.ensure_run_context(run_id)
        self.assertEqual(ctx["resolutionStatus"], "RESOLVED")
        return run_id, ctx, session

    def observe(self, endpoint_id="ep-1", tab=7):
        return self.console.endpoints.observe(
            tab, PAGE, endpoint_id=endpoint_id, title=endpoint_id,
            browser_epoch="epoch-1", chat_type="chatgpt",
            conversation_id="abc", project_id=None)

    def make_offline(self, endpoint_id="ep-1"):
        path = self.root / "runtime" / "browser-endpoints.json"
        body = json.loads(path.read_text("utf-8"))
        next(x for x in body["endpoints"] if x["endpointId"] == endpoint_id)["lastSeenAt"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_current_compatible_session_reauthorizes_without_rewriting_run_provenance(self):
        run_id, ctx, old_session = self.create_run(with_session=True)
        self.observe()
        new_session = self.console.sessions.ensure("p1", ["b1"], restart_generation=1)
        self.assertNotEqual(new_session["sessionId"], old_session["sessionId"])
        self.assertEqual(new_session["snapshotDigest"], ctx["snapshotDigest"])
        self.console.sessions.select_endpoint(new_session["sessionId"], "b1", "ep-1", selected_by="test", reason="OPERATOR")

        auth = self.console.profile_context.authorize_delivery(run_id)
        self.assertEqual(auth["deliverySessionId"], new_session["sessionId"])
        self.assertEqual(auth["endpoint"]["endpointId"], "ep-1")
        self.assertEqual(self.console.profile_context.get(run_id)["sessionId"], old_session["sessionId"])

    def test_incompatible_current_session_requires_explicit_decision(self):
        run_id, _ctx, _old = self.create_run(with_session=True)
        edited = self.console.profiles.get_profile("p1", include_prompts=True)
        edited["variables"]["MODE"] = "changed"
        self.console.profiles.save_profile(edited, actor="test", expected_id="p1")
        self.console.sessions.ensure("p1", ["b1"], restart_generation=1)
        self.observe()
        with self.assertRaises(ProfileAuthorizationError) as cm:
            self.console.profile_context.authorize_delivery(run_id)
        self.assertEqual(cm.exception.code, "DELIVERY_SESSION_DECISION_REQUIRED")
        self.assertIn("snapshotDigest", cm.exception.detail["mismatches"])

    def test_wait_timeout_comes_from_run_snapshot_not_live_profile(self):
        run_id, _ctx, session = self.create_run(with_session=True)
        self.observe()
        self.console.sessions.select_endpoint(session["sessionId"], "b1", "ep-1", selected_by="test", reason="OPERATOR")
        self.make_offline()
        edited = self.console.profiles.get_profile("p1", include_prompts=True)
        edited["delivery"]["endpointWaitTimeoutSeconds"] = 99
        self.console.profiles.save_profile(edited, actor="test", expected_id="p1")

        auth = self.console.profile_context.authorize_delivery(run_id, allow_wait=True)
        self.assertTrue(auth["waiting"])
        self.assertEqual(auth["endpoint"]["endpointId"], "ep-1")
        self.assertEqual(auth["endpointWaitTimeoutSeconds"], 3600)

    def test_sessionless_run_uses_normal_selection_and_has_no_delivery_session(self):
        run_id, ctx, _session = self.create_run(with_session=False)
        self.assertIsNone(ctx["sessionId"])
        self.observe()
        auth = self.console.profile_context.authorize_delivery(run_id)
        self.assertIsNone(auth["deliverySessionId"])
        self.assertEqual(auth["endpoint"]["endpointId"], "ep-1")


class EndpointSelectionPolicy(unittest.TestCase):
    @staticmethod
    def ep(endpoint_id, state, *, conv="abc", project=None):
        return {
            "endpointId": endpoint_id, "browserEpoch": "epoch-1", "tabId": 7,
            "chatType": "chatgpt", "conversationId": conv, "projectId": project,
            "state": state, "online": state == "ONLINE",
        }

    def setUp(self):
        self.target = {"chatType": "chatgpt", "conversationId": "abc", "projectId": None}

    def test_session_owned_offline_endpoint_is_sticky(self):
        rows = [self.ep("owned", "OFFLINE"), self.ep("other", "ONLINE")]
        result = EndpointRegistry.select(self.target, rows, "owned")
        self.assertEqual(result["status"], "WAITING_FOR_ENDPOINT")
        self.assertEqual(result["endpoint"]["endpointId"], "owned")

    def test_dead_selection_is_released_and_single_eligible_endpoint_is_chosen(self):
        rows = [self.ep("old", "CLOSED"), self.ep("new", "ONLINE")]
        result = EndpointRegistry.select(self.target, rows, "old")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["endpoint"]["endpointId"], "new")

    def test_multiple_eligible_without_live_session_owner_is_ambiguous(self):
        rows = [self.ep("a", "ONLINE"), self.ep("b", "ONLINE")]
        self.assertEqual(EndpointRegistry.select(self.target, rows)["status"], "ENDPOINT_AMBIGUOUS")

    def test_project_requirement_rejects_missing_project(self):
        target = {**self.target, "projectId": "proj-1"}
        ev = EndpointRegistry.evaluate(target, self.ep("a", "ONLINE", project=None))
        self.assertEqual(ev["verdict"], "PROJECT_MISMATCH")

    def test_selected_endpoint_that_navigated_away_stays_sticky(self):
        rows = [
            self.ep("owned", "ONLINE", conv="other"),
            self.ep("replacement", "ONLINE", conv="abc"),
        ]
        result = EndpointRegistry.select(self.target, rows, "owned")
        self.assertEqual(result["status"], "WAITING_FOR_ENDPOINT")
        self.assertIsNone(result["endpoint"])
        self.assertEqual(result["blockedEndpoint"]["endpointId"], "owned")
        self.assertEqual(result["blockedBy"], "IDENTITY_MISMATCH")


class PollUsesResolvedEndpointIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        token = self.root / "runtime" / "token.txt"
        token.write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.data, token)
        self.console.profiles.save_profile(profile_body(), actor="test", create=True)
        self.console.bindings.create({
            "bindingId": "b1", "name": "B1", "chatType": "chatgpt",
            "conversationId": "abc", "profileId": "p1", "role": "source",
            "enabled": True,
        }, "test")
        self.session = self.console.sessions.ensure("p1", ["b1"], restart_generation=0)
        self.console.endpoints.observe(
            7, PAGE, endpoint_id="ep-1", title="ep-1", browser_epoch="epoch-1",
            chat_type="chatgpt", conversation_id="abc", project_id=None)
        self.console.endpoints.observe(
            8, PAGE, endpoint_id="ep-2", title="ep-2", browser_epoch="epoch-1",
            chat_type="chatgpt", conversation_id="abc", project_id=None)
        receiver = ReceiverHarness(self.root)
        try:
            status, body = receiver.post_json("/api/chat-result", intake_payload())
            self.assertEqual(status, 200)
        finally:
            receiver.close()
        self.run_id = body["runId"]
        result = dict(self.console.executor.load_result(self.run_id))
        source = dict(result.get("papSource") or {})
        source.update({
            "tabId": 7, "url": PAGE, "chatType": "chatgpt",
            "endpointId": "ep-1", "browserEpoch": "epoch-1",
            "conversationId": "abc", "projectId": None,
        })
        result["papSource"] = source
        plan = self.console.executor.ensure_plan(self.run_id)
        state = self.console.executor.ensure_state(self.run_id, plan)
        self.job = self.console.delivery.create_job(
            self.run_id, result, plan, state, "hello", "open", 8 * 1024 * 1024, 120,
            delivery_session_id=self.session["sessionId"],
            side_effect_key=f"chat.send:{self.run_id}:b1")
        self.job["profileDelivery"] = {
            "bindingId": "b1", "profileId": "p1",
            "deliverySessionId": self.session["sessionId"],
            "state": "READY", "waitStartedAt": None, "timeoutSec": None,
        }
        self.job = self.console.delivery.save_job(self.job)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reused_tab_or_other_endpoint_cannot_receive_prepared_job(self):
        self.assertIsNone(self.console.delivery.poll_for_tab(7, PAGE, "ep-new"))
        self.assertIsNotNone(self.console.delivery.poll_for_tab(7, PAGE, "ep-1"))

    def test_retry_refuses_changed_authorized_endpoint_before_mutation(self):
        current = self.console.delivery.get_job(self.run_id, self.job["jobId"])
        current["attachments"][0]["state"] = "ERROR"
        current["attachments"][0]["phase"] = "ERROR"
        current["attachments"][0]["error"] = "fixture"
        current = self.console.delivery.save_job(current)
        before = self.console.delivery.get_job(self.run_id, self.job["jobId"])

        self.console.sessions.select_endpoint(
            self.session["sessionId"], "b1", "ep-2", selected_by="test", reason="OPERATOR")

        class R:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": self.run_id, "job_id": self.job["jobId"]}

        response = asyncio.run(self.console.api_delivery_retry(R()))
        self.assertEqual(response.status, 409)
        self.assertIn("DELIVERY_TARGET_CHANGED", response.text)
        self.assertEqual(
            self.console.delivery.get_job(self.run_id, self.job["jobId"]), before,
            "target-change refusal must precede retry state mutation",
        )

    def test_dead_explicit_selection_releases_poll_to_new_authorized_endpoint(self):
        self.console.sessions.select_endpoint(
            self.session["sessionId"], "b1", "ep-1", selected_by="test", reason="OPERATOR")
        self.console.endpoints.close("ep-1", "epoch-1")

        auth = self.console.profile_context.authorize_delivery(self.run_id)
        self.assertEqual(auth["endpoint"]["endpointId"], "ep-2")
        self.assertFalse(auth["selection"]["sessionOwned"])

        result = dict(self.console.executor.load_result(self.run_id))
        source = dict(result.get("papSource") or {})
        source.update({
            "tabId": 8, "url": PAGE, "chatType": "chatgpt",
            "endpointId": "ep-2", "browserEpoch": "epoch-1",
            "conversationId": "abc", "projectId": None,
        })
        result["papSource"] = source
        plan = self.console.executor.ensure_plan(self.run_id)
        state = self.console.executor.ensure_state(self.run_id, plan)
        job = self.console.delivery.create_job(
            self.run_id, result, plan, state, "after-dead-selection", "open",
            8 * 1024 * 1024, 120, delivery_session_id=self.session["sessionId"],
            side_effect_key=f"chat.send:{self.run_id}:b1:after-dead")
        job["profileDelivery"] = {
            "bindingId": "b1", "profileId": "p1",
            "deliverySessionId": self.session["sessionId"],
            "state": "READY", "waitStartedAt": None, "timeoutSec": None,
        }
        job = self.console.delivery.save_job(job)
        ep2 = next(e for e in self.console.endpoints.list()["endpoints"]
                   if e["endpointId"] == "ep-2")
        self.assertTrue(self.console._profile_job_poll_allowed(job, ep2))

    def test_explicit_selection_change_blocks_the_old_prepared_target(self):
        self.console.sessions.select_endpoint(
            self.session["sessionId"], "b1", "ep-2", selected_by="test", reason="OPERATOR")
        current = self.console.delivery.get_job(self.run_id, self.job["jobId"])
        ep1 = next(e for e in self.console.endpoints.list()["endpoints"]
                   if e["endpointId"] == "ep-1")
        self.assertFalse(self.console._profile_job_poll_allowed(current, ep1))


class LogicalDeliveryAndManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.root / "runtime").mkdir()
        self.dm = DeliveryManager(self.root, self.data, lambda _r: "terminal\n", "epoch-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def result(self, tab=7, endpoint="ep-1"):
        return {
            "papSource": {
                "tabId": tab, "url": PAGE, "chatType": "chatgpt",
                "endpointId": endpoint, "browserEpoch": "epoch-1",
                "conversationId": "abc", "projectId": None,
            },
            "page": PAGE, "chatType": "chatgpt", "chatLabel": "Chat",
        }

    def create(self, run_id, message, *, side=None):
        (self.data / run_id / "executor").mkdir(parents=True, exist_ok=True)
        return self.dm.create_job(
            run_id, self.result(), {"steps": []}, {"steps": {}}, message,
            "open", 8 * 1024 * 1024, 120,
            delivery_session_id="ps-1", side_effect_key=side)

    def create_with_reports(self, run_id, *, mode="open", count=1):
        executor = self.data / run_id / "executor"
        snapshots = executor / "snapshots" / "s001"
        snapshots.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for idx in range(1, count + 1):
            path = snapshots / f"{idx:02d}_report-{idx}.txt"
            path.write_text(f"report-{idx}\n", encoding="utf-8")
            artifacts.append({
                "artifactId": f"s001-{idx:02d}",
                "originalPath": f"/tmp/pap2/report-{idx}.txt",
                "snapshotPath": str(path),
                "name": f"report-{idx}.txt",
                "present": True,
                "size": path.stat().st_size,
            })
        plan = {"steps": [{"stepId": "s001", "type": "COMMAND_GET_REPORTS"}]}
        state = {"steps": {"s001": {
            "status": "DONE", "reportArtifacts": artifacts, "missingReports": [],
        }}}
        return self.dm.create_job(
            run_id, self.result(), plan, state, "hello", mode,
            8 * 1024 * 1024, 120, delivery_session_id="ps-1")

    def test_same_logical_delivery_supersedes_only_its_older_attempt(self):
        first = self.create("run1", "first")
        second = self.create("run1", "second")
        self.assertEqual(first["logicalDeliveryId"], second["logicalDeliveryId"])
        self.assertEqual(self.dm.get_job(first["runId"], first["jobId"])["status"], "SUPERSEDED")

    def test_two_distinct_deliveries_to_same_tab_do_not_supersede_each_other(self):
        first = self.create("run1", "one")
        second = self.create("run2", "two")
        self.assertNotEqual(first["logicalDeliveryId"], second["logicalDeliveryId"])
        self.assertEqual(self.dm.get_job(first["runId"], first["jobId"])["status"], "QUEUED")
        self.assertEqual(self.dm.get_job(second["runId"], second["jobId"])["status"], "QUEUED")

    def test_manifest_binds_endpoint_message_names_sizes_and_bytes(self):
        job = self.create("run1", "hello")
        manifest = job["deliveryManifest"]
        self.assertEqual(manifest["deliveryId"], job["jobId"])
        self.assertEqual(manifest["target"]["endpointId"], "ep-1")
        self.assertEqual(manifest["message"], "hello")
        self.assertEqual(manifest["logicalDeliveryId"], job["logicalDeliveryId"])
        self.assertEqual(manifest["sideEffectKey"], job["sideEffectKey"])
        self.assertEqual(manifest["attachments"][0]["ordinal"], 1)
        self.assertEqual(
            manifest["attachments"][0]["outgoingFilename"],
            job["attachments"][0]["name"],
        )
        self.assertIsNone(manifest["attachments"][0]["artifactId"])
        self.assertTrue(manifest["attachments"][0]["sha256"])

        attachment = Path(job["attachments"][0]["path"])
        attachment_id = job["attachments"][0]["attachmentId"]
        self.dm.update_from_client(job["runId"], job["jobId"], {
            "event": "CLAIM", "tabId": 7, "leaseToken": "tok", "url": PAGE,
        })
        attachment.write_bytes(attachment.read_bytes() + b"changed")
        with self.assertRaises(DeliveryError) as cm:
            self.dm.attachment_chunk(
                job["runId"], job["jobId"], attachment_id, 0, 64 * 1024,
                tab_id=7, lease_token="tok")
        self.assertIn("DELIVERY_MANIFEST_INVALID", str(cm.exception))

    def test_report_artifact_identity_survives_outgoing_rename_and_manifest_order(self):
        job = self.create_with_reports("run1", mode="packed", count=1)
        manifest = job["deliveryManifest"]
        self.assertEqual([x["ordinal"] for x in manifest["attachments"]], [1, 2])
        report = manifest["attachments"][1]
        self.assertEqual(report["artifactId"], "s001-01")
        self.assertEqual(report["sourceArtifactIds"], [])
        self.assertEqual(report["outgoingFilename"], "report-1.txt.zip")
        self.assertEqual(
            report["outgoingFilename"], job["attachments"][1]["name"],
            "the manifest must record the actual outgoing name, not the source name",
        )

    def test_smart_bundle_keeps_all_source_artifact_ids_in_manifest_provenance(self):
        job = self.create_with_reports("run1", mode="smart_zip", count=2)
        bundle = next(x for x in job["deliveryManifest"]["attachments"]
                      if x["outgoingFilename"].endswith(".zip"))
        self.assertIsNone(bundle["artifactId"])
        self.assertEqual(bundle["sourceArtifactIds"], ["s001-01", "s001-02"])
        attachment = next(x for x in job["attachments"]
                          if x["attachmentId"] == bundle["attachmentId"])
        self.assertEqual(
            [m["artifactId"] for m in attachment["members"] if m["artifactId"]],
            ["s001-01", "s001-02"],
        )

    def test_files_as_sent_ignore_newer_source_bytes_after_manifest_creation(self):
        job = self.create_with_reports("run1", mode="open", count=1)
        report_attachment = next(x for x in job["attachments"]
                                 if x.get("artifactId") == "s001-01")
        source_snapshot = (self.data / "run1" / "executor" / "snapshots"
                           / "s001" / "01_report-1.txt")
        source_snapshot.write_text("newer-report\n", encoding="utf-8")

        self.dm.update_from_client(job["runId"], job["jobId"], {
            "event": "CLAIM", "tabId": 7, "endpointId": "ep-1",
            "leaseToken": "tok", "url": PAGE,
        })
        chunk = self.dm.attachment_chunk(
            job["runId"], job["jobId"], report_attachment["attachmentId"], 0, 64 * 1024,
            tab_id=7, endpoint_id="ep-1", lease_token="tok")
        self.assertEqual(base64.b64decode(chunk["dataBase64"]), b"report-1\n")
        manifest_row = next(x for x in job["deliveryManifest"]["attachments"]
                            if x["artifactId"] == "s001-01")
        self.assertEqual(manifest_row["outgoingFilename"], "report-1.txt")

    def test_manifest_ordinal_refuses_reordered_persisted_attachments(self):
        job = self.create_with_reports("run1", mode="open", count=2)
        damaged = self.dm.get_job(job["runId"], job["jobId"])
        damaged["attachments"][1], damaged["attachments"][2] = (
            damaged["attachments"][2], damaged["attachments"][1])
        with self.assertRaises(DeliveryError) as cm:
            self.dm.save_job(damaged)
        self.assertIn("attachment order", str(cm.exception))

    def test_event_endpoint_identity_is_part_of_the_prepared_target_proof(self):
        job = self.create("run1", "hello")
        before = self.dm.get_job(job["runId"], job["jobId"])
        with self.assertRaises(DeliveryError) as cm:
            self.dm.update_from_client(job["runId"], job["jobId"], {
                "event": "CLAIM", "tabId": 7, "endpointId": "ep-other",
                "leaseToken": "tok", "url": PAGE,
            })
        self.assertIn("another endpoint", str(cm.exception))
        self.assertEqual(self.dm.get_job(job["runId"], job["jobId"]), before)

    def test_chunk_endpoint_identity_is_checked_before_lease_or_bytes(self):
        job = self.create("run1", "hello")
        attachment_id = job["attachments"][0]["attachmentId"]
        with self.assertRaises(DeliveryError) as cm:
            self.dm.attachment_chunk(
                job["runId"], job["jobId"], attachment_id, 0, 64 * 1024,
                tab_id=7, lease_token="", endpoint_id="ep-other")
        self.assertIn("another endpoint", str(cm.exception))

    def test_missing_endpoint_identity_is_refused_before_job_directory_is_created(self):
        result = self.result()
        del result["papSource"]["endpointId"]
        before = list(self.data.rglob("job.json"))
        with self.assertRaises(DeliveryError):
            self.dm.create_job("run1", result, {"steps": []}, {"steps": {}}, "m", "open", 8 * 1024 * 1024, 120)
        self.assertEqual(list(self.data.rglob("job.json")), before)


if __name__ == "__main__":
    unittest.main()
