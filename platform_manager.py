#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def stop_child(name: str, proc: subprocess.Popen | None, timeout: float = 10.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    print(f'[{now()}] stopping {name} pid={proc.pid}', flush=True)
    proc.terminate()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f'[{now()}] stopped {name} pid={proc.pid} rc={proc.returncode}', flush=True)
            return
        time.sleep(0.1)
    raise RuntimeError(f'{name} pid={proc.pid} did not stop after SIGTERM')


def load_console_release(root: Path) -> tuple[str, Path]:
    marker = root / 'runtime' / 'console-current.json'
    body = json.loads(marker.read_text('utf-8'))
    version = str(body['version'])
    release = (root / str(body['path'])).resolve()
    if root.resolve() not in release.parents:
        raise RuntimeError('console release path escapes root')
    if not (release / 'console_server.py').is_file():
        raise RuntimeError(f'console_server.py missing in {release}')
    return version, release


def main() -> None:
    ap = argparse.ArgumentParser(description='Prompt Automation Pro 2 stable platform manager')
    ap.add_argument('--root', required=True)
    ap.add_argument('--receiver-host', default='0.0.0.0')
    ap.add_argument('--receiver-port', type=int, default=8867)
    ap.add_argument('--console-host', default='0.0.0.0')
    ap.add_argument('--console-port', type=int, default=8871)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    runtime = root / 'runtime'
    logs = root / 'logs'
    runtime.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    token_file = runtime / 'token.txt'
    receiver: subprocess.Popen | None = None
    console: subprocess.Popen | None = None
    console_key: tuple[str, str] | None = None

    def shutdown(signum, frame):
        print(f'[{now()}] platform manager received signal={signum}', flush=True)
        errors=[]
        for name, proc in [('console', console), ('receiver', receiver)]:
            try:
                stop_child(name, proc)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            print(f'[{now()}] shutdown errors={errors}', flush=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    receiver_log = open(logs / 'receiver.log', 'a', encoding='utf-8', buffering=1)
    console_log = open(logs / 'console.log', 'a', encoding='utf-8', buffering=1)

    while True:
        try:
            token = token_file.read_text('utf-8').strip()
            if not token:
                raise RuntimeError('runtime/token.txt is empty')

            if receiver is None or receiver.poll() is not None:
                env = os.environ.copy()
                env['CLAUDE_RECEIVER_TOKEN'] = token
                cmd = [sys.executable, str(root / 'server.py'), '--host', args.receiver_host, '--port', str(args.receiver_port), '--data-dir', str(root / 'data')]
                print(f'[{now()}] starting receiver: {" ".join(cmd)}', flush=True)
                receiver = subprocess.Popen(cmd, env=env, stdout=receiver_log, stderr=subprocess.STDOUT)
                (runtime / 'receiver.pid').write_text(str(receiver.pid)+'\n', encoding='utf-8')

            version, release = load_console_release(root)
            key=(version, str(release))
            if console is None or console.poll() is not None or key != console_key:
                if console is not None and console.poll() is None:
                    stop_child('console', console)
                env=os.environ.copy()
                vendor=release/'vendor'
                if vendor.is_dir():
                    env['PYTHONPATH']=str(vendor)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
                cmd=[sys.executable, str(release/'console_server.py'), '--root', str(root), '--data-dir', str(root/'data'), '--token-file', str(token_file), '--host', args.console_host, '--port', str(args.console_port)]
                print(f'[{now()}] starting console version={version}: {" ".join(cmd)}', flush=True)
                console=subprocess.Popen(cmd, env=env, stdout=console_log, stderr=subprocess.STDOUT)
                (runtime / 'console.pid').write_text(str(console.pid)+'\n', encoding='utf-8')
                console_key=key
            time.sleep(1.0)
        except SystemExit:
            raise
        except Exception as exc:
            print(f'[{now()}] manager error={exc}; retry in 2s', flush=True)
            time.sleep(2.0)


if __name__ == '__main__':
    main()
