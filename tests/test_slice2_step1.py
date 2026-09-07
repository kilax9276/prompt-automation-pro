# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import asyncio
import hashlib
import http.client
import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from yarl import URL

import os
import sys

ROOT = Path(__file__).resolve().parents[1]
# Releases are versioned directories; the slice under test is selected here so
# the suite cannot silently exercise the previous release.
CONSOLE = ROOT / "console_releases" / os.environ.get("PAP_CONSOLE_RELEASE", "4.5.0-s2")
RECEIVER = ROOT / "receivers" / os.environ.get("PAP_RECEIVER_RELEASE", "2.11.0-s1") / "server.py"
if not CONSOLE.is_dir():
    raise SystemExit(f"console release directory not found: {CONSOLE}")
if not RECEIVER.is_file():
    raise SystemExit(f"receiver release not found: {RECEIVER}")
sys.path.insert(0, str(CONSOLE))

from chat_bindings import ChatBindingsStore
from console_server import ConsoleServer
from profile_store import ProfileError, ProfileActivationStore, ProfileSessionStore, ProfileSnapshotStore, ProfileStore
from run_profile_context import ProfileAuthorizationError

spec = importlib.util.spec_from_file_location("pap2_receiver", RECEIVER)
receiver = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(receiver)


def profile_body(profile_id: str, name: str | None = None) -> dict:
    role = "source"
    return {
        "id": profile_id,
        "name": name or profile_id,
        "enabled": True,
        "paths": {"workDir": "/tmp/pap2", "tempDir": "/tmp/pap2"},
        "variables": {"MODE": "slice1"},
        "secretRefs": {"API": f"{profile_id}-secret"},
        "roles": {role: {"promptPath": f"prompts/roles/{role}.md", "basePromptRequired": True}},
        "delivery": {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 3600},
        "directives": {"COMMAND_TEST": {"kind": "baseline"}},
        "errorDetection": {"enabled": True, "disabledBuiltins": [], "customSignatures": []},
        "promptTexts": {"base": f"BASE {profile_id}", "roles": {role: f"ROLE {profile_id}"}},
    }


class ReceiverHarness:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.server = receiver.ReceiverServer(("127.0.0.1", 0), receiver.Handler, self.data, "tok")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post_json(self, path: str, body: dict):
        raw = json.dumps(body).encode("utf-8")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=raw, headers={
            "Authorization": "Bearer tok",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        })
        r = c.getresponse()
        payload = json.loads(r.read().decode("utf-8"))
        status = r.status
        c.close()
        return status, payload

    def upload_legacy(self, intake_id: str, name: str, data: bytes):
        digest = hashlib.sha256(data).hexdigest()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/chat-file", body=data, headers={
            "Authorization": "Bearer tok",
            "Content-Length": str(len(data)),
            "X-Run-Id": intake_id,
            "X-File-Name": name,
            "X-File-Sha256": digest,
            "X-File-Mime": "application/octet-stream",
        })
        r = c.getresponse()
        payload = json.loads(r.read().decode("utf-8"))
        status = r.status
        c.close()
        return status, payload


class Slice2Step1TimeoutRename(unittest.TestCase):
    """Step 1 of slice 2: endpointWaitTimeoutSec -> endpointWaitTimeoutSeconds.

    Independent of the endpoint/epoch model and of the extension: the whole step
    touches only the console and its UI.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "config" / "secrets").mkdir(parents=True)
        (self.root / "config" / "secrets" / "p1-secret").write_text("S", encoding="utf-8")
        self.profiles = ProfileStore(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fresh(self):
        # ProfileStore creates its staging directory on construction, so the
        # store is rebuilt rather than left pointing at a removed tree.
        shutil.rmtree(self.root / "config" / "profiles", ignore_errors=True)
        self.profiles = ProfileStore(self.root)

    def save(self, delivery):
        body = profile_body("p1")
        body["delivery"] = delivery
        return self.profiles.save_profile(body, actor="t", create=True)

    def stored(self):
        return self.profiles.get_profile("p1", include_prompts=False)["delivery"]

    def test_five_states_decided_by_membership(self):
        for label, delivery, expected in [
            ("both absent", {"offlineTargetPolicy": "wait"}, 3600),
            ("legacy only", {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 900}, 900),
            ("canonical only", {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSeconds": 120}, 120),
            ("both agree", {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 300,
                            "endpointWaitTimeoutSeconds": 300}, 300),
        ]:
            with self.subTest(state=label):
                self.fresh(); self.save(delivery)
                got = self.stored()
                self.assertEqual(got["endpointWaitTimeoutSeconds"], expected)
                self.assertNotIn("endpointWaitTimeoutSec", got)
        self.fresh()
        with self.assertRaises(ProfileError) as cm:
            self.save({"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 300,
                       "endpointWaitTimeoutSeconds": 400})
        self.assertIn("disagree", str(cm.exception))

    def test_explicit_falsy_is_rejected_not_defaulted(self):
        for key in ("endpointWaitTimeoutSec", "endpointWaitTimeoutSeconds"):
            for value in (0, False, "", None):
                with self.subTest(key=key, value=value):
                    self.fresh()
                    with self.assertRaises(ProfileError) as cm:
                        self.save({"offlineTargetPolicy": "wait", key: value})
                    msg = str(cm.exception)
                    self.assertIn("endpointWaitTimeoutSeconds", msg)
                    # Rejected on its merits, never quietly replaced by the
                    # default the operator did not choose.
                    self.assertTrue("must be >=" in msg or "must be an integer" in msg, msg)

    def test_range_bounds_named_canonically(self):
        self.fresh()
        with self.assertRaises(ProfileError) as low:
            self.save({"offlineTargetPolicy": "wait", "endpointWaitTimeoutSeconds": 14})
        self.assertIn("endpointWaitTimeoutSeconds must be >= 15", str(low.exception))
        self.fresh()
        with self.assertRaises(ProfileError) as high:
            self.save({"offlineTargetPolicy": "wait", "endpointWaitTimeoutSeconds": 604801})
        self.assertIn("endpointWaitTimeoutSeconds is too large", str(high.exception))
        for bound in (15, 604800):
            self.fresh(); self.save({"offlineTargetPolicy": "wait", "endpointWaitTimeoutSeconds": bound})
            self.assertEqual(self.stored()["endpointWaitTimeoutSeconds"], bound)

    def test_snapshot_freezes_only_the_canonical_name(self):
        self.fresh(); self.save({"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": 777})
        snaps = ProfileSnapshotStore(self.root, self.profiles)
        pub = snaps.publish_current("p1")
        raw = (snaps.path(pub["snapshotDigest"]) / "snapshot.json").read_text("utf-8")
        self.assertIn("endpointWaitTimeoutSeconds", raw)
        self.assertNotIn('"endpointWaitTimeoutSec"', raw)

    def test_authorization_and_console_use_the_canonical_name(self):
        ctx_src = (CONSOLE / "run_profile_context.py").read_text("utf-8")
        self.assertIn('"endpointWaitTimeoutSeconds": int(', ctx_src)
        self.assertNotIn('delivery.get("endpointWaitTimeoutSec")', ctx_src)
        srv_src = (CONSOLE / "console_server.py").read_text("utf-8")
        self.assertIn('authorization.get("endpointWaitTimeoutSeconds")', srv_src)
        self.assertNotIn('authorization.get("endpointWaitTimeoutSec")', srv_src)

    def test_ui_has_no_legacy_key_on_any_path(self):
        js = (CONSOLE / "static" / "app.js").read_text("utf-8")
        for bad in ("endpointWaitTimeoutSec:", ".endpointWaitTimeoutSec ", "endpointWaitTimeoutSec |"):
            self.assertNotIn(bad, js)
        self.assertEqual(js.count("endpointWaitTimeoutSeconds"), 3)
        self.assertIn("endpointWaitTimeoutSeconds:3600", js)
        self.assertIn("p.delivery?.endpointWaitTimeoutSeconds ?? 3600", js)


class Slice2Step1PersistedMigration(unittest.TestCase):
    """The contract is about migrating configuration that already exists.

    Creating a profile through the new code proves the input API accepts the
    legacy key. It does not prove that a profile written by slice 1 and sitting
    on disk can still be read — and it could not: get_profile normalises in
    memory and then compares the result against the digest stored for the old
    bytes, so a genuine slice-1 profile failed to load at all.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "config" / "secrets").mkdir(parents=True)
        (self.root / "config" / "secrets" / "p1-secret").write_text("S", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_slice1_profile(self, timeout=777, profile_id="p1"):
        """Write a profile with the slice-1 code, exactly as the stand has it."""
        s1_dir = ROOT / "console_releases" / "4.5.0-s1"
        spec = importlib.util.spec_from_file_location("s1_profile_store", s1_dir / "profile_store.py")
        s1 = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(s1_dir))
        try:
            spec.loader.exec_module(s1)
        finally:
            sys.path.remove(str(s1_dir))
        body = profile_body(profile_id)
        body["delivery"] = {"offlineTargetPolicy": "wait", "endpointWaitTimeoutSec": timeout}
        s1.ProfileStore(self.root).save_profile(body, actor="t", create=True)
        return json.loads((self.root / "config" / "profiles" / profile_id / "profile.json").read_text("utf-8"))

    def test_persisted_slice1_profile_migrates_and_then_loads(self):
        before = self.write_slice1_profile(777)
        self.assertIn("endpointWaitTimeoutSec", before["delivery"])

        store = ProfileStore(self.root)
        # Before migration the profile is unreadable — this is the defect, and
        # asserting it keeps the migration from being quietly removed later.
        with self.assertRaises(ProfileError):
            store.get_profile("p1", include_prompts=False)

        report = store.migrate_persisted_profiles(actor="rollout")
        self.assertEqual(report["failed"], [])
        self.assertTrue(report["committed"])
        self.assertEqual(len(report["migrated"]), 1)
        self.assertEqual(report["migrated"][0]["from"], 777)
        self.assertEqual(report["migrated"][0]["to"], 777)
        self.assertNotEqual(report["migrated"][0]["digestBefore"],
                            report["migrated"][0]["digestAfter"])

        delivery = store.get_profile("p1", include_prompts=False)["delivery"]
        self.assertEqual(delivery["endpointWaitTimeoutSeconds"], 777)
        self.assertNotIn("endpointWaitTimeoutSec", delivery)
        on_disk = json.loads((self.root / "config" / "profiles" / "p1" / "profile.json").read_text("utf-8"))
        self.assertNotIn("endpointWaitTimeoutSec", on_disk["delivery"])

    def test_migration_is_idempotent(self):
        self.write_slice1_profile(600)
        store = ProfileStore(self.root)
        store.migrate_persisted_profiles(actor="rollout")
        again = store.migrate_persisted_profiles(actor="rollout")
        self.assertEqual(again["migrated"], [])
        self.assertEqual(again["alreadyCanonical"], ["p1"])
        self.assertEqual(again["failed"], [])

    def test_corrupt_profile_is_reported_not_rewritten(self):
        """A profile that was already broken must not be laundered into a valid one."""
        self.write_slice1_profile(400)
        path = self.root / "config" / "profiles" / "p1" / "profile.json"
        body = json.loads(path.read_text("utf-8"))
        body["variables"]["MODE"] = "tampered"
        path.write_text(json.dumps(body), encoding="utf-8")

        store = ProfileStore(self.root)
        report = store.migrate_persisted_profiles(actor="rollout")
        self.assertEqual(report["migrated"], [])
        self.assertFalse(report["committed"])
        self.assertEqual(len(report["failed"]), 1)
        self.assertIn("pre-migration digest mismatch", report["failed"][0]["error"])
        still = json.loads(path.read_text("utf-8"))
        self.assertIn("endpointWaitTimeoutSec", still["delivery"])

    def test_authorization_emits_only_the_canonical_name(self):
        """ACC-MIG-015/016 behaviourally, not by grepping source."""
        self.write_slice1_profile(1234)
        store = ProfileStore(self.root)
        store.migrate_persisted_profiles(actor="rollout")
        snaps = ProfileSnapshotStore(self.root, store)
        published = snaps.publish_current("p1")
        snapshot = json.loads((snaps.path(published["snapshotDigest"]) / "snapshot.json").read_text("utf-8"))
        self.assertEqual(snapshot["delivery"]["endpointWaitTimeoutSeconds"], 1234)
        self.assertNotIn("endpointWaitTimeoutSec", snapshot["delivery"])

    def test_set_with_one_bad_profile_writes_nothing(self):
        """A known fault anywhere in the set means zero writes."""
        self.write_slice1_profile(500, "p1")
        (self.root / "config" / "secrets" / "p2-secret").write_text("S", encoding="utf-8")
        self.write_slice1_profile(500, "p2")
        bad = self.root / "config" / "profiles" / "p2" / "profile.json"
        body = json.loads(bad.read_text("utf-8"))
        body["variables"]["MODE"] = "tampered"
        bad.write_text(json.dumps(body), encoding="utf-8")

        store = ProfileStore(self.root)
        report = store.migrate_persisted_profiles(actor="rollout")
        self.assertFalse(report["committed"])
        self.assertEqual(report["migrated"], [])
        self.assertEqual([f["profileId"] for f in report["failed"]], ["p2"])
        for pid in ("p1", "p2"):
            on_disk = json.loads((self.root / "config" / "profiles" / pid / "profile.json").read_text("utf-8"))
            self.assertIn("endpointWaitTimeoutSec", on_disk["delivery"],
                          f"{pid} must not have been rewritten")

    def test_damaged_canonical_profile_is_failed_not_skipped(self):
        """Canonical-only is verified, not waved through."""
        self.write_slice1_profile(400)
        store = ProfileStore(self.root)
        self.assertTrue(store.migrate_persisted_profiles(actor="rollout")["committed"])
        path = self.root / "config" / "profiles" / "p1" / "profile.json"
        body = json.loads(path.read_text("utf-8"))
        body["variables"]["MODE"] = "tampered"
        path.write_text(json.dumps(body), encoding="utf-8")

        report = ProfileStore(self.root).migrate_persisted_profiles(actor="rollout")
        self.assertEqual(report["alreadyCanonical"], [])
        self.assertEqual([f["profileId"] for f in report["failed"]], ["p1"])
        with self.assertRaises(ProfileError):
            ProfileStore(self.root).get_profile("p1", include_prompts=False)

    def test_persisted_profile_without_either_key_gets_the_default(self):
        self.write_slice1_profile(600)
        path = self.root / "config" / "profiles" / "p1" / "profile.json"
        body = json.loads(path.read_text("utf-8"))
        body["delivery"] = {"offlineTargetPolicy": "wait"}
        # Re-stamp the digest so the fixture is a valid profile that simply has
        # neither key, rather than a corrupt one.
        store = ProfileStore(self.root)
        prompts = store._prompt_texts("p1", body)
        body["digest"] = ""
        body["digest"] = store._profile_digest(body, prompts)
        path.write_text(json.dumps(body), encoding="utf-8")

        report = ProfileStore(self.root).migrate_persisted_profiles(actor="rollout")
        self.assertEqual(report["failed"], [])
        self.assertTrue(report["committed"])
        self.assertEqual(report["migrated"][0]["state"], "absent")
        self.assertEqual(report["migrated"][0]["to"], 3600)
        delivery = ProfileStore(self.root).get_profile("p1", include_prompts=False)["delivery"]
        self.assertEqual(delivery["endpointWaitTimeoutSeconds"], 3600)

    def test_preflight_only_mode_writes_nothing(self):
        self.write_slice1_profile(888)
        store = ProfileStore(self.root)
        report = store.migrate_persisted_profiles(actor="rollout", commit=False)
        self.assertFalse(report["committed"])
        self.assertEqual(report["migrated"], [])
        self.assertEqual(report["planned"][0]["to"], 888)
        on_disk = json.loads((self.root / "config" / "profiles" / "p1" / "profile.json").read_text("utf-8"))
        self.assertIn("endpointWaitTimeoutSec", on_disk["delivery"])

