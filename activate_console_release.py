#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    p=argparse.ArgumentParser(description='Activate an installed Prompt Automation Pro 2 console release')
    p.add_argument('version')
    p.add_argument('--root', default=str(Path(__file__).resolve().parent))
    args=p.parse_args()
    root=Path(args.root).resolve()
    rel=f'console_releases/{args.version}'
    release=(root/rel).resolve()
    if root not in release.parents or not (release/'console_server.py').is_file():
        print('ERROR::CONSOLE_RELEASE_MISSING='+str(release))
        raise SystemExit(2)
    marker=root/'runtime'/'console-current.json'
    marker.parent.mkdir(parents=True,exist_ok=True)
    tmp=marker.with_suffix('.tmp')
    tmp.write_text(json.dumps({'version':args.version,'path':rel},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(tmp,marker)
    print('RET_VALUE::CONSOLE_RELEASE_ACTIVATED='+args.version)
    print('RET_VALUE::CONSOLE2_PORT=8871')

if __name__=='__main__':
    main()
