#!/usr/bin/env bash
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
#
# Live behavioural smoke for slice 1 against the running stand.
# Read-mostly: it posts intake to the receiver and reads the console API.
# It never restarts anything and never edits configuration.
set -uo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
TOKEN="$(tr -d '\n' < runtime/token.txt)"
export PAP_SMOKE_TOKEN="$TOKEN"
python3 - <<'PY'
import json, os, time, urllib.request, urllib.error, hashlib

TOKEN = os.environ['PAP_SMOKE_TOKEN']
R = 'http://127.0.0.1:8867'
C = 'http://127.0.0.1:8871'
STAMP = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())

def call(url, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ('POST' if data else 'GET'))
    req.add_header('Content-Type', 'application/json')
    if token: req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode()[:200]}

def parse(text_marker):
    return {
        'page': 'https://chatgpt.com/c/pap2-smoke',
        'chatType': 'chatgpt',
        'chatConversationId': 'pap2-smoke',
        'generatedAt': STAMP + '-' + text_marker,
        'items': [{'type': 'TEXT', 'value': 'slice1 smoke ' + STAMP}],
        'fileTransfer': {'requiredPaths': []},
    }

ok = True
def check(name, cond, detail=''):
    global ok
    print(f'RET_VALUE::{name}=' + ('PASS' if cond else 'FAIL') + (f' {detail}' if detail else ''))
    ok = ok and cond

s, health_r = call(R + '/health')
s2, health_c = call(C + '/health')
print('RET_VALUE::SMOKE_RECEIVER_VERSION=' + str(health_r.get('version')))
print('RET_VALUE::SMOKE_CONSOLE_VERSION=' + str(health_c.get('version')))
check('SMOKE_VERSIONS', health_r.get('version') == '2.11.0-s1' and health_c.get('version') == '4.5.0-s1')

st, first = call(R + '/api/chat-result', parse('a'), TOKEN)
print('RET_VALUE::SMOKE_INTAKE_STATUS=' + str(st))
run_id = first.get('canonicalRunId') or first.get('runId')
print('RET_VALUE::SMOKE_RUN_ID=' + str(run_id))
check('SMOKE_INTAKE_ACCEPTED', st == 200 and bool(run_id), str(first)[:120])
check('SMOKE_FIRST_NOT_DUPLICATE', first.get('duplicate') is False, str(first.get('duplicate')))

st2, second = call(R + '/api/chat-result', parse('b'), TOKEN)
print('RET_VALUE::SMOKE_SECOND=' + json.dumps(second)[:160])
check('SMOKE_DEDUPE', second.get('duplicate') is True and second.get('canonicalRunId') == run_id)
# /api/chat-result reports the dedupe verdict, not the counter; the counter is
# a flat field of the runs row, read below.

time.sleep(2)
st3, runs = call(C + '/api/runs', token=TOKEN)
items = runs.get('runs') if isinstance(runs, dict) else runs
ids = [r.get('runId') for r in (items or [])]
print('RET_VALUE::SMOKE_RUNS_STATUS=' + str(st3))
print('RET_VALUE::SMOKE_RUNS_COUNT=' + str(len(ids)))
check('SMOKE_RUN_VISIBLE', run_id in ids, 'run not listed' if run_id not in ids else '')
check('SMOKE_NO_STAGING_LISTED', not any(str(i).startswith('intake-') for i in ids))
check('SMOKE_ONE_CANONICAL', ids.count(run_id) == 1)

# list_runs flattens the context into the row rather than nesting it; only
# run_detail returns a profileContext object.
row = next((r for r in (items or []) if r.get('runId') == run_id), {})
print('RET_VALUE::SMOKE_RESOLUTION=' + str(row.get('resolutionStatus')))
print('RET_VALUE::SMOKE_BLOCK_REASON=' + str(row.get('blockReason')))
print('RET_VALUE::SMOKE_SNAPSHOT=' + str(row.get('snapshotDigest'))[:32])
print('RET_VALUE::SMOKE_WORKFLOW=' + str(row.get('workflowStatus')))
print('RET_VALUE::SMOKE_DUPCOUNT=' + str(row.get('duplicateCount')))
check('SMOKE_CONTEXT_PRESENT', bool(row.get('resolutionStatus')))
resolved = row.get('resolutionStatus') == 'RESOLVED'
# A smoke chat has no operator binding, so an unresolved verdict is the correct
# outcome. What must hold either way: the verdict is explicit, a resolved run
# carries a snapshot, and an unresolved one is blocked rather than runnable.
check('SMOKE_SNAPSHOT_IFF_RESOLVED', bool(row.get('snapshotDigest')) == resolved,
      f"resolution={row.get('resolutionStatus')} snapshot={bool(row.get('snapshotDigest'))}")
check('SMOKE_UNRESOLVED_IS_BLOCKED', resolved or row.get('workflowStatus') == 'BLOCKED',
      str(row.get('workflowStatus')))
check('SMOKE_DUPLICATE_COUNTED', int(row.get('duplicateCount') or 0) >= 1,
      str(row.get('duplicateCount')))

sd, detail = call(C + '/api/runs/' + run_id, token=TOKEN)
dctx = (detail or {}).get('profileContext') or {}
print('RET_VALUE::SMOKE_DETAIL_STATUS=' + str(sd))
check('SMOKE_DETAIL_CONTEXT', sd == 200 and dctx.get('resolutionStatus') == row.get('resolutionStatus'),
      str(dctx.get('resolutionStatus')))

print('RET_VALUE::SMOKE_RESULT=' + ('OK' if ok else 'FAILED'))
print('RET_VALUE::SMOKE_DONE=1')
PY
