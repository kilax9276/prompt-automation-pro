#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
"""Derive the byte inventory the implementation map anchors against.

Catalogs are logical: a file is named once as (role, name). The tree decides
where a role lives. Slice 1 was deployed as versioned release directories
rather than an in-place edit, so the same catalog must read both the frozen
historical layout and the working base — keeping two literal path lists is how
an extractor and an inventory end up from different generations.
"""
from __future__ import annotations
import ast, hashlib, json, re, subprocess
from pathlib import Path

# Paths are resolved from this file's location so the toolchain runs anywhere.
# The working base is the release directories themselves — one copy, not a
# duplicate that could drift away from the tree the map describes.
_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent

ROOT = _ROOT
OUT  = _TOOLS / 'inventory.generated.json'

LAYOUTS = {
 'historical-4.4.0': {'console':'console_releases/4.4.0','receiver':'server.py','extension':'extension'},
 'closed-S1':        {'console':'console_releases/4.5.0-s1','receiver':'receivers/2.11.0-s1/server.py','extension':'extension_releases/2.11.6'},
}


def resolve(root: Path):
    found=[n for n,s in LAYOUTS.items()
           if (root/s['console']/'console_server.py').is_file()
           and (root/s['receiver']).is_file()
           and (root/s['extension']/'manifest.json').is_file()]
    if len(found)==1: return found[0], LAYOUTS[found[0]]
    if not found: raise SystemExit('no known layout present in '+str(root))
    print('# note: layouts present: '+', '.join(found)+'; using closed-S1')
    return 'closed-S1', LAYOUTS['closed-S1']


LOGICAL_FILES = [
 ('console','executor.py'),('console','protocol_engine.py'),('console','console_server.py'),
 ('console','endpoint_registry.py'),('console','run_profile_context.py'),('console','delivery_manager.py'),
 ('console','execution_error_detector.py'),('console','profile_store.py'),('console','chat_bindings.py'),
 ('console','profile_resolver.py'),('console','static/app.js'),('console','static/index.html'),
 ('console','static/style.css'),
 ('receiver',''),
 ('extension','manifest.json'),('extension','background.js'),('extension','content.js'),('extension','chat-bridge.js'),
]

LOGICAL_PY_SYMBOLS = {
('console','executor.py'):['RunExecutor','ensure_plan','ensure_state','execute_step','_execute_command','_execute_put_files','_handle_control','cancel_step'],
('console','protocol_engine.py'):['EXECUTABLE_TYPES','CONTROL_TYPES','build_plan','plan_json'],
('console','console_server.py'):['ConsoleServer','list_runs','run_detail','scan_fingerprint','watcher','api_execute_step','api_log','api_delivery_prepare','api_delivery_poll','api_delivery_event','api_delivery_chunk','api_profiles','api_endpoint_pin','api_endpoint_unpin','on_startup','on_cleanup','create_app'],
('console','endpoint_registry.py'):['EndpointRegistry','observe','list','endpoints_for_binding','pin','unpin','pin_state','pinned_tab','select_for_binding'],
('console','run_profile_context.py'):['RunProfileContext','get','authorize_execution','_resolve_delivery_binding','authorize_delivery'],
('console','delivery_manager.py'):['ACTIVE_ATTACHMENT_STATES','TERMINAL_JOB_STATES','CLAIM_LEASE_SECONDS','DeliveryManager','job_dir','get_job','save_job','list_jobs','latest_job','create_job','find_latest_submitted_job','create_recovery_replay','pause_unfinished_jobs_after_restart','supersede_older_jobs_for_tab','_derive_job_status','_lease_is_active','_touch_lease','_clear_lease','recover_expired_leases','poll_for_tab','update_from_client','attachment_chunk'],
('receiver',''):['ReceiverServer','Handler','_result','_status','_file_start','_record_completed','_file_finish'],
('console','execution_error_detector.py'):['ErrorSignature','ExecutionErrorDetector','feed','result'],
('console','profile_store.py'):['ProfileStore','_validate_profile','get_profile','save_profile'],
('console','chat_bindings.py'):['ChatBindingsStore','_validate','create','update','find_for_chat','bindings_for_role'],
('console','profile_resolver.py'):['ProfileResolver','identity_from_result','resolve'],
}

LOGICAL_TEXT_ANCHORS = {

('console','profile_store.py'): {
 'endpoint timeout read':'timeout = int(delivery.get("endpointWaitTimeoutSec") or 3600)',
 'endpoint timeout min':'endpointWaitTimeoutSec must be >=',
 'endpoint timeout max':'endpointWaitTimeoutSec is too large',
 'endpoint timeout write':'"delivery": {"offlineTargetPolicy": offline_policy, "endpointWaitTimeoutSec": timeout}',
},
('console','run_profile_context.py'): {
 'endpoint timeout read/write':'"endpointWaitTimeoutSec": int(delivery.get("endpointWaitTimeoutSec") or 3600)',
},
('console','console_server.py'): {
 'endpoint timeout consume':'authorization.get("endpointWaitTimeoutSec")',
},
('extension','background.js'): {
 'SESSION_TABS_KEY':'const SESSION_TABS_KEY = "enabledTabs";',
 'SESSION_STATUS_KEY':'const SESSION_STATUS_KEY = "tabStatuses";',
 'isTabEnabled':'async function isTabEnabled(tabId)',
 'tabs.onRemoved':'chrome.tabs.onRemoved.addListener',
 'GET_RUNTIME_CONFIG':'if (message.type === "GET_RUNTIME_CONFIG")',
 'POST_PARSE_RESULT':'if (message.type === "POST_PARSE_RESULT")',
 'REQUIRED_SERVER_SERVICE':'const REQUIRED_SERVER_SERVICE',
 'base.port':'base.port = "8871"',
},
('extension','chat-bridge.js'): {
 'RECOVERY_SOURCE_KEY':'const RECOVERY_SOURCE_KEY',
 'runtimeConfig':'async function runtimeConfig()',
 'loop':'async function loop()',
},
('extension','content.js'): {
 'SOURCE_CONTENT':'const SOURCE_CONTENT',
 'SOURCE_PAGE':'const SOURCE_PAGE',
 'parseMessage':'const parseMessage =',
 'turnId:null':'turnId:null',
 'parsePage':'const parsePage =',
 'parserVersion':'parserVersion:',
},
('console','static/app.js'): {
 'refreshRuns':'async function refreshRuns()',
 'renderRuns':'function renderRuns()',
 'setView':'function setView(view)',
 'profile delivery default':"delivery:{offlineTargetPolicy:'wait',endpointWaitTimeoutSec:3600}, directives:{},",
 'profile delivery load':"$('endpointTimeoutInput').value = p.delivery?.endpointWaitTimeoutSec || 3600;",
 'renderProfileRoles':'function renderProfileRoles()',
 'profile delivery save':'endpointWaitTimeoutSec:Number',
 'refreshChats':'async function refreshChats(options)',
 'renderEndpoints':'function renderEndpoints()',
 'renderBindings':'function renderBindings()',
},
('console','static/index.html'): {
 'navigation':'<nav class="section-nav">',
 'runs sidebar':'<aside class="sidebar">',
 'fullRunLog':'id="fullRunLog"',
 'profile directives':'data-profile-panel="directives"',
 'profile delivery':'data-profile-panel="delivery"',
 'profile assigned chats':'id="profileAssignedChats"',
},
('console','static/style.css'): {
 'run-list':'.run-list',
 'auto-error mark':'mark.log-stop-match',
 'section-nav':'.section-nav { display:flex;',
 'profile-tab-panel':'.profile-tab-panel { min-height:',
},
('extension','manifest.json'): {
 'permissions':'"permissions": [',
 'background':'"background": {',
 'version':'"version": "2.11.6"',
},
}


# Symbols created by slice 1. Absent from the historical layout by definition,
# required in full on the working base. They are the anchor candidates the four
# DEBT items attach to; listing them here implements nothing.
LOGICAL_S1_SYMBOLS = {
('console','profile_store.py'):[
 'ProfileSnapshotStore',   # DEBT-001 owner: content-addressed snapshot publication
 '_source_files',          # DEBT-001: the byte set frozen into snapshotDigest
 'publish_current',        # DEBT-001: session-less Run path
 'publish_capture',        # DEBT-001: intake-captured path
 'ProfileActivationStore', # DEBT-003 owner: restartGeneration lives here
 'put',                    # DEBT-003: the only place restartGeneration increments
 'ProfileSessionStore',    # DEBT-002/004 owner: session composition
 'ensure',                 # DEBT-002/004: composition assembly per generation
],
('console','run_profile_context.py'):[
 'ensure_run_context',     # explicit creator; scenario provenance attaches here
],
}

LAYOUT_NAME, LAYOUT = resolve(ROOT)


def materialise(role, name):
    """Turn a logical (role, name) into the path this layout actually uses."""
    return LAYOUT['receiver'] if role == 'receiver' else f"{LAYOUT[role]}/{name}"


FILES        = [materialise(r, n) for r, n in LOGICAL_FILES]
PY_SYMBOLS   = {materialise(*k): v for k, v in LOGICAL_PY_SYMBOLS.items()}
TEXT_ANCHORS = {materialise(*k): v for k, v in LOGICAL_TEXT_ANCHORS.items()}
S1_SYMBOLS   = {materialise(*k): v for k, v in LOGICAL_S1_SYMBOLS.items()}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()






def py_index(path: Path):
    tree=ast.parse(path.read_text('utf-8'))
    out={}
    def record(n,prefix=''):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            start=min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])])
            out.setdefault(n.name,[]).append({'start':start,'end':getattr(n,'end_lineno',n.lineno),'kind':type(n).__name__})
        if isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=n.targets if isinstance(n,ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t,ast.Name): out.setdefault(t.id,[]).append({'start':n.lineno,'end':getattr(n,'end_lineno',n.lineno),'kind':'assignment'})
        for child in ast.iter_child_nodes(n): record(child,prefix)
    record(tree)
    return out

def brace_range(lines, start_idx):
    # For JS blocks beginning on the matched line. Conservative lexer for strings/comments.
    joined='\n'.join(lines[start_idx:])
    first=joined.find('{')
    if first < 0: return (start_idx+1,start_idx+1)
    bal=0; line=start_idx+1; in_s=in_d=in_bt=False; esc=False; line_comment=False; block_comment=False
    i=first
    while i < len(joined):
        ch=joined[i]; nxt=joined[i+1] if i+1<len(joined) else ''
        if ch=='\n': line+=1; line_comment=False; i+=1; continue
        if line_comment: i+=1; continue
        if block_comment:
            if ch=='*' and nxt=='/': block_comment=False; i+=2; continue
            i+=1; continue
        if esc: esc=False; i+=1; continue
        if (in_s or in_d or in_bt) and ch=='\\': esc=True; i+=1; continue
        if not (in_s or in_d or in_bt):
            if ch=='/' and nxt=='/': line_comment=True; i+=2; continue
            if ch=='/' and nxt=='*': block_comment=True; i+=2; continue
        if not in_d and not in_bt and ch=="'": in_s=not in_s; i+=1; continue
        if not in_s and not in_bt and ch=='"': in_d=not in_d; i+=1; continue
        if not in_s and not in_d and ch=='`': in_bt=not in_bt; i+=1; continue
        if in_s or in_d or in_bt: i+=1; continue
        if ch=='{': bal+=1
        elif ch=='}':
            bal-=1
            if bal==0: return (start_idx+1,line)
        i+=1
    return (start_idx+1,start_idx+1)

def text_index(path: Path, anchors):
    lines=path.read_text('utf-8').splitlines(); out={}
    for name,needle in anchors.items():
        hits=[i for i,l in enumerate(lines) if needle in l]
        if not hits: raise SystemExit(f'missing anchor {path}:{name}:{needle}')
        i=hits[0]
        is_block=any(k in lines[i] for k in ['function ','=> {','addListener','if (']) and '{' in '\n'.join(lines[i:i+2])
        if path.suffix=='.js' and is_block: s,e=brace_range(lines,i)
        else: s=e=i+1
        out[name]={'start':s,'end':e,'needle':needle,'hits':[x+1 for x in hits]}
    return out

s1_present=[]; s1_absent=[]
s1_present=[]; s1_absent=[]
# No absolute root and no HEAD in the output. Both are provenance of the run,
# not anchors of the tree, and both made the inventory unreproducible: the path
# differs on every machine, and HEAD moves on every unrelated commit — the very
# reason this file anchors on subtree hashes instead. The check that the
# extractor reproduces the shipped inventory could therefore only pass in the
# directory it was generated in, at the commit it was generated at.
inventory={'layout':LAYOUT_NAME,'files':{}}
for rel in FILES:
    p=ROOT/rel; lines=p.read_bytes().splitlines()
    rec={'sha256':sha(p),'lineCount':len(lines),'symbols':{}}
    if rel in PY_SYMBOLS:
        idx=py_index(p)
        for sym in PY_SYMBOLS[rel]:
            if sym not in idx: raise SystemExit(f'missing python symbol {rel}:{sym}')
            choices=idx[sym]
            # Prefer definitions/classes over local assignments when a name collides (e.g. endpoint_registry.pin).
            defs=[x for x in choices if x.get('kind') != 'assignment']
            rec['symbols'][sym]=(defs[0] if defs else choices[0])
    if rel in S1_SYMBOLS:
        idx=idx if rel in PY_SYMBOLS else py_index(p)
        for sym in S1_SYMBOLS[rel]:
            if sym in idx:
                choices=idx[sym]
                defs=[x for x in choices if x.get('kind') != 'assignment']
                rec['symbols'][sym]=(defs[0] if defs else choices[0])
                s1_present.append(f'{rel}:{sym}')
            else:
                s1_absent.append(f'{rel}:{sym}')
    if rel in TEXT_ANCHORS:
        rec['symbols'].update(text_index(p,TEXT_ANCHORS[rel]))
    inventory['files'][rel]=rec
# A tree is either pre-S1 (none of the slice-1 symbols present) or closed-S1
# (all present). Anything in between means the tree is not what it claims.
base = LAYOUT_NAME
# The symbol catalog is now a cross-check of the byte classification, not the
# classification itself. Disagreement means one of the two is wrong.
expected_symbols = 0 if base.startswith('historical') else sum(len(v) for v in S1_SYMBOLS.values())
if len(s1_present)!=expected_symbols or (s1_absent and not base.startswith('historical')):
    raise SystemExit(f'{base} by bytes but slice-1 symbols disagree: '
                     f'present={len(s1_present)} expected={expected_symbols}; absent={s1_absent}')
inventory['baseKind']=base
# Identity of the working base comes from git, not from us. Subtree hashes
# rather than HEAD or the root tree: an unrelated commit — a README edit, a
# journal entry — moves the root tree while moving no anchor, and a value that
# must be hand-corrected on every unrelated change stops describing the tree
# within a fortnight.
def _rev(spec):
    try:
        return subprocess.check_output(['git','-C',str(ROOT),'rev-parse',spec],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
inventory['workingTrees']={
 'console':   _rev('HEAD:'+LAYOUT['console']),
 'receiver':  _rev('HEAD:'+str(Path(LAYOUT['receiver']).parent)),
 'extension': _rev('HEAD:'+LAYOUT['extension']),
}
inventory['historicalPoint']='830ab8c6453fa58ab1fd1339e210a41857e16df6'
inventory['slice1Symbols']=sorted(s1_present)

OUT.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n','utf-8')
# HEAD is reported for the operator reading the run, not written to the file.
print(json.dumps({'head':_rev('HEAD'),'workingTrees':inventory['workingTrees'],'baseKind':base,'files':len(inventory['files']),
                  'anchors':sum(len(x['symbols']) for x in inventory['files'].values()),
                  'slice1Anchors':len(s1_present)},ensure_ascii=False))
