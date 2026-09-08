#!/usr/bin/env python3
"""
verify_inventory.py — closes the one gap in verify_map.py.

verify_map.py checks map ranges against inventory.json, and inventory.json
against nothing. This script re-derives every symbol range from the source
bytes and compares it to inventory.json, so the chain becomes

    source bytes -> inventory.json -> implementation map

instead of inventory.json -> map with inventory.json unproven.

Run it BEFORE verify_map.py. Exit 0 = inventory matches bytes.
"""
from __future__ import annotations
import ast, json, re, sys
from pathlib import Path

# Paths are resolved from this file's location so the toolchain runs anywhere.
# The working base is the release directories themselves — one copy, not a
# duplicate that could drift away from the tree the map describes.
_TOOLS = Path(__file__).resolve().parent
_ROOT = _TOOLS.parent

ROOT = _ROOT
INV  = _TOOLS / 'inventory.json'

checks, failures = [], []
ok   = lambda n, d='': checks.append((n, d))
fail = lambda n, d='': failures.append((n, d))


def py_ranges(path: Path) -> dict[str, tuple[int, int]]:
    """Qualified-name -> (start, end). Decorators included in start.

    Keyed by qualified name first; a bare name is registered only if it does
    not collide with an already-registered def. This is what my first pass got
    wrong: a local variable `pin = ...` overwrote the method `pin`, producing
    four phantom mismatches.
    """
    tree = ast.parse(path.read_text('utf-8'))
    defs: dict[str, tuple[int, int]] = {}
    assigns: dict[str, tuple[int, int]] = {}

    def walk(node, prefix=''):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                span = (start, ch.end_lineno)
                defs[prefix + ch.name] = span
                defs.setdefault(ch.name, span)
                walk(ch, prefix=prefix + ch.name + '.')
            else:
                if isinstance(ch, ast.Assign):
                    targets = ch.targets
                elif isinstance(ch, ast.AnnAssign):
                    targets = [ch.target]
                else:
                    targets = []
                for t in targets:
                    if isinstance(t, ast.Name):
                        assigns.setdefault(t.id, (ch.lineno, ch.end_lineno))
                walk(ch, prefix=prefix)

    walk(tree)
    for name, span in assigns.items():
        defs.setdefault(name, span)
    return defs


def strip_js(line: str) -> str:
    line = re.sub(r'//.*', '', line)
    line = re.sub(r'"(\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(\\.|[^'\\])*'", "''", line)
    line = re.sub(r'`[^`]*`', '``', line)
    return line


def main() -> int:
    inv = json.loads(INV.read_text('utf-8'))
    files = inv['files']

    for rel, rec in files.items():
        path = ROOT / rel
        if not path.exists():
            fail(f'{rel}', 'missing from source tree')
            continue
        raw = path.read_bytes()
        n_lines = raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)
        if n_lines != rec['lineCount']:
            fail(f'{rel} lineCount', f'{n_lines} vs declared {rec["lineCount"]}')
        else:
            ok(f'{rel} lineCount', str(n_lines))

        text_lines = path.read_text('utf-8').splitlines()
        derived = py_ranges(path) if rel.endswith('.py') else {}

        for anchor, r in rec.get('symbols', {}).items():
            label = f'{rel}/{anchor}'
            start, end = r['start'], r['end']

            if end > n_lines or start < 1 or start > end:
                fail(f'{label} bounds', f'{start}-{end} vs file {n_lines} lines')
                continue

            # Python symbol: must match the AST exactly.
            if anchor in derived:
                a_start, a_end = derived[anchor]
                if (a_start, a_end) == (start, end):
                    ok(f'{label} ast range', f'{start}-{end}')
                elif a_end == end and a_start < start and \
                        text_lines[a_start - 1].lstrip().startswith('@'):
                    # The only benign divergence: the range omits decorator
                    # lines. Benign today only while the anchor is unused by
                    # the map; as an injection point the decorator is a byte
                    # the change may have to touch.
                    fail(f'{label} decorator excluded',
                         f'declared {start}-{end}, symbol starts {a_start} '
                         f'({text_lines[a_start - 1].strip()})')
                else:
                    fail(f'{label} ast range',
                         f'declared {start}-{end}, ast {derived[anchor]}')
                continue

            # Otherwise the anchor must carry a needle, and the needle must
            # actually sit on the declared start line.
            needle = r.get('needle')
            if not needle:
                fail(f'{label} anchor', 'not an AST symbol and no needle')
                continue
            occ = [i + 1 for i, l in enumerate(text_lines) if needle in l]
            if occ != r.get('hits'):
                fail(f'{label} hits', f'recorded {r.get("hits")}, actual {occ}')
                continue
            if start not in occ:
                fail(f'{label} needle', f'absent on declared start {start}')
                continue
            ok(f'{label} needle', f'{start}-{end}, hits {occ}')

            # Multi-line JS/HTML ranges must close: unbalanced braces or
            # parens mean the end line was guessed, not derived.
            if end - start >= 2 and rel.endswith('.js'):
                seg = [strip_js(x) for x in text_lines[start - 1:end]]
                brace = sum(x.count('{') - x.count('}') for x in seg)
                paren = sum(x.count('(') - x.count(')') for x in seg)
                if brace or paren:
                    fail(f'{label} balance', f'brace={brace:+d} paren={paren:+d}')
                else:
                    ok(f'{label} balance', 'closed')

    # Non-unique needles are legal but must be visible: an ambiguous anchor is
    # a place where a future edit can silently move the wrong line.
    ambiguous = [
        (rel, a) for rel, rec in files.items()
        for a, r in rec.get('symbols', {}).items()
        if len(r.get('hits') or []) > 1
    ]

    print(f'checks={len(checks)} failures={len(failures)}')
    if ambiguous:
        print(f'note: {len(ambiguous)} anchors have non-unique needles '
              f'(recorded, not an error):')
        for rel, a in ambiguous:
            print(f'  {rel}/{a}')
    if failures:
        for n, d in failures:
            print('FAIL', n, d, sep=' | ')
        return 1
    print('INVENTORY_MATCHES_BYTES')
    return 0


if __name__ == '__main__':
    sys.exit(main())
