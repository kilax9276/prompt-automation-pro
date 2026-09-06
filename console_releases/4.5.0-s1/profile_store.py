# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_error_detector import ERROR_SIGNATURES

PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ROLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CLAIM_LEASE_SECONDS = 15


class ProfileError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode if mode is not None else 0o644)
    try:
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, value: Any, mode: int | None = None) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n", mode=mode)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory_tree(root: Path) -> None:
    dirs = [root] + [x for x in root.rglob("*") if x.is_dir() and not x.is_symlink()]
    dirs.sort(key=lambda x: len(x.parts), reverse=True)
    for directory in dirs:
        _fsync_dir(directory)


def _exchange_directories(stage: Path, target: Path) -> None:
    """Atomically exchange two existing directories on Linux.

    The deployed platform is Linux. RENAME_EXCHANGE gives us a real commit
    point for a multi-file profile: readers see either the complete old
    directory or the complete new one, never a mixture of prompt/profile bytes.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise ProfileError("atomic profile update requires renameat2(RENAME_EXCHANGE)")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_exchange = 2
    rc = renameat2(at_fdcwd, os.fsencode(stage), at_fdcwd, os.fsencode(target), rename_exchange)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"{stage} <-> {target}")


class ConfigHistory:
    def __init__(self, config_root: Path) -> None:
        self.path = config_root / "config-history.ndjson"

    def append(self, actor: str, kind: str, object_id: str, action: str, before: Any, after: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "at": utc_now(),
            "actor": str(actor or "unknown"),
            "kind": kind,
            "objectId": object_id,
            "action": action,
            "before": before,
            "after": after,
        }
        raw = canonical_json_bytes(row) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)

    def list(self, limit: int = 300) -> list[dict[str, Any]]:
        limit = min(2000, max(1, int(limit or 300)))
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text("utf-8", errors="replace").splitlines()[-limit:]:
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        rows.reverse()
        return rows


ALLOWED_PATH_ROOTS = ("/tmp/", "/home/ext_disk/")


def _check_contained_path(label: str, value: Any) -> str:
    """Reject anything outside the roots this installation may touch.

    workDir becomes the working directory for executed commands and tempDir
    receives delivered files, so an unconstrained value here turns into an
    execution path later. Normalisation happens before the check so that
    /tmp/pap2/../../etc cannot slip through.
    """
    text = str(value or "").strip()
    if not text.startswith("/"):
        raise ProfileError(f"{label} must be an absolute path")
    normalised = os.path.normpath(text)
    if not any(
        normalised == root.rstrip("/") or normalised.startswith(root)
        for root in ALLOWED_PATH_ROOTS
    ):
        raise ProfileError(
            f"{label} must stay inside " + " or ".join(ALLOWED_PATH_ROOTS)
        )
    return normalised


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.config_root = self.root / "config"
        self.profiles_root = self.config_root / "profiles"
        self.profile_staging_root = self.profiles_root / ".staging"
        self.secrets_root = self.config_root / "secrets"
        self.history = ConfigHistory(self.config_root)
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        self.profile_staging_root.mkdir(parents=True, exist_ok=True)
        # Anything left here is from a process/system interruption either before
        # or after the atomic exchange. The authoritative profile directory is
        # always profiles/<id>; staging remnants are never read.
        for leftover in list(self.profile_staging_root.iterdir()):
            try:
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover)
                else:
                    leftover.unlink()
            except FileNotFoundError:
                pass
        self.secrets_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.secrets_root, 0o700)
        except OSError:
            pass

    def profile_dir(self, profile_id: str) -> Path:
        self._validate_profile_id(profile_id)
        path = (self.profiles_root / profile_id).resolve()
        if path.parent != self.profiles_root.resolve():
            raise ProfileError("invalid profile id")
        return path

    def profile_path(self, profile_id: str) -> Path:
        return self.profile_dir(profile_id) / "profile.json"

    @staticmethod
    def _validate_profile_id(profile_id: str) -> None:
        if not PROFILE_ID_RE.fullmatch(str(profile_id or "")):
            raise ProfileError("profile id must match [a-z0-9][a-z0-9._-]{0,63}")

    def _load_json(self, path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text("utf-8"))
        except FileNotFoundError:
            return default
        except Exception as exc:
            raise ProfileError(f"invalid JSON in {path}: {exc}") from exc

    def _prompt_texts(self, profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        pdir = self.profile_dir(profile_id)
        base = ""
        prompts = profile.get("prompts") if isinstance(profile.get("prompts"), dict) else {}
        base_spec = prompts.get("base") if isinstance(prompts.get("base"), dict) else {}
        if base_spec.get("source") == "file" and base_spec.get("path"):
            p = (pdir / str(base_spec["path"])).resolve()
            if pdir not in p.parents:
                raise ProfileError("base prompt path escapes profile directory")
            if p.is_file():
                base = p.read_text("utf-8", errors="strict")
        roles_text: dict[str, str] = {}
        for role, spec in (profile.get("roles") or {}).items():
            if not isinstance(spec, dict):
                continue
            rel = str(spec.get("promptPath") or "")
            if not rel:
                roles_text[str(role)] = ""
                continue
            p = (pdir / rel).resolve()
            if pdir not in p.parents:
                raise ProfileError(f"role prompt path escapes profile directory: {role}")
            roles_text[str(role)] = p.read_text("utf-8", errors="strict") if p.is_file() else ""
        return {"base": base, "roles": roles_text}

    def _profile_digest(self, profile_without_digest: dict[str, Any], prompt_texts: dict[str, Any]) -> str:
        material = {
            "profile": {k: v for k, v in profile_without_digest.items() if k != "digest"},
            "promptTexts": prompt_texts,
        }
        return sha256_prefixed(canonical_json_bytes(material))

    def _validate_profile(self, body: dict[str, Any], expected_id: str | None = None) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ProfileError("profile must be an object")
        profile_id = str(body.get("id") or "").strip()
        self._validate_profile_id(profile_id)
        if expected_id is not None and profile_id != expected_id:
            raise ProfileError("profile id does not match URL")
        if int(body.get("schemaVersion") or 1) != 1:
            raise ProfileError("unsupported profile schemaVersion")
        name = str(body.get("name") or "").strip()
        if not name:
            raise ProfileError("profile name is required")

        paths = body.get("paths") if isinstance(body.get("paths"), dict) else {}
        work_dir = _check_contained_path("workDir", paths.get("workDir"))
        temp_dir = _check_contained_path("tempDir", paths.get("tempDir"))

        variables = body.get("variables") if isinstance(body.get("variables"), dict) else {}
        for key in variables:
            if not VAR_NAME_RE.fullmatch(str(key)):
                raise ProfileError(f"invalid variable name: {key}")
        secret_refs = body.get("secretRefs") if isinstance(body.get("secretRefs"), dict) else {}
        for ref_name, secret_id in secret_refs.items():
            if not ROLE_ID_RE.fullmatch(str(ref_name)):
                raise ProfileError(f"invalid secret reference name: {ref_name}")
            if not PROFILE_ID_RE.fullmatch(str(secret_id)):
                raise ProfileError(f"invalid secret id: {secret_id}")
        prompts = body.get("prompts") if isinstance(body.get("prompts"), dict) else {}
        roles = body.get("roles") if isinstance(body.get("roles"), dict) else {}
        if not roles:
            raise ProfileError("profile must define at least one role")
        normalized_roles: dict[str, dict[str, Any]] = {}
        for role, spec in roles.items():
            role = str(role)
            if not ROLE_ID_RE.fullmatch(role):
                raise ProfileError(f"invalid role id: {role}")
            if not isinstance(spec, dict):
                raise ProfileError(f"role {role} must be an object")
            prompt_path = str(spec.get("promptPath") or f"prompts/roles/{role}.md")
            pp = Path(prompt_path)
            if pp.is_absolute() or ".." in pp.parts:
                raise ProfileError(f"invalid promptPath for role {role}")
            normalized_roles[role] = {
                "promptPath": prompt_path,
                "basePromptRequired": bool(spec.get("basePromptRequired", False)),
            }

        base_spec = prompts.get("base") if isinstance(prompts.get("base"), dict) else {}
        base_path = str(base_spec.get("path") or "prompts/base.md")
        bp = Path(base_path)
        if bp.is_absolute() or ".." in bp.parts:
            raise ProfileError("invalid base prompt path")
        prompt_paths = [base_path] + [str(spec.get("promptPath") or "") for spec in normalized_roles.values()]
        if len(prompt_paths) != len(set(prompt_paths)):
            raise ProfileError("base and role prompt paths must be unique")

        delivery = body.get("delivery") if isinstance(body.get("delivery"), dict) else {}
        offline_policy = str(delivery.get("offlineTargetPolicy") or "wait")
        if offline_policy not in {"wait", "fail"}:
            raise ProfileError("offlineTargetPolicy must be wait or fail")
        timeout = int(delivery.get("endpointWaitTimeoutSec") or 3600)
        if timeout < CLAIM_LEASE_SECONDS:
            raise ProfileError(f"endpointWaitTimeoutSec must be >= {CLAIM_LEASE_SECONDS}")
        if timeout > 7 * 24 * 3600:
            raise ProfileError("endpointWaitTimeoutSec is too large")

        error_detection = body.get("errorDetection") if isinstance(body.get("errorDetection"), dict) else {}
        disabled_builtins = error_detection.get("disabledBuiltins") if isinstance(error_detection.get("disabledBuiltins"), list) else []
        custom = error_detection.get("customSignatures") if isinstance(error_detection.get("customSignatures"), list) else []
        normalized_custom: list[dict[str, Any]] = []
        for idx, item in enumerate(custom):
            if isinstance(item, str):
                item = {"name": f"custom-{idx+1}", "pattern": item, "flags": "i"}
            if not isinstance(item, dict):
                raise ProfileError("customSignatures items must be objects or strings")
            pattern = str(item.get("pattern") or "")
            if not pattern:
                raise ProfileError("custom signature pattern is required")
            try:
                flags = re.I if "i" in str(item.get("flags") or "i") else 0
                re.compile(pattern, flags)
            except re.error as exc:
                raise ProfileError(f"invalid custom signature regex: {exc}") from exc
            normalized_custom.append({
                "name": str(item.get("name") or f"custom-{idx+1}"),
                "pattern": pattern,
                "flags": str(item.get("flags") or "i"),
                "enabled": bool(item.get("enabled", True)),
            })

        directives = body.get("directives") if isinstance(body.get("directives"), dict) else {}
        for key in directives:
            if not str(key).startswith("COMMAND_"):
                raise ProfileError(f"directive key must start with COMMAND_: {key}")

        normalized = {
            "schemaVersion": 1,
            "id": profile_id,
            "name": name,
            "enabled": bool(body.get("enabled", True)),
            "revision": int(body.get("revision") or 0),
            "digest": str(body.get("digest") or ""),
            "paths": {"workDir": work_dir, "tempDir": temp_dir},
            "variables": {str(k): str(v) for k, v in variables.items()},
            "secretRefs": {str(k): str(v) for k, v in secret_refs.items()},
            "prompts": {"base": {"source": "file", "path": base_path}},
            "roles": normalized_roles,
            "delivery": {"offlineTargetPolicy": offline_policy, "endpointWaitTimeoutSec": timeout},
            "directives": directives,
            "errorDetection": {
                "enabled": bool(error_detection.get("enabled", True)),
                "disabledBuiltins": [str(x) for x in disabled_builtins],
                "customSignatures": normalized_custom,
            },
        }
        return normalized

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = []
        if not self.profiles_root.is_dir():
            return rows
        for p in sorted(self.profiles_root.iterdir(), key=lambda x: x.name):
            if p == self.profile_staging_root:
                continue
            if not p.is_dir() or not (p / "profile.json").is_file():
                continue
            try:
                profile = self.get_profile(p.name, include_prompts=False)
                rows.append(profile)
            except Exception as exc:
                rows.append({"id": p.name, "name": p.name, "enabled": False, "invalid": True, "error": str(exc)})
        return rows

    def get_profile(self, profile_id: str, include_prompts: bool = True) -> dict[str, Any]:
        path = self.profile_path(profile_id)
        body = self._load_json(path)
        if not isinstance(body, dict):
            raise ProfileError("profile not found")
        profile = self._validate_profile(body, expected_id=profile_id)
        prompt_texts = self._prompt_texts(profile_id, profile)
        stored_digest = str(profile.get("digest") or "")
        if not stored_digest.startswith("sha256:"):
            raise ProfileError("profile digest is missing")
        computed = self._profile_digest(profile, prompt_texts)
        if computed != stored_digest:
            raise ProfileError(f"profile digest mismatch: stored={stored_digest} computed={computed}")
        result = dict(profile)
        if include_prompts:
            result["promptTexts"] = prompt_texts
        result["secretMetadata"] = self.secret_metadata(profile)
        return result

    def save_profile(self, body: dict[str, Any], actor: str, expected_id: str | None = None, create: bool = False) -> dict[str, Any]:
        incoming = dict(body or {})
        prompt_texts = incoming.pop("promptTexts", None)
        incoming.pop("secretMetadata", None)
        normalized = self._validate_profile(incoming, expected_id=expected_id)
        profile_id = normalized["id"]
        path = self.profile_path(profile_id)
        exists = path.is_file()
        if create and exists:
            raise ProfileError("profile already exists")
        if not create and expected_id is not None and not exists:
            raise ProfileError("profile not found")

        before = None
        old_rev = 0
        if exists:
            before = self.get_profile(profile_id, include_prompts=True)
            old_rev = int(before.get("revision") or 0)

        if prompt_texts is None:
            prompt_texts = before.get("promptTexts") if isinstance(before, dict) else {"base": "", "roles": {}}
        if not isinstance(prompt_texts, dict):
            raise ProfileError("promptTexts must be an object")
        base_text = str(prompt_texts.get("base") or "")
        role_texts = prompt_texts.get("roles") if isinstance(prompt_texts.get("roles"), dict) else {}

        normalized["revision"] = old_rev + 1
        normalized["digest"] = ""
        normalized_prompt_texts = {
            "base": base_text,
            "roles": {role: str(role_texts.get(role) or "") for role in normalized["roles"]},
        }
        normalized["digest"] = self._profile_digest(normalized, normalized_prompt_texts)

        pdir = self.profile_dir(profile_id)
        stage = self.profile_staging_root / (profile_id + ".save-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o750)
        committed = False
        try:
            base_path = stage / normalized["prompts"]["base"]["path"]
            atomic_write_bytes(base_path, base_text.encode("utf-8"), mode=0o640)
            for role, spec in normalized["roles"].items():
                role_path = stage / spec["promptPath"]
                atomic_write_bytes(role_path, normalized_prompt_texts["roles"][role].encode("utf-8"), mode=0o640)
            atomic_write_json(stage / "profile.json", normalized, mode=0o640)
            _fsync_directory_tree(stage)

            if pdir.exists():
                _exchange_directories(stage, pdir)
                # stage now contains the complete old profile directory.
                _fsync_dir(self.profiles_root)
                _fsync_dir(self.profile_staging_root)
                committed = True
                shutil.rmtree(stage)
                _fsync_dir(self.profile_staging_root)
            else:
                os.rename(stage, pdir)
                _fsync_dir(self.profiles_root)
                _fsync_dir(self.profile_staging_root)
                committed = True
        finally:
            if not committed and stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

        after = self.get_profile(profile_id, include_prompts=True)
        self.history.append(actor, "profile", profile_id, "create" if not exists else "update", before, self._redact_for_history(after))
        return after

    def delete_profile(self, profile_id: str, actor: str, binding_count: int = 0) -> None:
        if binding_count:
            raise ProfileError("profile has chat bindings")
        pdir = self.profile_dir(profile_id)
        if not pdir.is_dir():
            raise ProfileError("profile not found")
        before = self.get_profile(profile_id, include_prompts=True)
        # Profiles contain only configuration/prompt files. Secrets are external and never deleted here.
        tombstone = self.profile_staging_root / (profile_id + ".delete-" + uuid.uuid4().hex)
        os.rename(pdir, tombstone)
        _fsync_dir(self.profiles_root)
        try:
            shutil.rmtree(tombstone)
            _fsync_dir(self.profile_staging_root)
        finally:
            # If cleanup fails, the authoritative profile is already atomically
            # absent; a hidden staging remnant is ignored and cleaned on restart.
            pass
        self.history.append(actor, "profile", profile_id, "delete", self._redact_for_history(before), None)

    def _redact_for_history(self, profile: Any) -> Any:
        if not isinstance(profile, dict):
            return profile
        out = dict(profile)
        out.pop("secretMetadata", None)
        return out

    def secret_metadata(self, profile: dict[str, Any]) -> dict[str, Any]:
        rows: dict[str, Any] = {}
        for name, secret_id in (profile.get("secretRefs") or {}).items():
            sid = str(secret_id)
            if not PROFILE_ID_RE.fullmatch(sid):
                rows[str(name)] = {"secretId": sid, "configured": False, "invalidRef": True}
                continue
            path = self.secrets_root / sid
            if path.is_file():
                data = path.read_bytes()
                rows[str(name)] = {
                    "secretId": sid,
                    "configured": True,
                    "length": len(data),
                    "fingerprint": hashlib.sha256(data).hexdigest()[:12],
                }
            else:
                rows[str(name)] = {"secretId": sid, "configured": False, "length": 0, "fingerprint": None}
        return rows

    def set_secret(self, profile_id: str, name: str, value: str, actor: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id, include_prompts=False)
        refs = profile.get("secretRefs") or {}
        if name not in refs:
            raise ProfileError("secret name is not referenced by profile")
        secret_id = str(refs[name])
        if not PROFILE_ID_RE.fullmatch(secret_id):
            raise ProfileError("invalid secret id")
        data = str(value).encode("utf-8")
        path = self.secrets_root / secret_id
        before_meta = self.secret_metadata(profile).get(name)
        atomic_write_bytes(path, data, mode=0o600)
        after_meta = self.secret_metadata(profile).get(name)
        self.history.append(actor, "secret", f"{profile_id}:{name}", "replace", before_meta, after_meta)
        return after_meta

    def test_error_signatures(self, profile_id: str, text: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id, include_prompts=False)
        cfg = profile.get("errorDetection") or {}
        matches = []
        source = str(text or "")
        if cfg.get("enabled"):
            disabled = {str(x) for x in cfg.get("disabledBuiltins") or []}
            for signature in ERROR_SIGNATURES:
                if signature.signature_id in disabled:
                    continue
                m = signature.pattern.search(source)
                if m:
                    matches.append({
                        "kind": "builtin",
                        "id": signature.signature_id,
                        "name": signature.signature_id,
                        "description": signature.description,
                        "pattern": signature.pattern.pattern,
                        "match": m.group(0)[:500],
                    })
            for item in cfg.get("customSignatures") or []:
                if not item.get("enabled", True):
                    continue
                flags = re.I if "i" in str(item.get("flags") or "") else 0
                m = re.search(str(item.get("pattern") or ""), source, flags)
                if m:
                    matches.append({
                        "kind": "custom",
                        "name": item.get("name"),
                        "pattern": item.get("pattern"),
                        "match": m.group(0)[:500],
                    })
        return {"enabled": bool(cfg.get("enabled")), "matches": matches, "matchCount": len(matches)}


class ProfileSnapshotStore:
    """Content-addressed, immutable profile snapshots for sessions and Runs."""

    def __init__(self, root: Path, profiles: ProfileStore) -> None:
        self.root = root.resolve()
        self.profiles = profiles
        self.storage_root = self.root / "storage" / "profile-snapshots"
        self.staging_root = self.storage_root / ".staging"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        for leftover in list(self.staging_root.iterdir()):
            try:
                if leftover.is_dir() and not leftover.is_symlink():
                    shutil.rmtree(leftover)
                else:
                    leftover.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _snapshot_digest(files: dict[str, bytes]) -> str:
        h = hashlib.sha256()
        for rel in sorted(files):
            raw_name = rel.encode("utf-8")
            raw = files[rel]
            h.update(len(raw_name).to_bytes(4, "big"))
            h.update(raw_name)
            h.update(len(raw).to_bytes(8, "big"))
            h.update(raw)
        return "sha256:" + h.hexdigest()

    @staticmethod
    def _snapshot_name(snapshot_digest: str) -> str:
        value = str(snapshot_digest or "")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
            raise ProfileError("invalid snapshot digest")
        return value

    def path(self, snapshot_digest: str) -> Path:
        path = (self.storage_root / self._snapshot_name(snapshot_digest)).resolve()
        if path.parent != self.storage_root.resolve():
            raise ProfileError("invalid snapshot path")
        return path

    def _source_files(self, source_dir: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
        published = not (source_dir / "profile.json").is_file() and (source_dir / "snapshot.json").is_file()
        profile_path = source_dir / ("snapshot.json" if published else "profile.json")
        raw_profile = profile_path.read_bytes()
        profile = json.loads(raw_profile.decode("utf-8"))
        if not isinstance(profile, dict):
            raise ProfileError("snapshot profile must be an object")
        profile_id = str(profile.get("id") or "")
        ProfileStore._validate_profile_id(profile_id)
        files: dict[str, bytes] = {"snapshot.json": raw_profile}
        prompts = profile.get("prompts") if isinstance(profile.get("prompts"), dict) else {}
        base = prompts.get("base") if isinstance(prompts.get("base"), dict) else {}
        base_rel = str(base.get("path") or "prompts/base.md")
        base_path = (source_dir / ("prompts/base.md" if published else base_rel)).resolve()
        if source_dir.resolve() not in base_path.parents or not base_path.is_file():
            raise ProfileError("snapshot base prompt missing")
        files["prompts/base.md"] = base_path.read_bytes()
        for role, spec in sorted((profile.get("roles") or {}).items(), key=lambda kv: str(kv[0])):
            if not isinstance(spec, dict):
                raise ProfileError(f"invalid role {role}")
            rel = str(spec.get("promptPath") or f"prompts/roles/{role}.md")
            src = (source_dir / (f"prompts/roles/{role}.md" if published else rel)).resolve()
            if source_dir.resolve() not in src.parents or not src.is_file():
                raise ProfileError(f"snapshot role prompt missing: {role}")
            files[f"prompts/roles/{role}.md"] = src.read_bytes()
        return files, profile

    def _publish_files(self, files: dict[str, bytes], profile: dict[str, Any]) -> dict[str, Any]:
        # Profile files contain secret references only. Refuse the presentation-only
        # secretMetadata field defensively so a future caller cannot persist it.
        if "secretMetadata" in profile or "promptTexts" in profile:
            raise ProfileError("snapshot source contains presentation-only profile data")
        digest = self._snapshot_digest(files)
        target = self.path(digest)
        if not target.exists():
            stage = self.staging_root / ("snapshot-" + uuid.uuid4().hex)
            stage.mkdir(mode=0o750)
            committed = False
            try:
                for rel, raw in files.items():
                    atomic_write_bytes(stage / rel, raw, mode=0o640)
                _fsync_directory_tree(stage)
                try:
                    os.rename(stage, target)
                    _fsync_dir(self.storage_root)
                    committed = True
                except FileExistsError:
                    committed = True
            finally:
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=True)
        verify_files, verify_profile = self._source_files(target)
        if self._snapshot_digest(verify_files) != digest:
            raise ProfileError("published snapshot verification failed")
        return {
            "snapshotDigest": digest,
            "profileId": str(verify_profile.get("id") or ""),
            "profileRevision": int(verify_profile.get("revision") or 0),
            "profileDigest": str(verify_profile.get("digest") or ""),
        }

    def publish_current(self, profile_id: str) -> dict[str, Any]:
        # Validate semantic digest first. Profile commits are directory-atomic; the
        # second profile read below detects a concurrent exchange and retries.
        for _ in range(3):
            self.profiles.get_profile(profile_id, include_prompts=False)
            source = self.profiles.profile_dir(profile_id)
            before = (source / "profile.json").read_bytes()
            files, profile = self._source_files(source)
            after = (source / "profile.json").read_bytes()
            if before == after == files["snapshot.json"]:
                return self._publish_files(files, profile)
        raise ProfileError("profile changed while snapshot was being captured")

    def publish_capture(self, capture_dir: Path) -> dict[str, Any]:
        source = capture_dir.resolve()
        files, profile = self._source_files(source)
        return self._publish_files(files, profile)

    def load(self, snapshot_digest: str) -> dict[str, Any]:
        path = self.path(snapshot_digest)
        files, profile = self._source_files(path)
        if self._snapshot_digest(files) != snapshot_digest:
            raise ProfileError("snapshot digest mismatch")
        return {
            "snapshotDigest": snapshot_digest,
            "profile": profile,
            "promptTexts": {
                "base": files["prompts/base.md"].decode("utf-8"),
                "roles": {
                    role: files[f"prompts/roles/{role}.md"].decode("utf-8")
                    for role in (profile.get("roles") or {})
                },
            },
        }


class ProfileActivationStore:
    """Persistent intent only; no browser reconciliation in slice 1."""

    def __init__(self, root: Path) -> None:
        self.path = root.resolve() / "config" / "profile-activation.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_json(self.path, {"schemaVersion": 1, "profiles": {}}, mode=0o640)

    def _load(self) -> dict[str, Any]:
        try:
            body = json.loads(self.path.read_text("utf-8"))
        except Exception as exc:
            raise ProfileError(f"invalid profile-activation.json: {exc}") from exc
        if not isinstance(body, dict) or int(body.get("schemaVersion") or 0) != 1 or not isinstance(body.get("profiles"), dict):
            raise ProfileError("invalid profile activation schema")
        return body

    @staticmethod
    def effective(row: dict[str, Any]) -> str:
        return str(row.get("operatorOverride") or row.get("scheduleIntent") or row.get("configIntent") or "INACTIVE")

    def get(self, profile_id: str) -> dict[str, Any]:
        ProfileStore._validate_profile_id(profile_id)
        body = self._load()
        row = dict((body.get("profiles") or {}).get(profile_id) or {})
        row.setdefault("profileId", profile_id)
        row.setdefault("configIntent", "INACTIVE")
        row.setdefault("scheduleIntent", None)
        row.setdefault("operatorOverride", None)
        row.setdefault("restartGeneration", 0)
        row["effectiveDesiredState"] = self.effective(row)
        return row

    def put(self, profile_id: str, *, config_intent: str | None = None, schedule_intent: str | None | object = ..., operator_override: str | None | object = ..., restart: bool = False, changed_by: str = "config", reason: str = "") -> dict[str, Any]:
        ProfileStore._validate_profile_id(profile_id)
        body = self._load()
        rows = body.setdefault("profiles", {})
        row = self.get(profile_id)
        if config_intent is not None:
            row["configIntent"] = str(config_intent)
        if schedule_intent is not ...:
            row["scheduleIntent"] = schedule_intent
        if operator_override is not ...:
            row["operatorOverride"] = operator_override
        for key in ("configIntent", "scheduleIntent", "operatorOverride"):
            if row.get(key) not in {"ACTIVE", "INACTIVE", None}:
                raise ProfileError(f"invalid activation {key}")
        if restart:
            row["restartGeneration"] = int(row.get("restartGeneration") or 0) + 1
        row["changedAt"] = utc_now()
        row["changedBy"] = str(changed_by or "config")
        row["reason"] = str(reason or "")
        row.pop("effectiveDesiredState", None)
        rows[profile_id] = row
        atomic_write_json(self.path, body, mode=0o640)
        return self.get(profile_id)


class ProfileSessionStore:
    """ProfileSession foundation. It deliberately has no endpoint/tab effects."""

    LIVE_STATES = {"STARTING", "RUNNING", "DEGRADED"}

    def __init__(self, root: Path, snapshots: ProfileSnapshotStore) -> None:
        self.root = root.resolve()
        self.sessions_root = self.root / "runtime" / "profile-sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.snapshots = snapshots

    def list(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.sessions_root.iterdir():
            if not path.is_dir() or not (path / "session.json").is_file():
                continue
            try:
                row = json.loads((path / "session.json").read_text("utf-8"))
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if profile_id is not None and str(row.get("profileId") or "") != str(profile_id):
                continue
            rows.append(row)
        rows.sort(key=lambda x: str(x.get("createdAt") or ""), reverse=True)
        return rows

    def current(self, profile_id: str) -> dict[str, Any] | None:
        rows = [x for x in self.list(profile_id) if str(x.get("state") or "") in self.LIVE_STATES]
        if len(rows) > 1:
            raise ProfileError(f"multiple live sessions for profile {profile_id}")
        return rows[0] if rows else None

    def ensure(self, profile_id: str, binding_ids: list[str], restart_generation: int = 0) -> dict[str, Any]:
        current = self.current(profile_id)
        if current and int(current.get("restartGeneration") or 0) == int(restart_generation):
            return current
        if current:
            stopped = dict(current)
            stopped["state"] = "STOPPED"
            stopped["stoppedAt"] = utc_now()
            atomic_write_json(self.sessions_root / str(current["sessionId"]) / "session.json", stopped, mode=0o640)
        snap = self.snapshots.publish_current(profile_id)
        session_id = "ps-" + uuid.uuid4().hex
        row = {
            "schemaVersion": 1,
            "sessionId": session_id,
            "profileId": profile_id,
            "profileRevision": snap["profileRevision"],
            "profileDigest": snap["profileDigest"],
            "snapshotDigest": snap["snapshotDigest"],
            "bindingIds": sorted({str(x) for x in binding_ids if str(x)}),
            "restartGeneration": int(restart_generation),
            "state": "STARTING",
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
        }
        session_dir = self.sessions_root / session_id
        session_dir.mkdir(mode=0o750)
        atomic_write_json(session_dir / "session.json", row, mode=0o640)
        return row
