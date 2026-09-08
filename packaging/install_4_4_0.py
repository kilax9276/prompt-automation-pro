#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import shutil
import stat
import uuid
from pathlib import Path

TARGET_VERSION = "4.4.0"
BASE_VERSION = "4.3.5"


def ret(name: str, value) -> None:
    print(f"RET_VALUE::{name}={value}", flush=True)


def fail(code: str, detail: str) -> None:
    print(f"ERROR::{code}={detail}", flush=True)
    raise SystemExit(2)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception as exc:
        fail("JSON_INVALID", f"{path}:{type(exc).__name__}:{exc}")


def verify_tree(root: Path, manifest: dict, label: str) -> None:
    expected = {str(x["path"]): x for x in manifest.get("files") or []}
    actual = {}
    if not root.is_dir():
        fail(f"{label}_MISSING", str(root))
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            fail(f"{label}_SYMLINK", rel)
        if p.is_dir():
            continue
        # Bytecode caches are produced by CPython whenever the console imports
        # its own modules. They are generated artefacts, never source, and are
        # not part of any release manifest: a running release always has them.
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        actual[rel] = p
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        fail(f"{label}_TREE_MISMATCH", f"missing={missing};extra={extra}")
    for rel, spec in expected.items():
        p = actual[rel]
        if p.stat().st_size != int(spec["size"]):
            fail(f"{label}_SIZE_MISMATCH", rel)
        got = sha256(p)
        if got != str(spec["sha256"]):
            fail(f"{label}_SHA256_MISMATCH", f"{rel}:{got}")



def tree_matches(root: Path, manifest: dict) -> bool:
    expected = {str(x["path"]): x for x in manifest.get("files") or []}
    if not root.is_dir():
        return False
    actual = {}
    try:
        for item in root.rglob("*"):
            rel = item.relative_to(root).as_posix()
            if item.is_symlink():
                return False
            if item.is_dir():
                continue
            if "__pycache__" in item.parts or item.suffix == ".pyc":
                continue
            actual[rel] = item
        if set(actual) != set(expected):
            return False
        for rel, spec in expected.items():
            item = actual[rel]
            if item.stat().st_size != int(spec["size"]):
                return False
            if sha256(item) != str(spec["sha256"]):
                return False
        return True
    except Exception:
        return False

def fsync_tree(root: Path) -> None:
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            fd = os.open(p, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    dirs = [root] + [p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()]
    dirs.sort(key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        fd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/ext_disk/prompt_automation_pro2")
    args = ap.parse_args()

    package_dir = Path(__file__).resolve().parent
    root = Path(args.root).resolve()
    if not root.is_dir():
        fail("ROOT_MISSING", str(root))

    baseline_manifest = load_json(package_dir / "baseline-4.3.5-sha256.json")
    release_manifest = load_json(package_dir / "release-manifest.json")
    source_release = package_dir / "console_releases" / TARGET_VERSION
    baseline_release = root / "console_releases" / BASE_VERSION
    target_release = root / "console_releases" / TARGET_VERSION
    marker_path = root / "runtime" / "console-current.json"

    marker = load_json(marker_path)
    active = str((marker or {}).get("version") or "") if isinstance(marker, dict) else ""
    if active not in {BASE_VERSION, TARGET_VERSION}:
        fail("ACTIVE_CONSOLE_UNEXPECTED", active or "UNKNOWN")

    # The build is based on the exact uploaded 4.3.5 bytes. Refuse to install on drift.
    verify_tree(baseline_release, baseline_manifest, "BASELINE_4_3_5")
    ret("BASELINE_4_3_5_VERIFIED", 1)

    verify_tree(source_release, release_manifest, "PACKAGE_4_4_0")
    ret("PACKAGE_4_4_0_VERIFIED", 1)

    # Compile every Python file before touching the project tree.
    compile_root = package_dir / (".compile-" + uuid.uuid4().hex)
    compile_root.mkdir()
    try:
        for src in sorted(source_release.glob("*.py")):
            py_compile.compile(str(src), cfile=str(compile_root / (src.name + ".pyc")), doraise=True)
    except Exception as exc:
        fail("PY_COMPILE_FAILED", f"{type(exc).__name__}:{exc}")
    finally:
        shutil.rmtree(compile_root, ignore_errors=True)
    ret("PY_COMPILE_OK", 1)

    replace_existing = False
    if target_release.exists():
        if tree_matches(target_release, release_manifest):
            ret("INSTALL_ALREADY_PRESENT", 1)
            ret("CONSOLE_RELEASE_INSTALLED", TARGET_VERSION)
            ret("ACTIVE_CONSOLE_UNCHANGED", active)
            ret("CONFIG_CREATED", 0)
            ret("DATA_TOUCHED", 0)
            ret("INSTALL_OK", 1)
            return
        if active == TARGET_VERSION:
            fail("ACTIVE_4_4_0_DIFFERS_FROM_PACKAGE", str(target_release))
        replaceable_manifest = load_json(package_dir / "replaceable-manifest.json")
        verify_tree(target_release, replaceable_manifest, "REPLACEABLE_INACTIVE_4_4_0")
        replace_existing = True
        ret("REPLACEABLE_INACTIVE_4_4_0_VERIFIED", 1)

    releases_root = root / "console_releases"
    tmp = releases_root / ("." + TARGET_VERSION + ".install-" + uuid.uuid4().hex)
    backup = None
    if tmp.exists():
        fail("INSTALL_TMP_EXISTS", str(tmp))
    try:
        shutil.copytree(
            source_release,
            tmp,
            copy_function=shutil.copy2,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        verify_tree(tmp, release_manifest, "STAGED_4_4_0")
        fsync_tree(tmp)
        if replace_existing:
            backup = releases_root / ("." + TARGET_VERSION + ".replaced-" + uuid.uuid4().hex)
            os.rename(target_release, backup)
            try:
                os.rename(tmp, target_release)
            except Exception:
                os.rename(backup, target_release)
                backup = None
                raise
        else:
            os.rename(tmp, target_release)
        pfd = os.open(releases_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(pfd)
        finally:
            os.close(pfd)
        verify_tree(target_release, release_manifest, "INSTALLED_4_4_0")
        if backup is not None:
            shutil.rmtree(backup)
            pfd = os.open(releases_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(pfd)
            finally:
                os.close(pfd)
            backup = None
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(exc, SystemExit):
            raise
        fail("INSTALL_FAILED", f"{type(exc).__name__}:{exc}")

    verify_tree(target_release, release_manifest, "INSTALLED_4_4_0")
    ret("CONSOLE_RELEASE_INSTALLED", TARGET_VERSION)
    ret("ACTIVE_CONSOLE_UNCHANGED", active)
    ret("CONFIG_CREATED", 0)
    ret("DATA_TOUCHED", 0)
    ret("INSTALL_OK", 1)


if __name__ == "__main__":
    main()
