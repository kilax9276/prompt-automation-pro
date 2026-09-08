# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Slice 2 atomic server block: endpoint model, ownership and poll barriers.

The point of these tests is the *order* of refusal. A registry unit test cannot
show it: the defect this block fixes was that an incompatible client reached
the registry first and only then failed, inside a swallowed try, so a broken
call looked like a healthy empty response. Every case here therefore goes
through api_delivery_poll and asserts what the registry holds afterwards.
"""
from __future__ import annotations

import asyncio
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

from console_server import ConsoleServer, REQUIRED_EXTENSION_VERSION
from endpoint_registry import EndpointError, EndpointRegistry


class Req:
    def __init__(self, **query):
        self.headers = {"Authorization": "Bearer ctok"}
        self.rel_url = type("U", (), {"query": {k: str(v) for k, v in query.items() if v is not None}})()


class EndpointModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "runtime").mkdir(parents=True)
        self.reg = EndpointRegistry(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def obs(self, endpoint_id="ep-1", epoch="e1", tab=7, page="https://chatgpt.com/c/abc",
            chat_type="chatgpt", conversation_id="abc"):
        return self.reg.observe(tab, page, endpoint_id=endpoint_id, title="T", browser_epoch=epoch,
                                chat_type=chat_type, conversation_id=conversation_id)

    def test_page_reload_keeps_endpoint_id_within_the_epoch(self):
        first = self.obs()
        again = self.obs(page="https://chatgpt.com/c/abc?reloaded=1")
        self.assertEqual(first["endpointId"], again["endpointId"])
        self.assertEqual(again["browserEpoch"], "e1")
        self.assertEqual(len(self.reg.list()["endpoints"]), 1)

    def test_late_pulse_after_closed_does_not_revive(self):
        self.obs()
        self.reg.close("ep-1", "e1")
        row = self.obs()
        self.assertEqual(row["state"], "CLOSED")
        self.assertFalse(row["online"])

    def test_late_pulse_of_previous_epoch_after_expired_does_not_revive(self):
        self.obs(epoch="e1")
        self.reg.acquire_control("e1")
        self.expire_lease()
        self.reg.acquire_control("e2")            # takeover after the lease died
        rows = {r["endpointId"]: r for r in self.reg.list()["endpoints"]}
        self.assertEqual(rows["ep-1"]["state"], "EXPIRED")
        # Design 9a: a late pulse for a terminal endpoint is ignored, not
        # rejected — the race is harmless, and the row must simply not move.
        row = self.obs(epoch="e1")
        self.assertEqual(row["state"], "EXPIRED")
        self.assertFalse(row["online"])
        self.assertEqual(self.reg.list()["endpoints"][0]["state"], "EXPIRED")

    def expire_lease(self):
        body = json.loads((self.root / "runtime" / "browser-endpoints.json").read_text("utf-8"))
        body["control"]["leaseUntil"] = "2020-01-01T00:00:00Z"
        (self.root / "runtime" / "browser-endpoints.json").write_text(json.dumps(body), encoding="utf-8")

    def test_lease_gap_without_owner_change_keeps_endpoint_id(self):
        self.obs()
        self.reg.acquire_control("e1")
        self.expire_lease()
        again = self.reg.acquire_control("e1")    # same epoch returns before takeover
        self.assertTrue(again["owner"])
        self.assertTrue(again["reacquired"])
        self.assertFalse(again["transferred"])
        self.assertEqual(again["expiredEndpoints"], [])
        self.assertEqual(self.reg.list()["endpoints"][0]["endpointId"], "ep-1")


    def test_identity_comes_from_stated_fields_not_the_url(self):
        """Design 9a: the raw URL takes no part in identity evaluation."""
        row = self.obs(page="https://chatgpt.com/c/url-id", conversation_id="explicit-id")
        self.assertEqual(row["conversationId"], "explicit-id")
        self.assertEqual(row["url"], "https://chatgpt.com/c/url-id")
        stored = self.reg.list()["endpoints"][0]
        self.assertEqual(stored["conversationId"], "explicit-id")

    def test_identity_is_required(self):
        with self.assertRaises(EndpointError):
            self.reg.observe(7, "https://chatgpt.com/c/abc", endpoint_id="ep-x",
                             browser_epoch="e1", chat_type="chatgpt", conversation_id=None)

    def test_second_live_epoch_is_refused_without_any_write(self):
        first = self.reg.acquire_control("e1")
        self.assertTrue(first["owner"])
        before = (self.root / "runtime" / "browser-endpoints.json").read_bytes()
        second = self.reg.acquire_control("e2")
        self.assertFalse(second["owner"])
        self.assertTrue(second["conflict"])
        self.assertEqual(second["heldBy"], "e1")
        self.assertEqual((self.root / "runtime" / "browser-endpoints.json").read_bytes(), before,
                         "a refused acquisition must write nothing")

    def test_takeover_expires_previous_endpoints_in_one_write(self):
        self.obs(endpoint_id="ep-a", epoch="e1")
        self.obs(endpoint_id="ep-b", epoch="e1")
        self.reg.acquire_control("e1")
        self.expire_lease()
        result = self.reg.acquire_control("e2")
        self.assertTrue(result["transferred"])
        self.assertEqual(sorted(result["expiredEndpoints"]), ["ep-a", "ep-b"])
        states = {r["endpointId"]: r["state"] for r in self.reg.list()["endpoints"]}
        self.assertEqual(states, {"ep-a": "EXPIRED", "ep-b": "EXPIRED"})
        # Owner and expiries are one commit: no state where the new owner holds
        # live endpoints of an epoch that no longer exists.
        self.assertEqual(self.reg.control_state()["browserEpoch"], "e2")

    def test_expired_lease_means_not_owner(self):
        self.reg.acquire_control("e1")
        self.assertTrue(self.reg.control_check("e1")["owner"])
        self.expire_lease()
        self.assertFalse(self.reg.control_check("e1")["owner"])
        self.assertFalse(self.reg.control_check("e1")["conflict"])

    def test_list_returns_observed_state_without_policy(self):
        self.obs()
        listing = self.reg.list()
        self.assertNotIn("pins", listing)
        row = listing["endpoints"][0]
        for policy_field in ("bindingId", "approved", "approvedEndpointId", "stale", "identityConflict"):
            self.assertNotIn(policy_field, row)
        self.assertIn("state", row)
        self.assertIn("browserEpoch", row)

    def test_offline_endpoints_are_not_hidden_by_the_server(self):
        self.obs()
        body = json.loads((self.root / "runtime" / "browser-endpoints.json").read_text("utf-8"))
        body["endpoints"][0]["lastSeenAt"] = "2020-01-01T00:00:00Z"
        (self.root / "runtime" / "browser-endpoints.json").write_text(json.dumps(body), encoding="utf-8")
        listing = EndpointRegistry(self.root).list()
        self.assertEqual(len(listing["endpoints"]), 1)
        self.assertEqual(listing["endpoints"][0]["state"], "OFFLINE")


class PollBarriers(unittest.TestCase):
    """Refusal must happen before the registry is touched, never after."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def poll(self, **query):
        return asyncio.run(self.console.api_delivery_poll(Req(**query)))

    def endpoint_poll(self, epoch="e1", endpoint_id="ep-1", tab=7, **over):
        q = dict(pollKind="ENDPOINT", browserEpoch=epoch, endpointId=endpoint_id, tabId=tab,
                 page="https://chatgpt.com/c/abc", chatType="chatgpt", conversationId="abc",
                 extensionVersion=REQUIRED_EXTENSION_VERSION)
        q.update(over)
        return self.poll(**{k: v for k, v in q.items() if v is not None})

    def expire_lease(self):
        path = self.root / "runtime" / "browser-endpoints.json"
        body = json.loads(path.read_text("utf-8"))
        body["control"]["leaseUntil"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(body), encoding="utf-8")

    def endpoints(self):
        return self.console.endpoints.list()["endpoints"]

    def own(self, epoch="e1"):
        r = self.poll(pollKind="CONTROL_AGENT", browserEpoch=epoch,
                      extensionVersion=REQUIRED_EXTENSION_VERSION)
        self.assertEqual(r.status, 200)

    def test_compatible_owner_records_the_endpoint(self):
        self.own()
        r = self.endpoint_poll()
        self.assertEqual(r.status, 200)
        self.assertEqual([e["endpointId"] for e in self.endpoints()], ["ep-1"])

    def test_wrong_version_is_refused_before_observe(self):
        self.own()
        r = self.endpoint_poll(endpoint_id="ep-9", tab=9, extensionVersion="2.11.6")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "EXTENSION_VERSION_INCOMPATIBLE")
        self.assertEqual(self.endpoints(), [], "observe must not have run")

    def test_foreign_live_epoch_gets_conflict_before_observe(self):
        """ACC-S2-005: a foreign epoch while the owner lives is a conflict."""
        self.own(epoch="e1")
        r = self.endpoint_poll(epoch="e2", endpoint_id="ep-2", tab=8)
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "CONTROL_AGENT_CONFLICT")
        self.assertEqual(self.endpoints(), [])

    def test_expired_lease_gets_not_owner_before_observe(self):
        """ACC-S2-004: no live owner is a different answer from a conflict."""
        self.own(epoch="e1")
        self.expire_lease()
        r = self.endpoint_poll(epoch="e1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "NOT_CONTROL_OWNER")
        self.assertEqual(self.endpoints(), [])

    def test_second_live_control_agent_gets_conflict_and_no_plan(self):
        """ACC-S2-003: the loser gets no plan and changes nothing."""
        self.own(epoch="e1")
        r = self.poll(pollKind="CONTROL_AGENT", browserEpoch="e2",
                      extensionVersion=REQUIRED_EXTENSION_VERSION)
        self.assertEqual(r.status, 409)
        body = json.loads(r.body)
        self.assertEqual(body["code"], "CONTROL_AGENT_CONFLICT")
        self.assertEqual(body["heldBy"], "e1")
        self.assertNotIn("plan", body)
        self.assertEqual(self.console.endpoints.control_state()["browserEpoch"], "e1")

    def test_takeover_after_expired_lease_expires_previous_endpoints(self):
        self.own(epoch="e1")
        self.endpoint_poll(epoch="e1", endpoint_id="ep-1")
        self.expire_lease()
        r = self.poll(pollKind="CONTROL_AGENT", browserEpoch="e2",
                      extensionVersion=REQUIRED_EXTENSION_VERSION)
        self.assertEqual(r.status, 200)
        body = json.loads(r.body)
        self.assertTrue(body["transferred"])
        self.assertEqual(body["expiredEndpoints"], ["ep-1"])
        self.assertEqual(self.endpoints()[0]["state"], "EXPIRED")

    def test_missing_epoch_or_endpoint_is_refused_before_observe(self):
        self.own()
        for query, code in [
            (dict(pollKind="ENDPOINT", endpointId="ep-3", tabId=3, chatType="chatgpt",
                  conversationId="abc",
                  extensionVersion=REQUIRED_EXTENSION_VERSION), "BROWSER_EPOCH_REQUIRED"),
            (dict(pollKind="ENDPOINT", browserEpoch="e1", tabId=3, chatType="chatgpt",
                  conversationId="abc",
                  extensionVersion=REQUIRED_EXTENSION_VERSION), "ENDPOINT_ID_REQUIRED"),
            (dict(pollKind="ENDPOINT", browserEpoch="e1", endpointId="ep-3", tabId=3,
                  extensionVersion=REQUIRED_EXTENSION_VERSION), "ENDPOINT_IDENTITY_REQUIRED"),
            (dict(pollKind="NONSENSE", browserEpoch="e1", endpointId="ep-3", tabId=3,
                  extensionVersion=REQUIRED_EXTENSION_VERSION), "POLL_KIND_INVALID"),
        ]:
            with self.subTest(code=code):
                r = self.poll(**query)
                self.assertIn(r.status, (400, 409))
                self.assertEqual(json.loads(r.body)["code"], code)
                self.assertEqual(self.endpoints(), [])

    def test_registry_refusal_is_answered_not_swallowed(self):
        """The defect class: a rejected observe must never look like an empty 200.

        The refusal is forced at the registry itself. An earlier version of this
        test used a foreign epoch, which the ownership barrier rejects before
        observe is ever called — so it proved a different thing than its name.
        """
        self.own()
        original = self.console.endpoints.observe

        def refusing(*args, **kwargs):
            raise EndpointError("probe")

        self.console.endpoints.observe = refusing
        try:
            r = self.endpoint_poll()
        finally:
            self.console.endpoints.observe = original
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "ENDPOINT_REJECTED")

    def test_real_legacy_client_is_recorded_and_cleared_after_upgrade(self):
        """A real 2.11.6 poll carries no slice-2 identity at all."""
        r = self.poll(tabId=7, page="https://chatgpt.com/c/c1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "EXTENSION_VERSION_INCOMPATIBLE")
        rows = self.console.version_mismatches()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scope"], "LEGACY_AGENT")
        self.assertIsNone(rows[0]["endpointId"])
        self.assertEqual(self.endpoints(), [])

        self.own(epoch="e1")
        self.assertEqual(self.console.version_mismatches(), [],
                         "a compatible control handshake clears the legacy record")

    def test_version_mismatch_is_recorded_once_and_cleared_on_handshake(self):
        self.endpoint_poll(extensionVersion="2.11.6")
        self.endpoint_poll(extensionVersion="2.11.6")
        rows = self.console.version_mismatches()
        self.assertEqual(len(rows), 1, "repeated polls refresh the record, not multiply it")
        self.assertEqual(rows[0]["observed"], "2.11.6")
        self.assertEqual(rows[0]["expected"], REQUIRED_EXTENSION_VERSION)
        self.assertNotEqual(rows[0]["firstSeenAt"], "")
        self.own(epoch="e1")
        self.assertEqual(self.console.version_mismatches(), [])

class RegistrySchemaBoundary(unittest.TestCase):
    """Slice-1 endpoint state is invalidated at the boundary, never reinterpreted.

    A tabId says nothing about which endpoint it was, so slice-1 rows cannot be
    given an endpointId or a browserEpoch. Reading them as slice-2 rows produced
    ghost endpoints with no identity that selection could still pick up.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "runtime").mkdir(parents=True)
        self.path = self.root / "runtime" / "browser-endpoints.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_legacy(self):
        self.path.write_text(json.dumps({
            "schemaVersion": 1,
            "endpoints": [{"tabId": 7, "endpointId": None, "chatType": "chatgpt",
                           "conversationId": "c1", "projectId": None,
                           "url": "https://chatgpt.com/c/c1", "title": "T",
                           "firstSeenAt": "2026-01-01T00:00:00Z",
                           "lastSeenAt": "2026-01-01T00:00:00Z"}],
            "pins": {"b1": {"tabId": 7, "pinnedAt": "2026-01-01T00:00:00Z"}},
        }), encoding="utf-8")

    def test_legacy_registry_is_refused_until_invalidated(self):
        self.write_legacy()
        reg = EndpointRegistry(self.root)
        with self.assertRaises(EndpointError) as cm:
            reg.list()
        self.assertIn("REGISTRY_MIGRATION_REQUIRED", str(cm.exception))
        with self.assertRaises(EndpointError):
            reg.acquire_control("e1")

    def test_invalidation_discards_endpoints_and_pins_and_keeps_evidence(self):
        self.write_legacy()
        reg = EndpointRegistry(self.root)
        report = reg.invalidate_legacy_registry()
        self.assertTrue(report["migrated"])
        self.assertEqual(report["fromSchemaVersion"], 1)
        self.assertEqual(report["discardedEndpoints"], 1)
        self.assertEqual(report["discardedPins"], 1)

        body = json.loads(self.path.read_text("utf-8"))
        self.assertEqual(body["schemaVersion"], 2)
        self.assertEqual(body["endpoints"], [])
        self.assertNotIn("pins", body)

        listing = EndpointRegistry(self.root).list()
        self.assertEqual(listing["schemaVersion"], 2)
        self.assertEqual(listing["endpoints"], [])

        # The old state survives as rollback evidence, not as live state.
        backup = json.loads(Path(report["backup"]).read_text("utf-8"))
        self.assertEqual(backup["endpoints"][0]["tabId"], 7)
        self.assertIn("pins", backup)

    def test_no_identity_is_synthesised_for_legacy_rows(self):
        self.write_legacy()
        reg = EndpointRegistry(self.root)
        reg.invalidate_legacy_registry()
        reg.acquire_control("e1")
        self.assertEqual(reg.list()["endpoints"], [],
                         "a legacy row must not reappear with an invented endpointId")


    def test_corrupt_registry_is_refused_not_reset(self):
        """Damage must fail closed too, or the boundary is only half a boundary."""
        self.path.write_text("{not json", encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(EndpointError) as cm:
            EndpointRegistry(self.root).list()
        self.assertIn("REGISTRY_INVALID", str(cm.exception))
        self.assertEqual(self.path.read_bytes(), before, "a corrupt file must not be rewritten")

    def test_registry_without_schema_version_is_refused(self):
        self.path.write_text(json.dumps({"endpoints": []}), encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(EndpointError) as cm:
            EndpointRegistry(self.root).list()
        self.assertIn("REGISTRY_INVALID", str(cm.exception))
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalidation_refuses_an_unknown_registry(self):
        self.path.write_text(json.dumps({"schemaVersion": 99, "endpoints": []}), encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(EndpointError):
            EndpointRegistry(self.root).invalidate_legacy_registry()
        self.assertEqual(self.path.read_bytes(), before,
                         "evidence of an unknown registry must survive")

    def test_no_way_left_to_create_a_pin(self):
        reg = EndpointRegistry(self.root)
        for gone in ("pin", "unpin"):
            self.assertFalse(hasattr(reg, gone), f"{gone} must no longer exist")


    def test_damaged_schema2_registry_is_refused_not_coerced(self):
        """Damage inside the current schema fails closed too.

        Coercing a broken field back to a default is the same fail-open the
        version check removed: an endpoint row with no identity cannot exist in
        schema 2, and turning it into a ghost is how such a row reached
        selection before.
        """
        cases = {
            "endpoints not a list": {"schemaVersion": 2, "endpoints": "oops", "control": {}},
            "control not an object": {"schemaVersion": 2, "endpoints": [], "control": []},
            "row not an object": {"schemaVersion": 2, "endpoints": [7], "control": {}},
            "row without identity": {"schemaVersion": 2, "control": {},
                                     "endpoints": [{"tabId": 7, "state": "ONLINE"}]},
            "row without epoch": {"schemaVersion": 2, "control": {}, "endpoints": [
                {"endpointId": "ep-1", "tabId": 7, "state": "ONLINE",
                 "chatType": "chatgpt", "conversationId": "c1"}]},
            "unknown state": {"schemaVersion": 2, "control": {}, "endpoints": [
                {"endpointId": "ep-1", "browserEpoch": "e1", "tabId": 7, "state": "WAT",
                 "chatType": "chatgpt", "conversationId": "c1"}]},
            "duplicate endpointId": {"schemaVersion": 2, "control": {}, "endpoints": [
                {"endpointId": "ep-1", "browserEpoch": "e1", "tabId": 7, "state": "ONLINE",
                 "chatType": "chatgpt", "conversationId": "c1"},
                {"endpointId": "ep-1", "browserEpoch": "e1", "tabId": 8, "state": "ONLINE",
                 "chatType": "chatgpt", "conversationId": "c2"}]},
            "control half filled": {"schemaVersion": 2, "endpoints": [],
                                    "control": {"browserEpoch": "e1"}},
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                self.path.write_text(json.dumps(body), encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaises(EndpointError) as cm:
                    EndpointRegistry(self.root).list()
                self.assertIn("REGISTRY_INVALID", str(cm.exception))
                self.assertEqual(self.path.read_bytes(), before)


    def test_timestamps_must_carry_an_offset_and_schema_version_is_not_coerced(self):
        """Naive timestamps used to parse, then crash far away with a TypeError."""
        def row(**over):
            base = {"endpointId": "ep-1", "browserEpoch": "e1", "tabId": 7,
                    "state": "ONLINE", "chatType": "chatgpt", "conversationId": "c1",
                    "firstSeenAt": "2026-09-07T10:00:00Z", "lastSeenAt": "2026-09-07T10:00:00Z"}
            base.update(over)
            return base

        live_control = {"browserEpoch": "e1", "acquiredAt": "2026-09-07T10:00:00Z",
                        "lastSeenAt": "2026-09-07T10:00:00Z", "leaseUntil": "2026-09-07T10:00:00Z"}
        cases = {
            'schemaVersion as string': {"schemaVersion": "2", "endpoints": [], "control": {}},
            'schemaVersion as float': {"schemaVersion": 2.9, "endpoints": [], "control": {}},
            'schemaVersion as bool': {"schemaVersion": True, "endpoints": [], "control": {}},
            'naive control timestamps': {"schemaVersion": 2, "endpoints": [], "control": dict(
                live_control, acquiredAt="2026-09-07T10:00:00")},
            'naive endpoint lastSeenAt': {"schemaVersion": 2, "control": {},
                                          "endpoints": [row(lastSeenAt="2026-09-07T10:00:00")]},
            'endpoint without lastSeenAt': {"schemaVersion": 2, "control": {},
                                            "endpoints": [{k: v for k, v in row().items()
                                                           if k != "lastSeenAt"}]},
            'terminal without terminatedAt': {"schemaVersion": 2, "control": {},
                                              "endpoints": [row(state="CLOSED")]},
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                self.path.write_text(json.dumps(body), encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaises(EndpointError) as cm:
                    EndpointRegistry(self.root).list()
                self.assertIn("REGISTRY_INVALID", str(cm.exception))
                self.assertEqual(self.path.read_bytes(), before)

    def test_a_foreign_integer_schema_is_migration_not_invalid(self):
        """The two refusals point at different problems and must stay distinct."""
        self.path.write_text(json.dumps({"schemaVersion": 1, "endpoints": [], "pins": {}}),
                             encoding="utf-8")
        with self.assertRaises(EndpointError) as cm:
            EndpointRegistry(self.root).list()
        self.assertIn("REGISTRY_MIGRATION_REQUIRED", str(cm.exception))

    def test_legacy_backup_keeps_the_original_bytes(self):
        """The backup is rollback evidence, so it must be byte-exact."""
        raw = ('{"schemaVersion":1,   "endpoints":[{"tabId":7,"endpointId":null}],\n'
               ' "pins":{"b1":{"tabId":7}}}\n')
        self.path.write_text(raw, encoding="utf-8")
        report = EndpointRegistry(self.root).invalidate_legacy_registry()
        self.assertTrue(report["migrated"])
        self.assertEqual(Path(report["backup"]).read_text("utf-8"), raw,
                         "a re-serialised copy is not the file that was there")

    def test_invalidation_is_idempotent_on_a_current_registry(self):
        reg = EndpointRegistry(self.root)
        first = reg.invalidate_legacy_registry()
        self.assertFalse(first["migrated"])
        self.assertEqual(first["reason"], "already-current")
        self.assertIsNone(first["backup"])

class PinApiRemoved(unittest.TestCase):
    """No route, no handler, no button: nothing can create a pin any more."""

    def test_console_has_no_pin_route_or_handler(self):
        src = (CONSOLE / "console_server.py").read_text("utf-8")
        self.assertNotIn('add_post("/api/endpoints/{tab_id}/pin"', src)
        self.assertNotIn('add_delete("/api/endpoints/{tab_id}/pin"', src)
        self.assertNotIn("async def api_endpoint_pin", src)
        self.assertNotIn("async def api_endpoint_unpin", src)

    def test_ui_offers_no_pin_action(self):
        js = (CONSOLE / "static" / "app.js").read_text("utf-8")
        for gone in ("pin-endpoint", "unpin-endpoint", "/pin`", "async function pinEndpoint"):
            self.assertNotIn(gone, js)

class EventRouteBarriers(unittest.TestCase):
    """The event route must not be a way around the poll barrier.

    Before slice 2 it had no version gate, no epoch and no ownership check at
    all: an incompatible client could not poll, but could still move delivery
    state through this route.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        self.moved = []
        self.console.delivery.update_from_client = lambda *a, **k: self.moved.append(a) or {"id": "j"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def event(self, **query):
        class R:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": "r1", "job_id": "j1"}
            def __init__(s, q):
                s.rel_url = type("U", (), {"query": q})()
            async def json(s):
                return {"state": "SENT"}
        q = {k: str(v) for k, v in query.items() if v is not None}
        return asyncio.run(self.console.api_delivery_event(R(q)))

    def own_and_observe(self, epoch="e1", endpoint_id="ep-1"):
        cls = type(self.console)
        req = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                             "rel_url": type("U", (), {"query": {
                                 "pollKind": "CONTROL_AGENT", "browserEpoch": epoch,
                                 "extensionVersion": REQUIRED_EXTENSION_VERSION}})()})()
        asyncio.run(self.console.api_delivery_poll(req))
        req2 = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                              "rel_url": type("U", (), {"query": {
                                  "pollKind": "ENDPOINT", "browserEpoch": epoch,
                                  "endpointId": endpoint_id, "tabId": "7",
                                  "page": "https://chatgpt.com/c/abc",
                                  "chatType": "chatgpt", "conversationId": "abc",
                                  "extensionVersion": REQUIRED_EXTENSION_VERSION}})()})()
        asyncio.run(self.console.api_delivery_poll(req2))

    def test_compatible_owner_reaches_delivery(self):
        self.own_and_observe()
        r = self.event(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                       endpointId="ep-1")
        self.assertEqual(r.status, 200)
        self.assertEqual(len(self.moved), 1)

    def test_incompatible_version_cannot_move_delivery_state(self):
        self.own_and_observe()
        r = self.event(extensionVersion="2.11.6", browserEpoch="e1", endpointId="ep-1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "EXTENSION_VERSION_INCOMPATIBLE")
        self.assertEqual(self.moved, [], "delivery state must not have moved")

    def test_foreign_epoch_cannot_move_delivery_state(self):
        self.own_and_observe(epoch="e1")
        r = self.event(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e2",
                       endpointId="ep-1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "CONTROL_AGENT_CONFLICT")
        self.assertEqual(self.moved, [])

    def test_terminal_endpoint_cannot_move_delivery_state(self):
        self.own_and_observe()
        self.console.endpoints.close("ep-1", "e1")
        r = self.event(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                       endpointId="ep-1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "ENDPOINT_TERMINAL")
        self.assertEqual(self.moved, [],
                         "a closed tab cannot have received the delivery it reports on")

    def test_unknown_endpoint_is_refused(self):
        self.own_and_observe()
        r = self.event(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                       endpointId="ep-nope")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "ENDPOINT_UNKNOWN")
        self.assertEqual(self.moved, [])

    def test_missing_epoch_or_endpoint_is_refused(self):
        self.own_and_observe()
        for query, code in [
            (dict(extensionVersion=REQUIRED_EXTENSION_VERSION, endpointId="ep-1"),
             "BROWSER_EPOCH_REQUIRED"),
            (dict(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1"),
             "ENDPOINT_ID_REQUIRED"),
        ]:
            with self.subTest(code=code):
                r = self.event(**query)
                self.assertEqual(json.loads(r.body)["code"], code)
                self.assertEqual(self.moved, [])

    def test_every_browser_route_goes_through_the_barrier(self):
        """A new route that forgets the barrier is the failure mode this guards."""
        src = (CONSOLE / "console_server.py").read_text("utf-8")
        for route in ("api_delivery_poll", "api_delivery_event", "api_delivery_chunk"):
            body = src.split(f"async def {route}(", 1)[1].split("\n    async def", 1)[0]
            self.assertIn("_browser_barrier", body, f"{route} bypasses the barrier")

class ChunkRouteBarriers(unittest.TestCase):
    """Attachment bytes are part of a delivery, so the same barrier applies.

    A structural check that the route calls the barrier is a guard, not proof;
    these show the refusals actually happen and no bytes come back.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        self.reads = []
        self.console.delivery.attachment_chunk = (
            lambda *a, **kw: self.reads.append((a, kw)) or {"bytes": "x"})
        own = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                             "rel_url": type("U", (), {"query": {
                                 "pollKind": "CONTROL_AGENT", "browserEpoch": "e1",
                                 "extensionVersion": REQUIRED_EXTENSION_VERSION}})()})()
        asyncio.run(self.console.api_delivery_poll(own))
        ep = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                            "rel_url": type("U", (), {"query": {
                                "pollKind": "ENDPOINT", "browserEpoch": "e1", "endpointId": "ep-1",
                                "tabId": "7", "page": "https://chatgpt.com/c/abc",
                                "chatType": "chatgpt", "conversationId": "abc",
                                "extensionVersion": REQUIRED_EXTENSION_VERSION}})()})()
        asyncio.run(self.console.api_delivery_poll(ep))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chunk(self, **query):
        class R:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": "r1", "job_id": "j1", "attachment_id": "a1"}
            def __init__(s, q):
                s.rel_url = type("U", (), {"query": q})()
        return asyncio.run(self.console.api_delivery_chunk(
            R({k: str(v) for k, v in query.items() if v is not None})))

    def test_compatible_owner_can_read_with_its_own_tab_and_lease(self):
        r = self.chunk(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                       endpointId="ep-1", offset=0, limit=10, leaseToken="tok")
        self.assertEqual(r.status, 200)
        self.assertEqual(len(self.reads), 1)
        _args, kwargs = self.reads[0]
        # Taken from the validated endpoint, not from anything the client said.
        self.assertEqual(kwargs["tab_id"], 7)
        self.assertEqual(kwargs["lease_token"], "tok")

    def test_barriers_refuse_and_return_no_bytes(self):
        for query, code in [
            (dict(extensionVersion="2.11.6", browserEpoch="e1", endpointId="ep-1"),
             "EXTENSION_VERSION_INCOMPATIBLE"),
            (dict(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e2", endpointId="ep-1"),
             "CONTROL_AGENT_CONFLICT"),
            (dict(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1"),
             "ENDPOINT_ID_REQUIRED"),
            (dict(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                  endpointId="ep-nope"), "ENDPOINT_UNKNOWN"),
        ]:
            with self.subTest(code=code):
                r = self.chunk(**query)
                self.assertEqual(json.loads(r.body)["code"], code)
                self.assertEqual(self.reads, [], "no attachment bytes may be read")

    def test_terminal_endpoint_cannot_read(self):
        self.console.endpoints.close("ep-1", "e1")
        r = self.chunk(extensionVersion=REQUIRED_EXTENSION_VERSION, browserEpoch="e1",
                       endpointId="ep-1")
        self.assertEqual(json.loads(r.body)["code"], "ENDPOINT_TERMINAL")
        self.assertEqual(self.reads, [])

class InvalidRolloutStateBlocksDeliveryPlane(unittest.TestCase):
    """Damaged rollout state must not read as a mode that still permits work."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        self.moved = []
        self.console.delivery.update_from_client = lambda *a, **k: self.moved.append(a) or {"id": "j"}
        for query in ({"pollKind": "CONTROL_AGENT", "browserEpoch": "e1",
                       "extensionVersion": REQUIRED_EXTENSION_VERSION},
                      {"pollKind": "ENDPOINT", "browserEpoch": "e1", "endpointId": "ep-1",
                       "tabId": "7", "page": "https://chatgpt.com/c/abc", "chatType": "chatgpt",
                       "conversationId": "abc", "extensionVersion": REQUIRED_EXTENSION_VERSION}):
            req = type("R", (), {"headers": {"Authorization": "Bearer ctok"},
                                 "rel_url": type("U", (), {"query": query})()})()
            asyncio.run(self.console.api_delivery_poll(req))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unreadable_rollout_state_refuses_delivery_events(self):
        (self.root / "runtime" / "delivery-rollout.json").write_text("{broken", encoding="utf-8")

        class R:
            headers = {"Authorization": "Bearer ctok"}
            match_info = {"run_id": "r1", "job_id": "j1"}
            rel_url = type("U", (), {"query": {
                "extensionVersion": REQUIRED_EXTENSION_VERSION,
                "browserEpoch": "e1", "endpointId": "ep-1"}})()
            async def json(self):
                return {"state": "SENT"}

        r = asyncio.run(self.console.api_delivery_event(R()))
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "DELIVERY_ROLLOUT_STATE_INVALID")
        self.assertEqual(self.moved, [], "delivery state must not move on untrusted rollout state")

