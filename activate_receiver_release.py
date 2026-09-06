#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Activate an installed receiver release.

Mirrors activate_console_release.py. Writing the marker is atomic; the platform
manager notices the change on its next loop and restarts the receiver, so
activation and rollback are the same single operation in both directions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description='Activate an installed Prompt Automation Pro 2 receiver release')
    p.add_argument('version')
    p.add_argument('--root', default=str(Path(__file__).resolve().parent))
    args = p.parse_args()
    root = Path(args.root).resolve()
    rel = f'receivers/{args.version}/server.py'
    target = (root / rel).resolve()
    if root not in target.parents or not target.is_file():
        print('ERROR::RECEIVER_RELEASE_MISSING=' + str(target))
        raise SystemExit(2)
    marker = root / 'runtime' / 'receiver-current.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version': args.version, 'path': rel}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, marker)
    print('RET_VALUE::RECEIVER_RELEASE_ACTIVATED=' + args.version)
    print('RET_VALUE::RECEIVER_PORT=8867')


if __name__ == '__main__':
    main()
