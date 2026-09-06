# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from profile_store import ConfigHistory, ProfileError, ProfileStore, atomic_write_json, canonical_json_bytes, sha256_prefixed

BINDING_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ChatBindingError(ValueError):
    pass


class ChatBindingsStore:
    def __init__(self, root: Path, profiles: ProfileStore) -> None:
        self.root = root.resolve()
        self.config_root = self.root / "config"
        self.path = self.config_root / "chat-bindings.json"
        self.profiles = profiles
        self.history = ConfigHistory(self.config_root)
        self.config_root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"schemaVersion": 1, "revision": 0, "digest": "", "bindings": []})

    def _load(self) -> dict[str, Any]:
        try:
            body = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            body = {"schemaVersion": 1, "revision": 0, "digest": "", "bindings": []}
        except Exception as exc:
            raise ChatBindingError(f"invalid chat-bindings.json: {exc}") from exc
        if not isinstance(body, dict) or int(body.get("schemaVersion") or 0) != 1 or not isinstance(body.get("bindings"), list):
            raise ChatBindingError("invalid chat-bindings schema")
        stored = str(body.get("digest") or "")
        computed = self._digest(body)
        if not stored.startswith("sha256:") or stored != computed:
            raise ChatBindingError(f"chat-bindings digest mismatch: stored={stored or 'MISSING'} computed={computed}")
        return body

    def _digest(self, body: dict[str, Any]) -> str:
        material = {k: v for k, v in body.items() if k != "digest"}
        return sha256_prefixed(canonical_json_bytes(material))

    def _write(self, body: dict[str, Any]) -> dict[str, Any]:
        out = dict(body)
        out["schemaVersion"] = 1
        out["digest"] = ""
        out["digest"] = self._digest(out)
        atomic_write_json(self.path, out, mode=0o640)
        return out

    def state(self) -> dict[str, Any]:
        return self._load()

    def list(self) -> list[dict[str, Any]]:
        return list(self._load().get("bindings") or [])

    def get(self, binding_id: str) -> dict[str, Any] | None:
        for row in self.list():
            if str(row.get("bindingId")) == str(binding_id):
                return dict(row)
        return None

    def _validate(self, binding: dict[str, Any], current_id: str | None = None) -> dict[str, Any]:
        if not isinstance(binding, dict):
            raise ChatBindingError("binding must be an object")
        binding_id = str(binding.get("bindingId") or "").strip()
        if not BINDING_ID_RE.fullmatch(binding_id):
            raise ChatBindingError("invalid bindingId")
        if current_id is not None and binding_id != current_id:
            raise ChatBindingError("bindingId cannot be changed")
        name = str(binding.get("name") or "").strip()
        if not name:
            raise ChatBindingError("binding name is required")
        chat_type = re.sub(r"[^a-z0-9_-]+", "-", str(binding.get("chatType") or "").strip().lower()).strip("-")
        if chat_type not in {"claude", "chatgpt"}:
            raise ChatBindingError("chatType must be claude or chatgpt")
        conversation_id = str(binding.get("conversationId") or "").strip()
        if not conversation_id:
            raise ChatBindingError("conversationId is required")
        project_id = str(binding.get("projectId") or "").strip() or None
        profile_id = str(binding.get("profileId") or "").strip()
        role = str(binding.get("role") or "").strip()
        try:
            profile = self.profiles.get_profile(profile_id, include_prompts=False)
        except ProfileError as exc:
            raise ChatBindingError(str(exc)) from exc
        if role not in (profile.get("roles") or {}):
            raise ChatBindingError("role does not exist in selected profile")
        policy = str(binding.get("endpointPolicy") or "conversation")
        if policy not in {"conversation", "approved_endpoint"}:
            raise ChatBindingError("invalid endpointPolicy")
        approved = binding.get("approvedEndpointId")
        approved = str(approved).strip() if approved not in (None, "") else None
        if policy == "approved_endpoint":
            # Schema-reserved only in 4.4.0. Persistent endpoint identity does not exist yet.
            raise ChatBindingError("approved_endpoint is reserved until the extension provides persistent endpointId")
        return {
            "bindingId": binding_id,
            "name": name,
            "chatType": chat_type,
            "conversationId": conversation_id,
            "projectId": project_id,
            "profileId": profile_id,
            "role": role,
            "enabled": bool(binding.get("enabled", True)),
            "endpointPolicy": policy,
            "approvedEndpointId": approved,
        }

    def _assert_unique_identity(self, rows: list[dict[str, Any]], candidate: dict[str, Any], current_id: str | None = None) -> None:
        key = (candidate["chatType"], candidate["conversationId"])
        for row in rows:
            if current_id is not None and str(row.get("bindingId")) == current_id:
                continue
            if (str(row.get("chatType")), str(row.get("conversationId"))) == key:
                raise ChatBindingError("this chat conversation is already bound")

    def create(self, binding: dict[str, Any], actor: str) -> dict[str, Any]:
        state = self._load()
        rows = list(state.get("bindings") or [])
        candidate = self._validate(binding)
        if any(str(x.get("bindingId")) == candidate["bindingId"] for x in rows):
            raise ChatBindingError("bindingId already exists")
        self._assert_unique_identity(rows, candidate)
        rows.append(candidate)
        rows.sort(key=lambda x: str(x.get("bindingId")))
        state["bindings"] = rows
        state["revision"] = int(state.get("revision") or 0) + 1
        written = self._write(state)
        self.history.append(actor, "chat-binding", candidate["bindingId"], "create", None, candidate)
        return {"binding": candidate, "revision": written["revision"], "digest": written["digest"]}

    def update(self, binding_id: str, binding: dict[str, Any], actor: str) -> dict[str, Any]:
        state = self._load()
        rows = list(state.get("bindings") or [])
        old = next((dict(x) for x in rows if str(x.get("bindingId")) == binding_id), None)
        if old is None:
            raise ChatBindingError("binding not found")
        merged = dict(old)
        merged.update(binding or {})
        merged["bindingId"] = binding_id
        candidate = self._validate(merged, current_id=binding_id)
        self._assert_unique_identity(rows, candidate, current_id=binding_id)
        rows = [candidate if str(x.get("bindingId")) == binding_id else x for x in rows]
        rows.sort(key=lambda x: str(x.get("bindingId")))
        state["bindings"] = rows
        state["revision"] = int(state.get("revision") or 0) + 1
        written = self._write(state)
        self.history.append(actor, "chat-binding", binding_id, "update", old, candidate)
        return {"binding": candidate, "revision": written["revision"], "digest": written["digest"]}

    def delete(self, binding_id: str, actor: str) -> None:
        state = self._load()
        rows = list(state.get("bindings") or [])
        old = next((dict(x) for x in rows if str(x.get("bindingId")) == binding_id), None)
        if old is None:
            raise ChatBindingError("binding not found")
        state["bindings"] = [x for x in rows if str(x.get("bindingId")) != binding_id]
        state["revision"] = int(state.get("revision") or 0) + 1
        self._write(state)
        self.history.append(actor, "chat-binding", binding_id, "delete", old, None)

    def count_for_profile(self, profile_id: str) -> int:
        return sum(1 for x in self.list() if str(x.get("profileId")) == profile_id)

    def find_for_chat(self, chat_type: str, conversation_id: str) -> dict[str, Any] | None:
        for row in self.list():
            if str(row.get("chatType")) == str(chat_type) and str(row.get("conversationId")) == str(conversation_id):
                return dict(row)
        return None

    def bindings_for_role(self, profile_id: str, role: str) -> list[dict[str, Any]]:
        rows = [
            dict(x) for x in self.list()
            if str(x.get("profileId")) == str(profile_id)
            and str(x.get("role")) == str(role)
            and bool(x.get("enabled"))
        ]
        rows.sort(key=lambda x: str(x.get("bindingId")))
        return rows
