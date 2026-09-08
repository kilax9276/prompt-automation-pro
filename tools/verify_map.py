#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re, subprocess, sys
from pathlib import Path

# Paths are resolved from this file's location so the toolchain runs anywhere.
# The working base is the release directories themselves — one copy, not a
# duplicate that could drift away from the tree the map describes.
_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent

ROOT = _ROOT
MAP = _ROOT / 'PAP2_4.5.0_IMPLEMENTATION_MAP.md'
INV = _TOOLS / 'inventory.json'
VERIFY_INVENTORY = _TOOLS / 'verify_inventory.py'
VERIFY_OVERLAPS = _TOOLS / 'verify_overlaps.py'
EXTRACTOR = _TOOLS / 'extract_inventory.py'
DESIGN = _ROOT / 'docs' / 'PAP2_4.5.0_DESIGN.md'
EXPECTED_FILES = 18

# The report is written where the caller says, or beside the toolchain. It was
# an absolute path on the machine this was written on, so the whole chain died
# with FileNotFoundError on a fresh unpack — after every check had already run,
# which meant the numbers were never printed at all.
REPORT = Path(sys.argv[1]) if len(sys.argv) > 1 else _TOOLS / 'VERIFY_REPORT.txt'

failures=[]
checks=[]
def ok(name, detail=''):
    checks.append((name, detail))
def fail(name, detail=''):
    failures.append((name, detail))
def sha256(p: Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()
def lines_count(p: Path):
    b=p.read_bytes()
    return b.count(b'\n') + (1 if b and not b.endswith(b'\n') else 0)

# Re-derive inventory from immutable source bytes before trusting any map range.
if VERIFY_INVENTORY.exists():
    vi=subprocess.run([sys.executable, str(VERIFY_INVENTORY)], text=True, capture_output=True)
    vi_out=(vi.stdout + vi.stderr).strip()
    if vi.returncode==0 and 'INVENTORY_MATCHES_BYTES' in vi.stdout:
        ok('inventory ranges rederived from bytes', vi.stdout.splitlines()[0] if vi.stdout else 'clean')
    else:
        fail('inventory ranges rederived from bytes', vi_out or f'rc={vi.returncode}')
else:
    fail('inventory ranges rederived from bytes', 'verify_inventory.py missing')

# Cross-slice wholesale replacements must acknowledge earlier bytes they engulf.
# This runs only after inventory has been re-derived from source bytes above.
if VERIFY_OVERLAPS.exists():
    vo=subprocess.run([sys.executable, str(VERIFY_OVERLAPS)], text=True, capture_output=True)
    vo_out=(vo.stdout + vo.stderr).strip()
    if vo.returncode==0 and 'NO_UNDECLARED_CROSS_SLICE_OVERLAP' in vo.stdout:
        ok('cross-slice replacement overlaps declared', vo.stdout.splitlines()[0] if vo.stdout else 'clean')
    else:
        fail('cross-slice replacement overlaps declared', vo_out or f'rc={vo.returncode}')
else:
    fail('cross-slice replacement overlaps declared', 'verify_overlaps.py missing')

# The immutable basis is checked below, against git subtree hashes and a clean
# status of those subtrees. An archive self-hash used to be checked here as
# well: a leftover of the identity model that `baseId` belonged to. It proved
# only that one packaging artifact still had the bytes it had when it was
# packed, said nothing about the tree the map describes, and could not be
# reproduced by anyone who was not holding that exact archive. Removed rather
# than satisfied by shipping the archive — the check below is the one that
# answers the question.
# The design is a living contract, not a constant. It changes with every
# journal decision, more often than slices close. So the map declares which
# revision it was built against, and this check means "the map knows its
# revision", not "the design has not moved". A mismatch means the map was not
# updated after a decision.
declared=re.search(r'^- \*\*Редакция дизайна:\*\* `([0-9a-f]{64})` / (\d+) строк$',
                   MAP.read_text('utf-8'), re.M)
if not declared:
    fail('design revision declared in map', 'line missing from section 1')
elif not DESIGN.exists():
    fail('design revision matches map', 'design file missing')
else:
    got_sha, got_lines = sha256(DESIGN), lines_count(DESIGN)
    if got_sha==declared.group(1) and got_lines==int(declared.group(2)):
        ok('design revision matches map', f'{got_sha} / {got_lines}')
    else:
        fail('design revision matches map',
             f'design is {got_sha} / {got_lines}; map declares {declared.group(1)} / {declared.group(2)}')
# Identity of the working base is git's job. The map declares which subtrees
# it is anchored to; the verifier asks git what is actually there. Subtrees
# rather than HEAD or the root tree, because an unrelated commit moves the root
# tree without moving a single anchor — and a declaration that must be
# hand-corrected on every unrelated change is one that stops being true.
#
# This replaces a self-computed digest compared against itself, which proved
# only that the extractor agreed with the extractor.
def git(*args):
    try:
        return subprocess.check_output(['git','-C',str(ROOT),*args],text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None

declared_trees=dict(re.findall(r'^\| `([a-z]+)` \| `([^`]+)` \| `([0-9a-f]{40})` \|$',
                               MAP.read_text('utf-8'), re.M) and
                    [(m[0],(m[1],m[2])) for m in re.findall(
                        r'^\| `([a-z]+)` \| `([^`]+)` \| `([0-9a-f]{40})` \|$',
                        MAP.read_text('utf-8'), re.M)])
if not declared_trees:
    fail('working base declared in map','subtree table missing from section 1')
elif git('rev-parse','--is-inside-work-tree') != 'true':
    fail('working base verified against git','ROOT is not a git work tree')
else:
    bad=[]
    for role,(path,sha) in sorted(declared_trees.items()):
        actual=git('rev-parse',f'HEAD:{path}')
        if actual!=sha: bad.append(f'{role} {path}: git={actual} map={sha}')
    if bad: fail('working base subtrees match git','; '.join(bad))
    else: ok('working base subtrees match git',f'{len(declared_trees)} subtrees')
    # Any modification, tracked or not, inside the working base invalidates the
    # anchors. This is strictly stronger than the seven-file byte classifier it
    # replaces, which could not see an eighth file change at all.
    paths=[p for _,(p,_) in sorted(declared_trees.items())]
    dirty=[l for l in (git('status','--porcelain','--',*paths) or '').splitlines() if l.strip()]
    if dirty: fail('working base clean',' | '.join(dirty[:5]))
    else: ok('working base clean','no modifications under the declared subtrees')

inv=json.loads(INV.read_text('utf-8'))
inv_trees=inv.get('workingTrees') or {}
declared_only={r:sha for r,(_,sha) in declared_trees.items()}
if inv_trees==declared_only: ok('inventory subtrees match map',f'{len(inv_trees)} subtrees')
else: fail('inventory subtrees', f'inventory {inv_trees}; map {declared_only}')
files=inv.get('files',{})
if len(files)==EXPECTED_FILES: ok('basis file count', str(EXPECTED_FILES))
else: fail('basis file count', str(len(files)))
for rel, rec in files.items():
    p=ROOT/rel
    got_sha=sha256(p) if p.exists() else 'missing'
    got_lines=lines_count(p) if p.exists() else -1
    if got_sha==rec['sha256'] and got_lines==rec['lineCount']:
        ok(f'basis {rel}', f'{got_sha} / {got_lines}')
    else:
        fail(f'basis {rel}', f'sha={got_sha} lines={got_lines}; expected sha={rec["sha256"]} lines={rec["lineCount"]}')

# The shipped extractor must be able to reproduce the shipped inventory.
# Without this, a package can carry an extractor and an inventory from
# different generations and still pass every other check — which is exactly
# what happened once: catalogs listed the historical paths while the inventory
# described the versioned working base, and nothing noticed.
#
# The extractor is run where it is shipped, not as a rewritten copy in a
# temporary directory: it resolves the tree from its own __file__, so a copy
# elsewhere looked for the layout beside the temporary file and failed. That
# only ever worked because a second copy of the extractor happened to sit next
# to a tree on the machine this was written on. It writes its own output file
# (inventory.generated.json), so nothing needs rewriting.
try:
    if not EXTRACTOR.is_file():
        raise FileNotFoundError(f'{EXTRACTOR} is missing from the package')
    generated = _TOOLS / 'inventory.generated.json'
    pre_existing = generated.is_file()
    r = subprocess.run([sys.executable, str(EXTRACTOR)], capture_output=True, text=True)
    produced = json.loads(generated.read_text('utf-8')) if generated.is_file() else None
    if not pre_existing and generated.is_file():
        generated.unlink()
    shipped = json.loads(INV.read_text('utf-8'))
    if r.returncode == 0 and produced == shipped:
        ok('extractor reproduces inventory', f"{len(shipped['files'])} files, "
           f"{sum(len(f['symbols']) for f in shipped['files'].values())} anchors")
    else:
        diff = 'extractor failed: ' + (r.stderr.strip()[-200:] or 'rc=%d' % r.returncode) if r.returncode else \
               'output differs from shipped inventory'
        fail('extractor reproduces inventory', diff)
except Exception as exc:
    fail('extractor reproduces inventory', f'could not run extractor: {exc}')

text=MAP.read_text('utf-8')
# Parse section 3 MAP blocks only.
sec3=text.split('## 3. Точки врезки',1)[1].split('## 4. Миграция',1)[0]
pat=re.compile(r'^### MAP-(\d{3}) — срез (.+?) — `([^`]+)` / `([^`]+)`\n\n(.*?)(?=^### MAP-|\Z)',re.M|re.S)
blocks=list(pat.finditer(sec3))
if blocks and [int(m.group(1)) for m in blocks]==list(range(1,len(blocks)+1)):
    ok('MAP ids sequential', str(len(blocks)))
else:
    fail('MAP ids sequential', str([m.group(1) for m in blocks[:10]]))

map_acc_refs=[]
for m in blocks:
    num, slice_, rel, anchor, body = m.groups()
    label=f'MAP-{num} {rel}/{anchor}'
    # A closed slice's rows describe the frozen historical tree. Those bytes
    # cannot change, so the row keeps its original anchors and is deliberately
    # not compared against the working base — the alternative is to rewrite
    # history every time a slice closes.
    historical = slice_.endswith(' HISTORICAL')
    if historical:
        slice_ = slice_[:-len(' HISTORICAL')]
        am_h=re.search(r'^- \*\*Acceptance:\*\* (.+)$',body,re.M)
        if am_h:
            refs=re.findall(r'`(ACC-[A-Z0-9-]+)`',am_h.group(1))
            if refs: map_acc_refs.extend(refs)
            else: fail(label+' acceptance','no ACC ids')
        else: fail(label+' acceptance','line missing')
        if '- **Статус якорей:** HISTORICAL' not in body:
            fail(label+' historical marker','header says HISTORICAL, body does not')
        else:
            ok(label+' historical anchors','frozen at 830ab8c6, not compared')
        continue
    if rel not in files:
        fail(label+' basis file', 'not in 18-file inventory'); continue
    if anchor not in files[rel].get('symbols',{}):
        fail(label+' anchor', 'missing in inventory'); continue
    sm=re.search(r'^- \*\*Полный SHA-256:\*\* `([0-9a-f]{64})`$',body,re.M)
    rm=re.search(r'^- \*\*Точный диапазон:\*\* `(\d+)–(\d+)`$',body,re.M)
    am=re.search(r'^- \*\*Acceptance:\*\* (.+)$',body,re.M)
    if not sm or sm.group(1)!=files[rel]['sha256']:
        fail(label+' sha', sm.group(1) if sm else 'missing')
    else: ok(label+' sha', sm.group(1))
    sym=files[rel]['symbols'][anchor]
    expected=(sym['start'],sym['end'])
    got=(int(rm.group(1)),int(rm.group(2))) if rm else None
    if got==expected:
        ok(label+' range', f'{got[0]}-{got[1]}')
    else:
        fail(label+' range', f'{got}; expected {expected}')
    if am:
        refs=re.findall(r'`(ACC-[A-Z0-9-]+)`',am.group(1))
        if refs: map_acc_refs.extend(refs)
        else: fail(label+' acceptance', 'no ACC ids')
    else: fail(label+' acceptance', 'line missing')
    if (rel.endswith('/executor.py') or rel.endswith('/protocol_engine.py')) and slice_!='5':
        fail(label+' slice ownership', f'slice={slice_}, expected 5')
    elif rel.endswith('/executor.py') or rel.endswith('/protocol_engine.py'):
        ok(label+' slice ownership','5')
    if '/' in slice_:
        fail(label+' single slice', slice_)

# Exact timeout occurrence inventory.
target='endpointWaitTimeoutSec'
hits=[]
for rel in [
 'console_releases/4.5.0-s1/profile_store.py',
 'console_releases/4.5.0-s1/run_profile_context.py',
 'console_releases/4.5.0-s1/console_server.py',
 'console_releases/4.5.0-s1/static/app.js']:
    for ln,line in enumerate((ROOT/rel).read_text('utf-8').splitlines(),1):
        c=line.count(target)
        if c: hits.append((rel,ln,c))
# ACTIVE on the working base. The 830ab8c6 coordinates (profile_store
# 313/315/317/360, run_profile_context 266, console_server 515, app.js
# 1108/1132/1250) are historical evidence recorded in the map, not a live
# check: slice 1 moved these lines, and slice 2 will remove the old key
# entirely. Shifting the old constants onto new lines as if the same fact were
# being checked is exactly what the classification rule forbids.
expected_hits=[
 ('console_releases/4.5.0-s1/profile_store.py',315,1),
 ('console_releases/4.5.0-s1/profile_store.py',317,1),
 ('console_releases/4.5.0-s1/profile_store.py',319,1),
 ('console_releases/4.5.0-s1/profile_store.py',362,1),
 ('console_releases/4.5.0-s1/run_profile_context.py',391,2),
 ('console_releases/4.5.0-s1/console_server.py',655,1),
 ('console_releases/4.5.0-s1/static/app.js',1142,1),
 ('console_releases/4.5.0-s1/static/app.js',1166,1),
 ('console_releases/4.5.0-s1/static/app.js',1284,1)]
if hits==expected_hits and sum(x[2] for x in hits)==10:
    ok('endpointWaitTimeoutSec exact inventory','10 hits / 9 lines / 4 files')
else: fail('endpointWaitTimeoutSec exact inventory',repr(hits))

# Timeout migration bytes must be represented by exact slice-2 anchors, not the broad validator row.
timeout_map_expected={
 'endpoint timeout read':(315,315),
 'endpoint timeout min':(317,317),
 'endpoint timeout max':(319,319),
 'endpoint timeout write':(362,362),
}
timeout_map_seen={}
for m in blocks:
    num,slice_,rel,anchor,body=m.groups()
    if rel=='console_releases/4.5.0-s1/profile_store.py' and anchor in timeout_map_expected:
        rm=re.search(r'^- \*\*Точный диапазон:\*\* `(\d+)–(\d+)`$',body,re.M)
        timeout_map_seen[anchor]=(slice_, (int(rm.group(1)),int(rm.group(2))) if rm else None)
if set(timeout_map_seen)==set(timeout_map_expected) and all(timeout_map_seen[a]==('2',timeout_map_expected[a]) for a in timeout_map_expected):
    ok('profile_store timeout migration granularity','4 exact anchors in slice 2')
else:
    fail('profile_store timeout migration granularity',repr(timeout_map_seen))

# Slice 1 must not own the timeout migration acceptance IDs.
legacy_mig={f'ACC-MIG-{i:03d}' for i in range(10,19)}
leaked=[]
for m in blocks:
    num,slice_,rel,anchor,body=m.groups()
    if slice_=='1':
        refs=set(re.findall(r'`(ACC-[A-Z0-9-]+)`', re.search(r'^- \*\*Acceptance:\*\* (.+)$',body,re.M).group(1))) if re.search(r'^- \*\*Acceptance:\*\* (.+)$',body,re.M) else set()
        bad=sorted(refs & legacy_mig)
        if bad: leaked.append((num,rel,anchor,bad))
if leaked:
    fail('slice1 timeout migration ownership',repr(leaked))
else:
    ok('slice1 timeout migration ownership','no ACC-MIG-010..018 on slice1 rows')

# Exact barrier source facts + map statement.
cs=(ROOT/'console_releases/4.5.0-s1/console_server.py').read_text('utf-8').splitlines()
barrier_source=(cs[777].strip()=='try:' and '.observe(' in cs[778] and cs[779].strip()=='except Exception:' and cs[780].strip()=='pass')
if barrier_source: ok('api_delivery_poll observe/except lines (working base)','778 try; 779 observe; 780 except; 781 pass')
else: fail('api_delivery_poll observe/except lines', '\n'.join(f'{i+1}:{cs[i]}' for i in range(637,641)))
if 'до строки 778 и вне этого try' in text:
    ok('map version barrier placement','before 638/outside swallowed try')
else: fail('map version barrier placement','required phrase absent')

# The map's own self-summary must match the map. A document that states a
# count nobody verifies is the same defect class as a frozen design constant.
sec8=text.split('## 8. Самопроверка карты',1)[1]
dm=re.search(r'^- точек врезки/guard rows: \*\*(\d+)\*\*$',sec8,re.M)
da=re.search(r'^- acceptance definitions: \*\*(\d+)\*\*$',sec8,re.M)
if dm and int(dm.group(1))==len(blocks): ok('self-summary MAP count', dm.group(1))
else: fail('self-summary MAP count', f'declared {dm.group(1) if dm else "missing"}, actual {len(blocks)}')

# Decisions whose implementing symbols did not exist in the 830ab8c6 basis
# cannot be anchored yet. They must stay visible until they are.
DEBT_IDS=['DEBT-001','DEBT-002','DEBT-003','DEBT-004']
bad=[]
for d in DEBT_IDS:
    hits=len(re.findall(r'\b'+d+r'\b', sec3))+len(re.findall(r'\b'+d+r'\b', sec8))
    if hits!=1: bad.append(f'{d}: {hits} occurrences')
if not bad: ok('anchor debt accounted', f'{len(DEBT_IDS)} ids, each exactly once in section 3 or 8.1')
else: fail('anchor debt accounted', '; '.join(bad))

# Section 1 states the working base in prose. A table nobody compares is how
# the self-summary drifted before; this one is compared to the inventory.
sec1=text.split('### 1.1. Рабочее основание',1)[1].split('\n### ',1)[0] if '### 1.1. Рабочее основание' in text else ''
declared_rows=dict((m.group(1),(m.group(2),int(m.group(3)))) for m in
                   re.finditer(r'^\| `([^`]+)` \| `([0-9a-f]{64})` \| (\d+) \|$', sec1, re.M))
actual_rows={rel:(rec['sha256'],rec['lineCount']) for rel,rec in files.items()}
if declared_rows==actual_rows:
    ok('section 1 working base table', f'{len(actual_rows)} files match inventory')
else:
    miss=sorted(set(actual_rows)-set(declared_rows)); extra=sorted(set(declared_rows)-set(actual_rows))
    bad=[k for k in set(declared_rows)&set(actual_rows) if declared_rows[k]!=actual_rows[k]]
    fail('section 1 working base table', f'missing={miss} extra={extra} mismatched={bad}')

# Acceptance and rollback coverage.
sec5=text.split('## 5. Матрица приёмки',1)[1].split('## 6. Матрица отката',1)[0]
acc_rows=re.findall(r'^\| `(ACC-[A-Z0-9-]+)` \| (.*?) \| (.*?) \|$',sec5,re.M)
acc_ids=[x[0] for x in acc_rows]
sec6=text.split('## 6. Матрица отката по acceptance ID',1)[1].split('## 7. Порядок реализации',1)[0]
rb_ids=re.findall(r'^\| `(ACC-[A-Z0-9-]+)` \|',sec6,re.M)
if da and int(da.group(1))==len(acc_ids): ok('self-summary acceptance count', da.group(1))
else: fail('self-summary acceptance count', f'declared {da.group(1) if da else "missing"}, actual {len(acc_ids)}')
if len(acc_ids)==len(set(acc_ids)): ok('acceptance definitions unique',str(len(acc_ids)))
else: fail('acceptance definitions unique','duplicates present')
if len(rb_ids)==len(set(rb_ids)): ok('rollback ids unique',str(len(rb_ids)))
else: fail('rollback ids unique','duplicates present')
refs=set(map_acc_refs); defs=set(acc_ids); rbs=set(rb_ids)
if refs==defs: ok('MAP acceptance coverage',f'{len(refs)} refs/defs exact set')
else:
    fail('MAP acceptance coverage',f'missing defs={sorted(refs-defs)} unused defs={sorted(defs-refs)}')
if defs==rbs: ok('rollback coverage',f'{len(defs)} acceptance ids')
else: fail('rollback coverage',f'missing rollback={sorted(defs-rbs)} extra rollback={sorted(rbs-defs)}')

live={a:(d,s) for a,d,s in acc_rows if a.startswith('ACC-LIVE-')}
expected_live={'ACC-LIVE-001','ACC-LIVE-002','ACC-LIVE-003'}
if set(live)==expected_live and all('NOT RUN' in live[a][1] and 'NOT YET CLAIMED PASSED' in live[a][0] for a in expected_live):
    ok('live acceptance honesty','3 scenarios explicitly NOT RUN / not claimed passed')
else: fail('live acceptance honesty',repr(live))

# Required semantic guardrails in map.
required_phrases={
 'unsafe lease expiry':'истёк во время DRAIN',
 'staging not public':'staging — не Run и не попадает в list_runs',
 'binding fingerprint':'bindingId/null из read-only binding lookup',
 'intentional repeat':'repeatAsNew',
 'slice5+3b boundary only':'Граница 5+3b',
 'timeout membership semantics':'membership (`key in delivery`)',
 'explicit falsy does not default':'explicit falsy не подменяется default',
 'decorator convention':'Python start включает все строки декораторов символа',
}
for name,phrase in required_phrases.items():
    if phrase in text: ok(name,phrase)
    else: fail(name,f'missing phrase: {phrase}')

report=REPORT
report.parent.mkdir(parents=True, exist_ok=True)
with report.open('w',encoding='utf-8') as f:
    f.write('PAP2 4.5.0 IMPLEMENTATION MAP VERIFICATION\n')
    f.write(f'map={MAP}\n')
    f.write(f'checks={len(checks)} failures={len(failures)}\n\n')
    for name,detail in checks:
        f.write(f'PASS  {name}: {detail}\n')
    for name,detail in failures:
        f.write(f'FAIL  {name}: {detail}\n')
print(f'checks={len(checks)} failures={len(failures)}')
if failures:
    for x in failures: print('FAIL',*x,sep=' | ')
    print('report',report)
    sys.exit(1)
print('VERIFIED_CLEAN')
print('report',report)
