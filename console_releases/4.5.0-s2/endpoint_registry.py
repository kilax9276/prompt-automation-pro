# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from profile_store import atomic_write_json

ONLINE_GRACE_SECONDS = 6

# Endpoint lifecycle. CLOSED and EXPIRED are terminal for a particular
# endpointId: a heartbeat can race a close event and arrive after it, and
# reviving the endpoint would hand a delivery to a tab that no longer exists.
# A tab that comes back must arrive with a new endpointId.
STATE_ONLINE = "ONLINE"
STATE_OFFLINE = "OFFLINE"
STATE_CLOSED = "CLOSED"
STATE_EXPIRED = "EXPIRED"
TERMINAL_STATES = frozenset({STATE_CLOSED, STATE_EXPIRED})

# Ownership lease. 90 seconds is a term of ownership, not a promise that the
# agent will be heard from that often.
CONTROL_LEASE_SECONDS = 90

# Registry schema. Slice-1 rows are keyed by tabId and carry no endpointId or
# browserEpoch, and that identity cannot be reconstructed — a tab number says
# nothing about which endpoint it was. So the old endpoint space is not
# migrated, it is invalidated at the atomic boundary and rebuilt by the
# extension's first reconciliation.
REGISTRY_SCHEMA_VERSION = 2


class EndpointError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def iso_after(seconds: int) -> str:
    return utc_iso(utc_now() + timedelta(seconds=seconds))


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def infer_from_page(page: str) -> dict[str, Any]:
    raw = str(page or "")
    chat_type = "unknown"
    conversation_id = None
    project_id = None
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        if host == "claude.ai" or host.endswith(".claude.ai"):
            chat_type = "claude"
            m = re.search(r"/chat/([^/?#]+)", path, re.I)
            if m:
                conversation_id = m.group(1)
            pm = re.search(r"/(?:project|projects)/([^/?#]+)", path, re.I)
            if pm:
                project_id = pm.group(1)
        elif host in {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}:
            chat_type = "chatgpt"
            m = re.search(r"/c/([^/?#]+)", path, re.I)
            if m:
                conversation_id = m.group(1)
            pm = re.search(r"/g/(g-p-[^/?#]+)/c/", path, re.I)
            if pm:
                project_id = pm.group(1)
    except Exception:
        pass
    return {
        "chatType": chat_type,
        "conversationId": conversation_id,
        "projectId": project_id,
        "url": raw,
    }


class EndpointRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime_root = self.root / "runtime"
        self.path = self.runtime_root / "browser-endpoints.json"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)

    @staticmethod
    def _empty_registry() -> dict[str, Any]:
        return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "endpoints": [], "control": {}}

    def invalidate_legacy_registry(self, backup_dir: Path | None = None) -> dict[str, Any]:
        """Replace a slice-1 endpoint space with an empty slice-2 one.

        Called by the rollout inside BARRIER, never lazily. The old file is kept
        as rollback evidence rather than deleted: it is the only record of what
        the browser looked like before the boundary, and rollback needs it.
        """
        if not self.path.is_file():
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)
            return {"migrated": False, "reason": "absent", "backup": None}
        # The backup is rollback evidence, so it keeps the original bytes
        # rather than a re-serialised copy: rollback must be able to restore
        # exactly what was there, not something merely equivalent.
        raw_bytes = self.path.read_bytes()
        try:
            body = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            body = {}
        version = body.get("schemaVersion") if isinstance(body, dict) else None
        if version == REGISTRY_SCHEMA_VERSION:
            return {"migrated": False, "reason": "already-current", "backup": None}
        if version != 1:
            # Only a proven slice-1 registry is invalidated. A corrupt or
            # unknown file is not silently replaced by a clean one: that would
            # destroy the only evidence of what went wrong.
            raise EndpointError(
                f"REGISTRY_INVALID: refusing to invalidate a registry of unknown "
                f"schemaVersion {version!r}")
        backup = None
        target_dir = backup_dir or self.runtime_root
        backup = target_dir / f"browser-endpoints.schema{version}.{utc_iso().replace(':', '').replace('-', '')}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw_bytes)
        atomic_write_json(self.path, self._empty_registry(), mode=0o640)
        return {"migrated": True, "fromSchemaVersion": version,
                "discardedEndpoints": len(body.get("endpoints") or []),
                "discardedPins": len(body.get("pins") or {}),
                "backup": str(backup)}

    def _load(self) -> dict[str, Any]:
        # Fail closed on damage as well as on version. Turning an unreadable
        # file into a clean empty registry is the opposite of the boundary just
        # introduced: a known foreign schema would be refused while a corrupt
        # file would be accepted and quietly reset.
        try:
            raw = self.path.read_text("utf-8")
        except FileNotFoundError:
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)
            raw = self.path.read_text("utf-8")
        try:
            body = json.loads(raw)
        except Exception as exc:
            raise EndpointError(f"REGISTRY_INVALID: endpoint registry is not valid JSON: {exc}")
        if not isinstance(body, dict):
            raise EndpointError("REGISTRY_INVALID: endpoint registry root is not an object")
        if "schemaVersion" not in body:
            raise EndpointError("REGISTRY_INVALID: endpoint registry has no schemaVersion")
        version = body["schemaVersion"]
        # No coercion. int("2") and int(2.9) both yield 2, which would let a
        # file that is not schema 2 pass a boundary whose whole purpose is to
        # tell schemas apart.
        if isinstance(version, bool) or not isinstance(version, int):
            raise EndpointError(
                f"REGISTRY_INVALID: schemaVersion must be an integer, got {version!r}")
        if version != REGISTRY_SCHEMA_VERSION:
            # Fail closed. Reading slice-1 rows as slice-2 rows produced ghost
            # endpoints with no identity that selection could still pick up.
            # Trusting the rollout to have replaced the file is not enough: a
            # guarantee nobody checks is the kind that fails quietly.
            raise EndpointError(
                f"REGISTRY_MIGRATION_REQUIRED: endpoint registry is schemaVersion "
                f"{version}, expected {REGISTRY_SCHEMA_VERSION}")
        # Selection policy left the registry; a stray pins block from an older
        # file is not carried forward.
        body.pop("pins", None)
        self._validate_registry(body)
        return body

    @staticmethod
    def _validate_registry(body: dict[str, Any]) -> None:
        """Refuse damage inside a schema-2 file as firmly as a foreign schema.

        Coercing a broken field back to a default is the same fail-open the
        version check was introduced to remove: an endpoint row without
        endpointId or browserEpoch cannot exist in schema 2, and quietly
        turning it into an identity-less ghost is how such a row reached
        selection in the first place.

        Unknown extra fields are tolerated on purpose — a schema that breaks on
        every added field is one nobody dares extend.
        """
        def bad(msg: str) -> None:
            raise EndpointError(f"REGISTRY_INVALID: {msg}")

        def require_ts(container: dict[str, Any], field: str, where: str) -> None:
            """A timestamp must be present and carry an offset.

            A naive timestamp parses happily and then meets utc_now() further
            down, where comparing it raises a bare TypeError from inside
            unrelated code. Refusing it here turns a crash into a stated reason.
            """
            value = container.get(field)
            if not isinstance(value, str) or not value.strip():
                bad(f"{where}.{field} must be a timestamp")
            parsed = parse_utc(value)
            if parsed is None:
                bad(f"{where}.{field} is not a valid timestamp: {value!r}")
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                bad(f"{where}.{field} must carry a timezone offset: {value!r}")

        if not isinstance(body.get("endpoints"), list):
            bad("endpoints must be a list")
        if not isinstance(body.get("control"), dict):
            bad("control must be an object")

        seen: set[str] = set()
        for idx, row in enumerate(body["endpoints"]):
            where = f"endpoints[{idx}]"
            if not isinstance(row, dict):
                bad(f"{where} must be an object")
            for field in ("endpointId", "browserEpoch", "chatType", "conversationId"):
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    bad(f"{where}.{field} must be a non-empty string")
            tab = row.get("tabId")
            if isinstance(tab, bool) or not isinstance(tab, int) or tab < 0:
                bad(f"{where}.tabId must be a non-negative integer")
            state = row.get("state")
            if state not in (STATE_ONLINE, STATE_OFFLINE, STATE_CLOSED, STATE_EXPIRED):
                bad(f"{where}.state is not a known endpoint state: {state!r}")
            require_ts(row, "firstSeenAt", where)
            require_ts(row, "lastSeenAt", where)
            if state in TERMINAL_STATES:
                # Slice-2 code always stamps this when it terminates an
                # endpoint, so its absence means the row was not written by it.
                require_ts(row, "terminatedAt", where)
            key = row["endpointId"].strip()
            if key in seen:
                bad(f"duplicate endpointId {key!r}")
            seen.add(key)

        control = body["control"]
        if control:
            epoch = control.get("browserEpoch")
            if not isinstance(epoch, str) or not epoch.strip():
                bad("control.browserEpoch must be a non-empty string")
            for field in ("acquiredAt", "lastSeenAt", "leaseUntil"):
                require_ts(control, field, "control")

    def _save(self, body: dict[str, Any]) -> None:
        atomic_write_json(self.path, body, mode=0o640)

    def observe(self, tab_id: int, page: str, endpoint_id: str | None = None,
                title: str | None = None, browser_epoch: str | None = None,
                chat_type: str | None = None, conversation_id: str | None = None,
                project_id: str | None = None) -> dict[str, Any]:
        """Record what the browser reports about one endpoint. Facts only.

        Keyed by endpointId rather than tabId: a tab number is reused by the
        browser, so keying by it lets a new tab inherit the identity of a dead
        one. The endpointId is minted by the extension and survives a page
        reload within the same epoch, which is what makes a reload keep its
        delivery target instead of silently acquiring a new one.

        No policy is stored here — no binding, no approval, no staleness. The
        registry answers "what does the browser look like", and selection
        answers "what may be used". Mixing the two is how a stale approval
        became indistinguishable from an absent tab.
        """
        tab_id = int(tab_id)
        if tab_id < 0:
            raise EndpointError("invalid tabId")
        endpoint_key = str(endpoint_id).strip() if endpoint_id else None
        if not endpoint_key:
            raise EndpointError("endpointId is required")
        epoch = str(browser_epoch).strip() if browser_epoch else None
        if not epoch:
            raise EndpointError("browserEpoch is required")
        # The browser states its identity; the URL is kept as a launch hint
        # only. Deriving identity from the URL is what let a reload or a
        # redirect quietly change which chat an endpoint claimed to be.
        stated = {
            "chatType": str(chat_type).strip() if chat_type else None,
            "conversationId": str(conversation_id).strip() if conversation_id else None,
            "projectId": str(project_id).strip() if project_id else None,
        }
        if not stated["chatType"] or not stated["conversationId"]:
            raise EndpointError("chatType and conversationId are required")
        now = utc_iso()
        body = self._load()
        rows = list(body.get("endpoints") or [])
        existing = next((x for x in rows if str(x.get("endpointId") or "") == endpoint_key), None)

        if existing and str(existing.get("state") or "") in TERMINAL_STATES:
            # A late pulse for an endpoint that is already CLOSED or EXPIRED.
            # There is no transition back: returning the row unchanged keeps the
            # race harmless without pretending the tab is alive.
            return self._decorate(dict(existing))
        if existing and str(existing.get("browserEpoch") or "") != epoch:
            raise EndpointError("endpointId belongs to another browserEpoch")
        previous_seen = parse_utc(str((existing or {}).get("lastSeenAt") or ""))
        continuity_broken = bool(previous_seen and (utc_now() - previous_seen).total_seconds() > ONLINE_GRACE_SECONDS)
        # Disconnect telemetry: observation only, never an authorization gate.
        history = [str(x) for x in ((existing or {}).get("disconnects") or []) if x]
        if continuity_broken:
            history.append(now)
        cutoff = utc_now() - timedelta(hours=24)
        history = [x for x in history if (parse_utc(x) or utc_now()) >= cutoff][-200:]
        gap_seconds = None
        if continuity_broken and previous_seen:
            gap_seconds = round((utc_now() - previous_seen).total_seconds(), 1)
        row = {
            "disconnects": history,
            "disconnects24h": len(history),
            "lastDisconnectAt": history[-1] if history else (existing or {}).get("lastDisconnectAt"),
            "lastGapSeconds": gap_seconds if gap_seconds is not None else (existing or {}).get("lastGapSeconds"),
            "tabId": tab_id,
            "endpointId": endpoint_key,
            "browserEpoch": epoch,
            "state": STATE_ONLINE,
            "chatType": stated["chatType"],
            "conversationId": stated["conversationId"],
            "projectId": stated["projectId"],
            # Stored, never used to decide identity.
            "url": str(page or "") or None,
            "title": str(title).strip() if title else (existing or {}).get("title"),
            "firstSeenAt": (existing or {}).get("firstSeenAt") if not continuity_broken else now,
            "lastSeenAt": now,
        }
        if not row["firstSeenAt"]:
            row["firstSeenAt"] = now
        replaced = False
        for idx, item in enumerate(rows):
            if str(item.get("endpointId") or "") == endpoint_key:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        rows.sort(key=lambda x: str(x.get("endpointId") or ""))
        body["endpoints"] = rows
        self._save(body)
        return self._decorate(row)


    # ---- control ownership ------------------------------------------------
    #
    # One control agent per browser epoch, held by a lease. Showing a conflict
    # is not enough: if both epochs receive a reconciliation plan we merely
    # observe the conflict and still end up with two competing reconcilers, so
    # the loser gets no plan and changes nothing.
    #
    # Ownership follows a real change of owner, not any lease gap: an epoch
    # that reappears before anyone took over reacquires its own endpoints
    # rather than minting new identities for them.

    def control_state(self) -> dict[str, Any]:
        body = self._load()
        control = body.get("control") if isinstance(body.get("control"), dict) else {}
        until = parse_utc(str(control.get("leaseUntil") or ""))
        return {"browserEpoch": control.get("browserEpoch"),
                "acquiredAt": control.get("acquiredAt"),
                "lastSeenAt": control.get("lastSeenAt"),
                "leaseUntil": control.get("leaseUntil"),
                "leaseLive": bool(until and until > utc_now())}

    def acquire_control(self, browser_epoch: str) -> dict[str, Any]:
        """Acquire, renew or refuse control for an epoch.

        Refusal is a value, not an exception: the caller must be able to answer
        CONTROL_AGENT_CONFLICT without the refusal itself having written
        anything.

        Takeover is a single write. Marking the new owner first and expiring the
        previous endpoints second leaves, if the process dies between them, a
        new owner holding live endpoints of an epoch that no longer exists.
        """
        epoch = str(browser_epoch or "").strip()
        if not epoch:
            raise EndpointError("browserEpoch is required")
        body = self._load()
        control = body.get("control") if isinstance(body.get("control"), dict) else {}
        current = str(control.get("browserEpoch") or "")
        until = parse_utc(str(control.get("leaseUntil") or ""))
        now = utc_now()
        lease_live = bool(until and until > now)

        if current and current != epoch and lease_live:
            return {"owner": False, "conflict": True, "browserEpoch": epoch,
                    "heldBy": current, "leaseUntil": control.get("leaseUntil"),
                    "transferred": False, "expiredEndpoints": []}

        now_iso = utc_iso()
        lease_until = iso_after(CONTROL_LEASE_SECONDS)
        takeover = bool(current and current != epoch)
        rows = list(body.get("endpoints") or [])
        expired: list[str] = []
        if takeover:
            for idx, item in enumerate(rows):
                if str(item.get("browserEpoch") or "") == epoch:
                    continue
                if str(item.get("state") or "") in TERMINAL_STATES:
                    continue
                row = dict(item)
                row["state"] = STATE_EXPIRED
                row["terminatedAt"] = now_iso
                rows[idx] = row
                expired.append(str(row.get("endpointId") or ""))
            body["endpoints"] = rows

        body["control"] = {
            "browserEpoch": epoch,
            "acquiredAt": now_iso if (takeover or not current) else (control.get("acquiredAt") or now_iso),
            "lastSeenAt": now_iso,
            "leaseUntil": lease_until,
        }
        # One save: owner and expiries commit together or not at all.
        self._save(body)
        return {"owner": True, "conflict": False, "browserEpoch": epoch,
                "leaseUntil": lease_until, "transferred": takeover,
                "reacquired": bool(current == epoch and not lease_live),
                "expiredEndpoints": expired}

    def control_check(self, browser_epoch: str) -> dict[str, Any]:
        """Answer whether this epoch may act, without writing anything."""
        epoch = str(browser_epoch or "").strip()
        state = self.control_state()
        current = str(state.get("browserEpoch") or "")
        if not epoch or not current:
            return {"owner": False, "conflict": False}
        if current == epoch:
            return {"owner": bool(state["leaseLive"]), "conflict": False}
        # A foreign epoch while the owner's lease is alive is a conflict, not a
        # plain "not owner": the two answers point the operator at different
        # problems.
        return {"owner": False, "conflict": bool(state["leaseLive"]), "heldBy": current}

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """Derive presence from the last heartbeat. Terminal states never move."""
        out = dict(row)
        seen = parse_utc(str(row.get("lastSeenAt") or ""))
        age = (utc_now() - seen).total_seconds() if seen else 10**9
        stored = str(row.get("state") or "")
        if stored in TERMINAL_STATES:
            out["state"] = stored
        else:
            out["state"] = STATE_ONLINE if age <= ONLINE_GRACE_SECONDS else STATE_OFFLINE
        out["online"] = out["state"] == STATE_ONLINE
        out["ageSeconds"] = max(0.0, age) if age < 10**8 else None
        return out

    def close(self, endpoint_id: str, browser_epoch: str) -> dict[str, Any]:
        """The tab is gone. Terminal, and only for its own epoch."""
        return self._terminate(endpoint_id, browser_epoch, STATE_CLOSED)

    def expire_epoch(self, browser_epoch: str) -> list[str]:
        """A new browser epoch strands every endpoint of the previous one.

        Expiry follows a real change of owner, not any lease gap: a flapping
        lease under the same owner must not force new identities, because that
        would rebuild delivery targets for no reason.
        """
        body = self._load()
        rows = list(body.get("endpoints") or [])
        expired = []
        for idx, item in enumerate(rows):
            if str(item.get("browserEpoch") or "") == str(browser_epoch):
                continue
            if str(item.get("state") or "") in TERMINAL_STATES:
                continue
            row = dict(item)
            row["state"] = STATE_EXPIRED
            row["terminatedAt"] = utc_iso()
            rows[idx] = row
            expired.append(str(row.get("endpointId") or ""))
        if expired:
            body["endpoints"] = rows
            self._save(body)
        return expired

    def _terminate(self, endpoint_id: str, browser_epoch: str, state: str) -> dict[str, Any]:
        key = str(endpoint_id).strip()
        body = self._load()
        rows = list(body.get("endpoints") or [])
        for idx, item in enumerate(rows):
            if str(item.get("endpointId") or "") != key:
                continue
            if str(item.get("browserEpoch") or "") != str(browser_epoch):
                raise EndpointError("endpointId belongs to another browserEpoch")
            row = dict(item)
            if str(row.get("state") or "") in TERMINAL_STATES:
                return self._decorate(row)
            row["state"] = state
            row["terminatedAt"] = utc_iso()
            rows[idx] = row
            body["endpoints"] = rows
            self._save(body)
            return self._decorate(row)
        raise EndpointError("endpoint not found")

    def list(self) -> dict[str, Any]:
        """Observed browser state only.

        Selection policy is not returned here. OFFLINE endpoints are included:
        hiding them is a UI filter, and a server that hides them makes an absent
        tab and a policy decision look the same to every caller.
        """
        body = self._load()
        endpoints = [self._decorate(dict(x)) for x in body.get("endpoints") or []]
        order = {STATE_ONLINE: 0, STATE_OFFLINE: 1, STATE_CLOSED: 2, STATE_EXPIRED: 3}
        endpoints.sort(key=lambda x: (order.get(str(x.get("state")), 9), str(x.get("endpointId") or "")))
        return {"schemaVersion": 2, "onlineGraceSeconds": ONLINE_GRACE_SECONDS,
                "endpoints": endpoints}

    def endpoints_for_binding(self, binding: dict[str, Any], online_only: bool = True) -> list[dict[str, Any]]:
        rows = []
        for ep in self.list()["endpoints"]:
            if str(ep.get("chatType")) != str(binding.get("chatType")):
                continue
            if str(ep.get("conversationId") or "") != str(binding.get("conversationId") or ""):
                continue
            bp = str(binding.get("projectId") or "")
            ep_project = str(ep.get("projectId") or "")
            if bp and ep_project and bp != ep_project:
                continue
            if online_only and not ep.get("online"):
                continue
            rows.append(ep)
        return rows

    # pin/unpin removed in slice 2.
    #
    # Selection stopped being a property written onto an endpoint: it is a
    # relation between a session and a binding, established by selectEndpoint.
    # There is deliberately no way left to *create* a pin. pin_state and
    # pinned_tab survive only as read-side tails for callers that have not moved
    # yet; after the schema-2 invalidation there is physically nothing for them
    # to read, and they disappear with the selection rewrite.

    def pin_state(self, binding_id: str) -> dict[str, Any] | None:
        value = self._load().get("pins", {}).get(str(binding_id))
        if value is None:
            return None
        if isinstance(value, dict):
            try:
                return {**value, "tabId": int(value.get("tabId"))}
            except Exception:
                return None
        try:
            return {"tabId": int(value), "stale": False}
        except Exception:
            return None

    def pinned_tab(self, binding_id: str) -> int | None:
        pin = self.pin_state(binding_id)
        return int(pin["tabId"]) if pin else None

    def select_for_binding(self, binding: dict[str, Any]) -> dict[str, Any]:
        if str(binding.get("endpointPolicy") or "conversation") == "approved_endpoint":
            approved = str(binding.get("approvedEndpointId") or "")
            if not approved:
                return {"status": "ENDPOINT_NOT_APPROVED", "endpoint": None, "candidates": []}
            candidates = [x for x in self.endpoints_for_binding(binding, online_only=True) if str(x.get("endpointId") or "") == approved]
            if not candidates:
                return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": []}
            return {"status": "READY", "endpoint": candidates[0], "candidates": candidates}

        candidates = self.endpoints_for_binding(binding, online_only=True)
        pin = self.pin_state(str(binding.get("bindingId") or ""))
        if pin is not None:
            pinned = int(pin["tabId"])
            if pin.get("stale"):
                return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": candidates, "pinned": True, "pinnedTabId": pinned, "pinStale": True, "pinState": pin}
            chosen = next((x for x in candidates if int(x.get("tabId") or -1) == pinned), None)
            if chosen is not None:
                return {"status": "READY", "endpoint": chosen, "candidates": candidates, "pinned": True}
            return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": candidates, "pinned": True, "pinnedTabId": pinned}
        if not candidates:
            return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": []}
        if len(candidates) > 1:
            return {"status": "ENDPOINT_AMBIGUOUS", "endpoint": None, "candidates": candidates}
        return {"status": "READY", "endpoint": candidates[0], "candidates": candidates}
