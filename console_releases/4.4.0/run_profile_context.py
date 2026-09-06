from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat_bindings import ChatBindingsStore
from endpoint_registry import EndpointRegistry, infer_from_page
from profile_resolver import ProfileResolver
from profile_store import ProfileStore, atomic_write_json


class ProfileAuthorizationError(RuntimeError):
    def __init__(self, code: str, message: str | None = None, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.detail = detail or {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunProfileContext:
    def __init__(self, root: Path, data_dir: Path, profiles: ProfileStore, bindings: ChatBindingsStore, endpoints: EndpointRegistry) -> None:
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.profiles = profiles
        self.bindings = bindings
        self.endpoints = endpoints
        self.resolver = ProfileResolver(root, profiles, bindings)

    def run_dir(self, run_id: str) -> Path:
        base = self.data_dir.resolve()
        path = (base / run_id).resolve()
        if path.parent != base:
            raise ProfileAuthorizationError("RUN_INVALID", "invalid run id")
        return path

    def path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "profile-context.json"

    @staticmethod
    def _load_json(path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return default

    @staticmethod
    def _material_key(ctx: dict[str, Any]) -> tuple:
        keys = (
            "resolutionStatus", "blockReason", "profileId", "profileRevision", "profileDigest",
            "bindingId", "role", "chatBindingsRevision", "chatBindingsDigest", "sourceTabId",
            "chatType", "conversationId", "projectId",
        )
        return tuple(json.dumps(ctx.get(k), sort_keys=True, ensure_ascii=False) for k in keys)

    def get(self, run_id: str) -> dict[str, Any]:
        p = self.path(run_id)
        existing = self._load_json(p, {})
        if isinstance(existing, dict) and existing.get("resolutionStatus") == "RESOLVED":
            return existing

        run_dir = self.run_dir(run_id)
        result = self._load_json(run_dir / "result.json", {})
        status = self._load_json(run_dir / "status.json", {})
        if not isinstance(result, dict):
            result = {}
        if not isinstance(status, dict):
            status = {}
        resolved = self.resolver.resolve(result, status)
        ctx = {"schemaVersion": 1, **resolved}
        if ctx.get("resolutionStatus") == "RESOLVED":
            ctx["resolvedAt"] = utc_now()
        else:
            ctx["resolvedAt"] = None

        if not isinstance(existing, dict) or self._material_key(existing) != self._material_key(ctx):
            atomic_write_json(p, ctx, mode=0o640)
        else:
            # Preserve the original file byte-for-byte when repeated blocked resolution has not changed.
            ctx = existing
        return ctx

    def authorize_execution(self, run_id: str) -> dict[str, Any]:
        """Live authorization gate.

        profile-context.json is immutable provenance once RESOLVED: it records
        which profile revision and which binding authorised this Run, and an
        edit to the profile must not move a started Run onto a new revision.

        Authorisation is a different question and is answered fresh on every
        call. Disabling or deleting the binding, disabling the profile, or
        repointing the binding at another profile, role or conversation all
        revoke the right to execute the next step. This mirrors the outgoing
        side, where the delivery target is already resolved live.
        """
        ctx = self.get(run_id)
        status = str(ctx.get("resolutionStatus") or "CHAT_IDENTITY_INVALID")
        if status != "RESOLVED":
            raise ProfileAuthorizationError(status, f"Run blocked by profile authorization: {status}", {"profileContext": ctx})

        def refuse(code: str, message: str) -> None:
            raise ProfileAuthorizationError(code, message, {"profileContext": ctx})

        binding_id = str(ctx.get("bindingId") or "")
        binding = self.bindings.get(binding_id) if binding_id else None
        if binding is None:
            refuse("CHAT_NOT_BOUND", f"binding {binding_id or '<none>'} no longer exists")
        if not bool(binding.get("enabled")):
            refuse("CHAT_DISABLED", f"binding {binding_id} is disabled")

        pinned_profile = str(ctx.get("profileId") or "")
        if str(binding.get("profileId") or "") != pinned_profile:
            refuse(
                "CHAT_BINDING_CHANGED",
                "binding %s now points at profile %s, not %s"
                % (binding_id, binding.get("profileId"), pinned_profile),
            )
        if str(binding.get("role") or "") != str(ctx.get("role") or ""):
            refuse(
                "CHAT_BINDING_CHANGED",
                "binding %s now carries role %s, not %s"
                % (binding_id, binding.get("role"), ctx.get("role")),
            )
        for field in ("chatType", "conversationId", "projectId"):
            pinned = ctx.get(field)
            if pinned in (None, ""):
                continue
            if str(binding.get(field) or "") != str(pinned):
                refuse(
                    "CHAT_BINDING_CHANGED",
                    "binding %s now identifies %s=%s, not %s"
                    % (binding_id, field, binding.get(field), pinned),
                )

        try:
            profile = self.profiles.get_profile(pinned_profile, include_prompts=False)
        except Exception:
            profile = None
        if not isinstance(profile, dict) or not profile:
            refuse("PROFILE_MISSING", f"profile {pinned_profile} no longer exists")
        if not bool(profile.get("enabled", True)):
            refuse("PROFILE_DISABLED", f"profile {pinned_profile} is disabled")

        return ctx

    @staticmethod
    def _target_key(binding: dict[str, Any] | None) -> tuple:
        if not isinstance(binding, dict):
            return tuple()
        return (
            str(binding.get("bindingId") or ""),
            str(binding.get("chatType") or ""),
            str(binding.get("conversationId") or ""),
            str(binding.get("projectId") or ""),
            str(binding.get("profileId") or ""),
            str(binding.get("role") or ""),
        )

    def _resolve_delivery_binding(self, ctx: dict[str, Any], target_role: str | None) -> dict[str, Any]:
        profile_id = str(ctx.get("profileId") or "")
        if target_role:
            rows = self.bindings.bindings_for_role(profile_id, target_role)
            if not rows:
                raise ProfileAuthorizationError("CHAT_NOT_BOUND", f"No enabled binding for role {target_role}")
            if len(rows) > 1:
                raise ProfileAuthorizationError("BINDING_AMBIGUOUS", f"Multiple enabled bindings for role {target_role}", {"bindings": rows})
            current = rows[0]
        else:
            current = self.bindings.get(str(ctx.get("bindingId") or ""))
            if current is None:
                raise ProfileAuthorizationError("CHAT_NOT_BOUND", "Source binding no longer exists")
            if not current.get("enabled"):
                raise ProfileAuthorizationError("CHAT_DISABLED", "Source binding is disabled")
            if str(current.get("profileId") or "") != profile_id:
                raise ProfileAuthorizationError("BINDING_CHANGED_SINCE_RUN", "Binding moved to another profile")

        try:
            profile = self.profiles.get_profile(profile_id, include_prompts=False)
        except Exception:
            raise ProfileAuthorizationError("PROFILE_DISABLED", "Profile is unavailable")
        if not profile.get("enabled"):
            raise ProfileAuthorizationError("PROFILE_DISABLED", "Profile is disabled")

        current_state = self.bindings.state()
        if str(current_state.get("digest") or "") != str(ctx.get("chatBindingsDigest") or ""):
            old_target = ctx.get("bindingTarget") if isinstance(ctx.get("bindingTarget"), dict) else None
            if self._target_key(old_target) != self._target_key(current):
                raise ProfileAuthorizationError(
                    "BINDING_CHANGED_SINCE_RUN",
                    "Delivery binding changed since this Run was resolved",
                    {"oldTarget": old_target, "currentTarget": current},
                )
        return current

    def authorize_delivery(self, run_id: str, target_role: str | None = None, allow_wait: bool = False) -> dict[str, Any]:
        ctx = self.authorize_execution(run_id)
        binding = self._resolve_delivery_binding(ctx, target_role)
        selection = self.endpoints.select_for_binding(binding)
        status = str(selection.get("status") or "WAITING_FOR_ENDPOINT")
        if status == "READY":
            return {"profileContext": ctx, "binding": binding, "endpoint": selection["endpoint"], "selection": selection, "waiting": False}
        if status == "WAITING_FOR_ENDPOINT" and allow_wait:
            try:
                profile = self.profiles.get_profile(str(ctx.get("profileId") or ""), include_prompts=False)
            except Exception:
                raise ProfileAuthorizationError("PROFILE_DISABLED", "Profile is unavailable")
            delivery = profile.get("delivery") if isinstance(profile.get("delivery"), dict) else {}
            if str(delivery.get("offlineTargetPolicy") or "wait") == "fail":
                raise ProfileAuthorizationError("ENDPOINT_OFFLINE", "Target endpoint is offline", {"binding": binding, **selection})
            target_tab = selection.get("pinnedTabId")
            if target_tab in (None, ""):
                target_tab = ctx.get("sourceTabId")
            try:
                target_tab = int(target_tab)
            except Exception:
                raise ProfileAuthorizationError("WAITING_FOR_ENDPOINT", "Target endpoint is offline and no safe tabId is available", {"binding": binding, **selection})
            # A historical tabId is not a durable endpoint identity. Chrome may
            # reuse it for a completely different conversation after a restart.
            # For an offline queued delivery, never inherit URL/identity from
            # whichever endpoint currently happens to have that numeric tabId.
            # The queued target must be anchored to evidence that is already
            # known to belong to THIS binding (runtime pin snapshot or the
            # source Run's page for its own source binding).
            pin_state = self.endpoints.pin_state(str(binding.get("bindingId") or ""))
            safe_url = ""
            if isinstance(pin_state, dict) and int(pin_state.get("tabId") or -1) == target_tab:
                pin_chat = str(pin_state.get("chatType") or "")
                pin_conv = str(pin_state.get("conversationId") or "")
                if pin_chat == str(binding.get("chatType") or "") and pin_conv == str(binding.get("conversationId") or ""):
                    safe_url = str(pin_state.get("url") or "")

            if not safe_url and str(binding.get("bindingId") or "") == str(ctx.get("bindingId") or ""):
                source_page = str(ctx.get("page") or "")
                source_identity = infer_from_page(source_page)
                if (
                    str(source_identity.get("chatType") or "") == str(binding.get("chatType") or "")
                    and str(source_identity.get("conversationId") or "") == str(binding.get("conversationId") or "")
                ):
                    safe_url = source_page

            if not safe_url:
                raise ProfileAuthorizationError(
                    "WAITING_FOR_ENDPOINT",
                    "Target endpoint is offline and no safe URL is available for the queued tab",
                    {"binding": binding, **selection},
                )

            endpoint = {
                "tabId": target_tab,
                "chatType": binding.get("chatType"),
                "conversationId": binding.get("conversationId"),
                "projectId": binding.get("projectId"),
                "url": safe_url,
                "online": False,
            }
            return {
                "profileContext": ctx,
                "binding": binding,
                "endpoint": endpoint,
                "selection": selection,
                "waiting": True,
                "endpointWaitTimeoutSec": int(delivery.get("endpointWaitTimeoutSec") or 3600),
            }
        raise ProfileAuthorizationError(status, status, {"profileContext": ctx, "binding": binding, **selection})
