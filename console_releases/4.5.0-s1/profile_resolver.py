from __future__ import annotations

from pathlib import Path
from typing import Any

from chat_bindings import ChatBindingsStore
from endpoint_registry import infer_from_page
from profile_store import ProfileError, ProfileStore


class ProfileResolver:
    def __init__(self, root: Path, profiles: ProfileStore, bindings: ChatBindingsStore) -> None:
        self.root = root.resolve()
        self.profiles = profiles
        self.bindings = bindings

    @staticmethod
    def identity_from_result(result: dict[str, Any], status: dict[str, Any] | None = None) -> dict[str, Any]:
        status = status or {}
        page = str(result.get("page") or status.get("page") or "")
        inferred = infer_from_page(page)
        chat_type = str(result.get("chatType") or status.get("chatType") or inferred.get("chatType") or "").strip().lower()
        conversation = str(result.get("chatConversationId") or status.get("chatConversationId") or inferred.get("conversationId") or "").strip()
        project_id = str(inferred.get("projectId") or "").strip() or None
        pap_source = result.get("papSource") if isinstance(result.get("papSource"), dict) else {}
        tab_id = pap_source.get("tabId")
        try:
            tab_id = int(tab_id) if tab_id not in (None, "") else None
        except Exception:
            tab_id = None
        return {
            "chatType": chat_type,
            "conversationId": conversation,
            "projectId": project_id,
            "sourceTabId": tab_id,
            "page": page,
        }

    def resolve(self, result: dict[str, Any], status: dict[str, Any] | None = None) -> dict[str, Any]:
        identity = self.identity_from_result(result, status)
        if identity["chatType"] not in {"claude", "chatgpt"} or not identity["conversationId"]:
            return {"resolutionStatus": "CHAT_IDENTITY_INVALID", "blockReason": "CHAT_IDENTITY_INVALID", **identity}

        binding = self.bindings.find_for_chat(identity["chatType"], identity["conversationId"])
        if binding is None:
            return {"resolutionStatus": "CHAT_NOT_BOUND", "blockReason": "CHAT_NOT_BOUND", **identity}
        if not binding.get("enabled"):
            return {"resolutionStatus": "CHAT_DISABLED", "blockReason": "CHAT_DISABLED", "bindingId": binding.get("bindingId"), **identity}

        try:
            profile = self.profiles.get_profile(str(binding.get("profileId") or ""), include_prompts=False)
        except ProfileError:
            return {
                "resolutionStatus": "PROFILE_DISABLED",
                "blockReason": "PROFILE_DISABLED",
                "bindingId": binding.get("bindingId"),
                "profileId": binding.get("profileId"),
                **identity,
            }
        if not profile.get("enabled"):
            return {
                "resolutionStatus": "PROFILE_DISABLED",
                "blockReason": "PROFILE_DISABLED",
                "bindingId": binding.get("bindingId"),
                "profileId": profile.get("id"),
                **identity,
            }

        policy = str(binding.get("endpointPolicy") or "conversation")
        if policy == "approved_endpoint":
            # Not enabled in 4.4.0; source endpoint has no stable endpointId yet.
            return {
                "resolutionStatus": "ENDPOINT_NOT_APPROVED",
                "blockReason": "ENDPOINT_NOT_APPROVED",
                "bindingId": binding.get("bindingId"),
                "profileId": profile.get("id"),
                **identity,
            }

        state = self.bindings.state()
        return {
            "resolutionStatus": "RESOLVED",
            "blockReason": None,
            "profileId": profile.get("id"),
            "profileRevision": profile.get("revision"),
            "profileDigest": profile.get("digest"),
            "bindingId": binding.get("bindingId"),
            "role": binding.get("role"),
            "chatBindingsRevision": state.get("revision"),
            "chatBindingsDigest": state.get("digest"),
            "bindingTarget": {
                "bindingId": binding.get("bindingId"),
                "chatType": binding.get("chatType"),
                "conversationId": binding.get("conversationId"),
                "projectId": binding.get("projectId"),
                "profileId": binding.get("profileId"),
                "role": binding.get("role"),
            },
            **identity,
        }
