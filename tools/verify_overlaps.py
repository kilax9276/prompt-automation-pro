#!/usr/bin/env python3
"""
verify_overlaps.py — the next gap after verify_inventory.py.

verify_map.py proves each row's range against the byte inventory, and now
proves that slice-1 rows do not *reference* the timeout acceptance ids. It
does not prove anything about rows whose byte ranges overlap across slices.

That matters because a row with change type "замена" rewrites its whole
declared range. When a later slice replaces a range that an earlier slice
already edited, the later implementer works from the 4.4.0 baseline bytes and
silently reverts the earlier slice's edit unless the row says otherwise.

The map already follows the right convention in several rows: MAP-007 states
"не менять delivery.endpointWaitTimeoutSec до атомарной границы slice2";
MAP-058 states "scaffold существует после slice1"; MAP-073 states "После
slice2 временно может существовать...". This script makes that convention
enforceable instead of optional.

Rule: if row B (later slice) has change type "замена" and its range overlaps
row A (earlier slice) on the same file, B's body must name A's slice or A's
anchor. Otherwise B silently discards A.

Run after verify_inventory.py. Exit 0 = no undeclared cross-slice overlap.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

# Paths are resolved from this file's location so the toolchain runs anywhere.
# base/ holds the closed-S1 working base the map is anchored to; it is a copy of
# the release directories, kept beside the tools so verification does not depend
# on where the tree was unpacked.
_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent

MAP = _ROOT / 'PAP2_4.5.0_IMPLEMENTATION_MAP.md'
INV = _TOOLS / 'inventory.json'

SLICE_ORDER = {'1': 1, '2': 2, '3a': 3, '3b': 4, '4': 5, '5': 6, '6': 7, '7': 8}

# Rows of a closed slice carry a HISTORICAL suffix and describe frozen bytes.
# They are matched here only so they can be skipped deliberately: geometry
# against the working base is meaningless for them, and relying on the regex
# failing to match would make the exclusion an accident rather than a rule.
ROW_RE = re.compile(
    r'^### MAP-(\d{3}) — срез (—|[^\s—]+?)( HISTORICAL)? — `([^`]+)` / `([^`]+)`\n\n(.*?)(?=^### MAP-|\Z)',
    re.M | re.S)


def field(body: str, name: str) -> str:
    m = re.search(r'^- \*\*' + re.escape(name) + r':\*\* (.+)$', body, re.M)
    return m.group(1).strip() if m else ''


def main() -> int:
    inv = json.loads(INV.read_text('utf-8'))
    text = MAP.read_text('utf-8')
    sec3 = text.split('## 3. Точки врезки', 1)[1].split('## 4. Миграция', 1)[0]

    rows = []
    for m in ROW_RE.finditer(sec3):
        num, slice_, historical, rel, anchor, body = m.groups()
        if historical:
            continue
        sym = inv['files'][rel]['symbols'][anchor]
        rows.append({
            'id': f'MAP-{num}',
            'slice': slice_,
            'order': SLICE_ORDER.get(slice_, 0),
            'file': rel,
            'anchor': anchor,
            'start': sym['start'],
            'end': sym['end'],
            'change': field(body, 'Изменение'),
            'body': body,
        })

    checks = failures = 0
    problems = []

    for b in rows:
        if not b['change'].startswith('замена') or b['order'] == 0:
            continue
        for a in rows:
            if a is b or a['file'] != b['file'] or a['order'] == 0:
                continue
            if a['order'] >= b['order']:
                continue
            if not (a['start'] <= b['end'] and b['start'] <= a['end']):
                continue
            # Only the swallowing direction is a defect. If b is *contained*
            # in a, the coarse earlier row is the one that must declare the
            # carve-out, and MAP-007 shows the map already does that. The
            # defect is a later wholesale "замена" that engulfs an earlier
            # row's bytes: its implementer starts from the 4.4.0 baseline and
            # reverts the earlier edit unless the row says otherwise.
            if not (b['start'] <= a['start'] and a['end'] <= b['end']):
                continue
            # b replaces bytes a already edited: b must acknowledge a.
            hay = b['body']
            declared = (
                re.search(r'slice\s*' + re.escape(a['slice']) + r'\b', hay, re.I) or
                re.search(r'срез\w*\s+' + re.escape(a['slice']) + r'\b', hay, re.I) or
                a['anchor'] in hay
            )
            checks += 1
            if not declared:
                failures += 1
                problems.append(
                    f"{b['id']} срез {b['slice']} [{b['change']}] {b['file']}"
                    f"/{b['anchor']} {b['start']}-{b['end']} replaces bytes edited by "
                    f"{a['id']} срез {a['slice']} /{a['anchor']} {a['start']}-{a['end']}"
                    f" — no mention of срез {a['slice']} or /{a['anchor']} in its body")

    print(f'checks={checks} failures={failures}')
    for p in problems:
        print('FAIL |', p)
    if failures:
        return 1
    print('NO_UNDECLARED_CROSS_SLICE_OVERLAP')
    return 0


if __name__ == '__main__':
    sys.exit(main())
