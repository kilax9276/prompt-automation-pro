#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUNTIME="$ROOT/runtime"
LOGS="$ROOT/logs"
mkdir -p "$RUNTIME" "$LOGS" "$ROOT/data"

PAP_PLATFORM_ROOT="$ROOT" python3 - <<'PY'
from pathlib import Path
import json, os, secrets, subprocess, sys, time, urllib.request
root=Path(os.environ['PAP_PLATFORM_ROOT']).resolve()
runtime=root/'runtime'; logs=root/'logs'
token_file=runtime/'token.txt'
if not token_file.is_file() or not token_file.read_text('utf-8').strip():
    token_file.write_text(secrets.token_urlsafe(32)+'\n',encoding='utf-8')
    os.chmod(token_file,0o600)
prepared_version=(root/'VERSION-platform').read_text('utf-8').strip()
marker=runtime/'console-current.json'
if not marker.is_file():
    marker.write_text(json.dumps({'version':prepared_version,'path':f'console_releases/{prepared_version}'},indent=2)+'\n',encoding='utf-8')
active=json.loads(marker.read_text('utf-8'))
active_version=str(active.get('version') or '')
pidfile=runtime/'platform-manager.pid'
alive=False
try:
    pid=int(pidfile.read_text().strip())
    cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode('utf-8','replace')
    alive=str(root/'platform_manager.py') in cmd
except Exception:
    alive=False
if not alive:
    log=open(logs/'platform-manager.log','a',encoding='utf-8')
    p=subprocess.Popen([sys.executable,str(root/'platform_manager.py'),'--root',str(root)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    pidfile.write_text(str(p.pid)+'\n',encoding='utf-8')
for _ in range(120):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8867/health',timeout=1) as rr: r=json.loads(rr.read().decode())
        with urllib.request.urlopen('http://127.0.0.1:8871/health',timeout=1) as cr: c=json.loads(cr.read().decode())
        if r.get('version')=='2.10.0' and c.get('version')==active_version:
            host=os.environ.get('PAP_PUBLIC_HOST','192.168.10.78')
            print('RET_VALUE::PLATFORM2_READY=1')
            print(f'RET_VALUE::RECEIVER2_URL=http://{host}:8867')
            print(f'RET_VALUE::CONSOLE2_URL=http://{host}:8871')
            print('RET_VALUE::CONSOLE2_VERSION='+active_version)
            print('RET_VALUE::PREPARED_CONSOLE2_VERSION='+prepared_version)
            _t=token_file.read_text('utf-8').strip(); print('RET_VALUE::TOKEN2_LEN='+str(len(_t))); print('RET_VALUE::TOKEN2_FP='+__import__('hashlib').sha256(_t.encode('utf-8')).hexdigest()[:12])
            break
    except Exception:
        pass
    time.sleep(.25)
else:
    print('ERROR::PLATFORM2_NOT_READY')
PY
