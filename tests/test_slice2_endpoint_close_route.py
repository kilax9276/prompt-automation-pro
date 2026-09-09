# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Slice 2 endpoint-close server bridge for MAP-053.

The extension cannot implement tabs.onRemoved -> CLOSED unless the browser
protocol has a control-owned server operation for it.  These tests use the
real control/observe writers, then exercise only the HTTP handler boundary.
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

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s2")
sys.path.insert(0, str(CONSOLE))

from console_server import ConsoleServer, REQUIRED_EXTENSION_VERSION


class Req:
    def __init__(self, *, auth=True, **query):
        self.headers = {"Authorization": "Bearer ctok"} if auth else {}
        self.rel_url = type("U", (), {"query": {k: str(v) for k, v in query.items() if v is not None}})()


class EndpointCloseRoute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for sub in ("runtime", "data", "config/secrets"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime" / "token.txt").write_text("ctok", encoding="utf-8")
        self.console = ConsoleServer(self.root, self.root / "data", self.root / "runtime" / "token.txt")
        self.own("e1")
        self.observe("e1", "ep-1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def registry_path(self):
        return self.root / "runtime" / "browser-endpoints.json"

    def poll(self, **query):
        return asyncio.run(self.console.api_delivery_poll(Req(**query)))

    def own(self, epoch):
        r = self.poll(pollKind="CONTROL_AGENT", browserEpoch=epoch,
                      extensionVersion=REQUIRED_EXTENSION_VERSION)
        self.assertEqual(r.status, 200)

    def observe(self, epoch, endpoint_id, tab=7):
        r = self.poll(pollKind="ENDPOINT", browserEpoch=epoch, endpointId=endpoint_id,
                      tabId=tab, page="https://chatgpt.com/c/abc", chatType="chatgpt",
                      conversationId="abc", extensionVersion=REQUIRED_EXTENSION_VERSION)
        self.assertEqual(r.status, 200)

    def close(self, epoch="e1", endpoint_id="ep-1", version=REQUIRED_EXTENSION_VERSION, auth=True):
        return asyncio.run(self.console.api_endpoint_close(Req(
            auth=auth, browserEpoch=epoch, endpointId=endpoint_id,
            extensionVersion=version)))

    def state(self, endpoint_id="ep-1"):
        return next(x for x in self.console.endpoints.list()["endpoints"]
                    if x["endpointId"] == endpoint_id)

    def runtime_bytes(self):
        runtime = self.root / "runtime"
        return {p.relative_to(runtime).as_posix(): p.read_bytes()
                for p in runtime.rglob("*") if p.is_file()}

    def expire_control_lease(self):
        body = json.loads(self.registry_path.read_text("utf-8"))
        body["control"]["leaseUntil"] = "2020-01-01T00:00:00Z"
        self.registry_path.write_text(json.dumps(body), encoding="utf-8")

    def test_owner_can_close_its_endpoint(self):
        r = self.close()
        self.assertEqual(r.status, 200)
        body = json.loads(r.body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["endpoint"]["endpointId"], "ep-1")
        self.assertEqual(body["endpoint"]["state"], "CLOSED")
        self.assertEqual(self.state()["state"], "CLOSED")

    def test_foreign_live_epoch_is_refused_before_endpoint_mutation(self):
        before = self.registry_path.read_bytes()
        r = self.close(epoch="e2")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "CONTROL_AGENT_CONFLICT")
        self.assertEqual(self.registry_path.read_bytes(), before)
        self.assertEqual(self.state()["state"], "ONLINE")

    def test_expired_owner_lease_is_not_authority_to_close(self):
        self.expire_control_lease()
        before = self.registry_path.read_bytes()
        r = self.close(epoch="e1")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "NOT_CONTROL_OWNER")
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_closed_is_idempotent_and_second_call_writes_nothing(self):
        self.assertEqual(self.close().status, 200)
        before = self.registry_path.read_bytes()
        second = self.close()
        self.assertEqual(second.status, 200)
        self.assertEqual(json.loads(second.body)["endpoint"]["state"], "CLOSED")
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_expired_endpoint_is_terminal_and_not_rewritten_when_epoch_owns_again(self):
        # Product writers only: e1 owns ep-1; e2 takes over after lease expiry,
        # which EXPIRES ep-1.  Then e1 takes ownership back after e2 expires.
        self.expire_control_lease()
        self.own("e2")
        self.assertEqual(self.state()["state"], "EXPIRED")
        self.expire_control_lease()
        self.own("e1")
        before = self.registry_path.read_bytes()
        r = self.close(epoch="e1")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body)["endpoint"]["state"], "EXPIRED")
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_wrong_version_does_not_write_any_browser_state(self):
        before = self.runtime_bytes()
        r = self.close(version="2.11.7")
        self.assertEqual(r.status, 409)
        self.assertEqual(json.loads(r.body)["code"], "EXTENSION_VERSION_INCOMPATIBLE")
        self.assertEqual(self.state()["state"], "ONLINE")
        self.assertEqual(self.runtime_bytes(), before)

    def test_delivery_barrier_does_not_disable_endpoint_cleanup(self):
        self.console.delivery.begin_drain()
        self.console.delivery.enter_barrier()
        self.assertEqual(self.console.delivery.rollout_state()["mode"], "BARRIER")
        r = self.close()
        self.assertEqual(r.status, 200)
        self.assertEqual(self.state()["state"], "CLOSED")

    def test_browser_auth_is_required(self):
        before = self.registry_path.read_bytes()
        with self.assertRaises(web.HTTPUnauthorized):
            self.close(auth=False)
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_route_is_registered_as_post_and_does_not_use_delivery_job_api(self):
        src = (CONSOLE / "console_server.py").read_text("utf-8")
        self.assertIn('app.router.add_post("/api/endpoints/close", server.api_endpoint_close)', src)
        body = src.split("async def api_endpoint_close(", 1)[1].split("\n    async def", 1)[0]
        self.assertNotIn("update_from_client", body)
        self.assertNotIn("create_job", body)
        self.assertNotIn("request_send", body)
        self.assertIn("_browser_owner_barrier", body)
        self.assertIn("endpoints.close", body)


if __name__ == "__main__":
    unittest.main()
