#!/usr/bin/env python3
"""Compile-only, complete-body comparison against the merged perfex POST."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ccfix_audit import audit

COLD = re.compile(r'::(?:FlatStore::(?:clear|clear_during_snapshot|storesize_clear)\(|'
                  r'(?:\(anonymous namespace\)::)?cmd_flush\()')


def inventory(path):
    elf = audit.Elf(path)
    functions = elf.functions()
    symbols = sorted(functions)
    names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n', text=True).splitlines()
    return {symbol: dict(name=name, body=elf.canonical(functions[symbol]),
                         size=functions[symbol]['size']) for symbol, name in zip(symbols, names)}


def main():
    assert os.sched_getaffinity(0) <= set(range(112, 128))
    obj, *values = sys.argv[1:]
    old = inventory(ROOT / 'build/perfex2/pre' / obj)
    log = ROOT / 'docs/perfex2/post-build.log'
    lines = (log.read_text() if log.exists() else
             gzip.decompress(log.with_suffix('.log.gz').read_bytes()).decode()).splitlines()
    commands = [shlex.split(line) for line in lines
                if line.startswith('g++ ') and line.endswith(' -o build/' + obj)]
    assert len(commands) == 1
    folder = ROOT / 'build/perfex2/budgets' / obj.replace('/', '_')
    if os.environ.get('PERFEX_BUDGET_TAG'):
        folder /= os.environ['PERFEX_BUDGET_TAG']
    folder.mkdir(parents=True, exist_ok=True)
    def trial(value):
        path = folder / (value + '.o')
        cmd = ['large-unit-insns=' + value if word.startswith('large-unit-insns=')
               else '-g0' if word == '-g' else word for word in commands[0]]
        cmd[cmd.index('-o') + 1] = str(path)
        with (folder / (value + '.log')).open('w') as stream:
            subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        new = inventory(path)
        changed = []
        for symbol in sorted(old.keys() | new.keys()):
            a, b = old.get(symbol), new.get(symbol)
            if a and b and a['body'] == b['body']: continue
            name = (a or b)['name']
            changed.append(dict(name=name, pre_size=a['size'] if a else 0,
                                post_size=b['size'] if b else 0, cold_clear=bool(COLD.search(name))))
        row = dict(object=obj, value=int(value), command=cmd, changed=changed,
                   source_sha256={str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                  for p in ('src/store/flatstore.h', 'src/cmd/storesize.cc')},
                   unexpected=[x for x in changed if not x['cold_clear']])
        (folder / (value + '.json')).write_text(json.dumps(row, indent=2) + '\n')
        print(json.dumps(dict(object=obj, value=int(value), unexpected=row['unexpected'])), flush=True)
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(trial, values))


if __name__ == '__main__':
    main()
