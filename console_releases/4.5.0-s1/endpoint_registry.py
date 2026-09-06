# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from profile_store import atomic_write_json

ONLINE_GRACE_SECONDS = 6


class EndpointError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


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
            atomic_write_json(self.path, {"schemaVersion": 1, "endpoints": [], "pins": {}}, mode=0o640)

    def _load(self) -> dict[str, Any]:
        try:
            body = json.loads(self.path.read_text("utf-8"))
        except Exception:
            body = {"schemaVersion": 1, "endpoints": [], "pins": {}}
        if not isinstance(body, dict):
            body = {"schemaVersion": 1, "endpoints": [], "pins": {}}
        body.setdefault("schemaVersion", 1)
        body.setdefault("endpoints", [])
        body.setdefault("pins", {})
        if not isinstance(body["endpoints"], list):
            body["endpoints"] = []
        if not isinstance(body["pins"], dict):
            body["pins"] = {}
        return body

    def _save(self, body: dict[str, Any]) -> None:
        atomic_write_json(self.path, body, mode=0o640)

    def observe(self, tab_id: int, page: str, endpoint_id: str | None = None, title: str | None = None) -> dict[str, Any]:
        tab_id = int(tab_id)
        if tab_id < 0:
            raise EndpointError("invalid tabId")
        inferred = infer_from_page(page)
        now = utc_iso()
        body = self._load()
        rows = list(body.get("endpoints") or [])
        existing = next((x for x in rows if int(x.get("tabId", -999999)) == tab_id), None)
        previous_seen = parse_utc(str((existing or {}).get("lastSeenAt") or ""))
        continuity_broken = bool(previous_seen and (utc_now() - previous_seen).total_seconds() > ONLINE_GRACE_SECONDS)
        # A runtime pin is only valid while the observed tab remains the same
        # conversation. This check is independent of the heartbeat grace so a
        # fast Chrome restart/tabId reuse cannot redirect a pin to another chat.
        for binding_id, pin in list((body.get("pins") or {}).items()):
            pin_tab = pin.get("tabId") if isinstance(pin, dict) else pin
            try:
                same_tab = int(pin_tab) == tab_id
            except Exception:
                same_tab = False
            if not same_tab:
                continue
            if not isinstance(pin, dict):
                pin = {"tabId": tab_id}
            pin = dict(pin)
            identity_changed = bool(
                (pin.get("chatType") and str(pin.get("chatType")) != str(inferred.get("chatType") or ""))
                or (pin.get("conversationId") and str(pin.get("conversationId")) != str(inferred.get("conversationId") or ""))
                or (pin.get("endpointId") and endpoint_id and str(pin.get("endpointId")) != str(endpoint_id))
            )
            # Only a changed conversation invalidates a pin. A heartbeat gap
            # means the very same chat went away and came back: delivery is
            # still addressed to the right conversation, so it resumes on its
            # own. Requiring an operator click there stopped real work for no
            # safety gain, while tabId reuse is caught by the identity check
            # regardless of how long the tab was silent.
            if identity_changed:
                pin["stale"] = True
                pin["staleReason"] = "tab identity changed; delivery is paused until this is resolved"
                pin["staleAt"] = now
                body.setdefault("pins", {})[binding_id] = pin
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
            "endpointId": str(endpoint_id).strip() if endpoint_id else None,
            "chatType": inferred["chatType"],
            "conversationId": inferred["conversationId"],
            "projectId": inferred["projectId"],
            "url": inferred["url"],
            "title": str(title).strip() if title else (existing or {}).get("title"),
            "firstSeenAt": (existing or {}).get("firstSeenAt") if not continuity_broken else now,
            "lastSeenAt": now,
        }
        if not row["firstSeenAt"]:
            row["firstSeenAt"] = now
        replaced = False
        for idx, item in enumerate(rows):
            if int(item.get("tabId", -999999)) == tab_id:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        rows.sort(key=lambda x: int(x.get("tabId") or 0))
        body["endpoints"] = rows
        self._save(body)
        return self._decorate(row)

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        seen = parse_utc(str(row.get("lastSeenAt") or ""))
        age = (utc_now() - seen).total_seconds() if seen else 10**9
        out["online"] = age <= ONLINE_GRACE_SECONDS
        out["ageSeconds"] = max(0.0, age) if age < 10**8 else None
        return out

    def list(self) -> dict[str, Any]:
        body = self._load()
        endpoints = [self._decorate(dict(x)) for x in body.get("endpoints") or []]
        endpoints.sort(key=lambda x: (not bool(x.get("online")), int(x.get("tabId") or 0)))
        return {"schemaVersion": 1, "onlineGraceSeconds": ONLINE_GRACE_SECONDS, "endpoints": endpoints, "pins": dict(body.get("pins") or {})}

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

    def pin(self, binding_id: str, tab_id: int) -> dict[str, Any]:
        body = self._load()
        tab_id = int(tab_id)
        ep = next((self._decorate(dict(x)) for x in body.get("endpoints") or [] if int(x.get("tabId", -1)) == tab_id), None)
        if ep is None:
            raise EndpointError("endpoint not found")
        body.setdefault("pins", {})[str(binding_id)] = {
            "tabId": tab_id,
            "stale": False,
            "pinnedAt": utc_iso(),
            "conversationId": ep.get("conversationId"),
            "chatType": ep.get("chatType"),
            "projectId": ep.get("projectId"),
            "url": ep.get("url"),
            "endpointId": ep.get("endpointId"),
        }
        self._save(body)
        return ep

    def unpin(self, binding_id: str) -> None:
        body = self._load()
        body.setdefault("pins", {}).pop(str(binding_id), None)
        self._save(body)

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
