#!/usr/bin/env python3
"""Verify A6's raw tokens, literal bytes and tool-marker boundaries against frozen PRE."""
from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

PRE = '5c3631281815c1652b3894d1736840c8466a5015'
BASE = '9a09e5919092cc5e33aaf1e49e55994bdf8439b5'
OWNED = '''src/core/atomic_admission.h
src/core/atomic_parked.h
src/core/atomic_tripwire.h
src/core/ex_execute.inc
src/core/ex_loop.h
src/core/ex_txn_chain.inc
src/core/exec1s.h
src/exec/exqueue.h
src/exec/masked_queue.h
src/exec/op.h'''.splitlines()
GENERATED = {'src/core/reorder.cc', 'src/core/io_loop.h'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode()


def literals(source):
    return tuple(m[0] for m in cpp.LEXER.finditer(source)
                 if m.lastgroup in ('raw', 'string'))


def markers(source):
    ends = [t.end for t in cpp.lex(source)]
    return tuple((m[0], bisect_left(ends, m.start())) for m in cpp.LEXER.finditer(source)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])


def outside_generated(source):
    return re.sub(r'(?<=// BEGIN R7 GENERATED ENVELOPES)[\s\S]*?(?=// END R7 GENERATED ENVELOPES)',
                  '', source)


def main():
    renames = json.loads((ROOT / 'docs/readability-a6/renames.json').read_text())
    changed = git('diff', '--name-only', BASE, '--', 'src').splitlines()
    assert set(changed) <= set(OWNED) | GENERATED, changed
    rows = []
    for filename in changed:
        original = git('show', f'{PRE}:{filename}')
        base = git('show', f'{BASE}:{filename}')
        current = (ROOT / filename).read_bytes().decode()
        assert literals(original) == literals(current), f'{filename}: literal bytes changed'
        assert markers(base) == markers(current), f'{filename}: tool markers moved/changed'
        if filename in GENERATED:
            assert outside_generated(base) == outside_generated(current), filename
        normalized = current
        for item in renames:
            if item['file'] != filename:
                continue
            _, start, end = cpp.function_span(normalized, item['function'])
            inverse = {new: old for old, new in item['names'].items()}
            normalized = normalized[:start] + cpp.rename(normalized[start:end], inverse) + normalized[end:]
        expected = tuple(t.text for t in cpp.lex(original))
        actual = tuple(t.text for t in cpp.lex(normalized))
        assert expected == actual, f'{filename}: preprocessing tokens changed'
        rows.append({'file': filename, 'tokens': len(actual), 'literal_tokens': len(literals(current)),
                     'token_sha256': hashlib.sha256(json.dumps(actual).encode()).hexdigest(),
                     'tokens_equal_after_scoped_renames': True, 'literals_byte_identical': True,
                     'tool_markers_unchanged_from_lane_base': True})
    print(json.dumps({'pre': PRE, 'lane_base': BASE, 'files': rows,
                      'renamed_bindings': sum(len(r['names']) for r in renames)}, indent=2))


if __name__ == '__main__':
    main()
