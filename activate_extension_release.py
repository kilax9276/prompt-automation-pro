#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Declare which extension release the operator intends to run.

This is deliberately only half of a release mechanism. The console cannot
reach the extension — that is a design invariant, not a gap — so activation
here records an intention and stages the bytes. Nothing forces the browser to
adopt them, and nothing yet verifies that it did: the extension does not report
its version to the server. Until slice 2 adds that report, "active" means
"declared and staged", never "confirmed running".

Saying otherwise would give an atomic server+extension boundary that is only
ever checked on one side.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def manifest_of(release_dir: Path) -> dict:
    return json.loads((release_dir / 'manifest.json').read_text('utf-8'))


def digest_of(release_dir: Path) -> str:
    lines = []
    for p in sorted(release_dir.rglob('*')):
        if p.is_file() and p.name != 'RELEASE_MANIFEST.txt':
            rel = str(p.relative_to(release_dir)).replace('\\', '/')
            lines.append(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}')
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description='Declare and stage a Prompt Automation Pro 2 extension release')
    ap.add_argument('version')
    ap.add_argument('--root', default=str(Path(__file__).resolve().parent))
    ap.add_argument('--stage', action='store_true',
                    help='also refresh runtime/extension-staging with the release bytes')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    rel = f'extension_releases/{args.version}'
    release = (root / rel).resolve()
    if root not in release.parents or not (release / 'manifest.json').is_file():
        print('ERROR::EXTENSION_RELEASE_MISSING=' + str(release))
        raise SystemExit(2)

    declared = str(manifest_of(release).get('version') or '')
    if declared != args.version:
        # A release directory whose manifest disagrees with its name would make
        # every later version comparison meaningless.
        print(f'ERROR::MANIFEST_VERSION_MISMATCH=dir={args.version} manifest={declared}')
        raise SystemExit(3)

    digest = digest_of(release)
    marker = root / 'runtime' / 'extension-current.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    body = {'version': args.version, 'path': rel, 'contentDigest': digest,
            'confirmedRunning': None}
    tmp = marker.with_suffix('.tmp')
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, marker)

    if args.stage:
        staging = root / 'runtime' / 'extension-staging'
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(release, staging)
        (staging / 'RELEASE_MANIFEST.txt').unlink(missing_ok=True)
        print('RET_VALUE::EXTENSION_STAGED=' + str(staging))

    print('RET_VALUE::EXTENSION_DECLARED=' + args.version)
    print('RET_VALUE::EXTENSION_DIGEST=' + digest)
    print('RET_VALUE::EXTENSION_CONFIRMED=none — the extension does not report its version until slice 2')


if __name__ == '__main__':
    main()
