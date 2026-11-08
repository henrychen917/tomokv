#!/usr/bin/env python3
"""Read-only token, literal and tool-marker audit for the nine A5 production files."""
from bisect import bisect_left
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

FILES = tuple('src/core/' + name for name in (
    'cfgfix.cc', 'cfgfix.h', 'config.h', 'live_config.h', 'server.h',
    'shard.h', 'thread.h', 'version.cc', 'version.h'))
BASE = '9a09e5919092cc5e33aaf1e49e55994bdf8439b5'
FROZEN = '5c3631281815c1652b3894d1736840c8466a5015'


def literals(source):
    return tuple(m[0] for m in cpp.LEXER.finditer(source)
                 if m.lastgroup in ('string', 'raw'))


def markers(source):
    ends = [t.end for t in cpp.lex(source)]
    return tuple((m[0], bisect_left(ends, m.start()))
                 for m in cpp.LEXER.finditer(source)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])


def main():
    rows = []
    for name in FILES:
        current = (ROOT / name).read_bytes().decode()
        tokens = tuple(t.text for t in cpp.lex(current))
        row = {'path': name, 'tokens': len(tokens), 'literals': len(literals(current))}
        for ref in (BASE, FROZEN):
            previous = subprocess.check_output(['git', 'show', ref + ':' + name], cwd=ROOT).decode()
            assert tuple(t.text for t in cpp.lex(previous)) == tokens, (name, ref, 'tokens')
            assert literals(previous) == literals(current), (name, ref, 'literal bytes')
            if ref == BASE:
                assert markers(previous) == markers(current), (name, 'tool marker boundary')
                row['edited'] = previous != current
        row['token_sha256'] = hashlib.sha256(json.dumps(tokens).encode()).hexdigest()
        rows.append(row)
    print(json.dumps({'base': BASE, 'frozen': FROZEN, 'renames': [],
                      'result': 'PASS', 'files': rows}, indent=2))


if __name__ == '__main__':
    main()
