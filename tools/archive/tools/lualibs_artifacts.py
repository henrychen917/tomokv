#!/usr/bin/env python3
"""Offline CC4.7 PAD-A, identity and serverless per-state memory evidence."""
import argparse
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import psfix_artifacts
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/lualibs'
BUILD = ROOT / 'build'
PRE = BUILD / 'tomokv-lualibs-pre'
POST = BUILD / 'tomokv'
PAD = BUILD / 'tomokv-lualibs-pad-a'
HOT = re.compile(r'::cmd_(?:get|set)(?:\(|<)|::cmd_xshard_only|'
                 r'::xshard_(?:prepare|execute|complete|store_string|queue_commit|flush_commits)')


def pad():
    elf = Elf(POST)
    bodies = [s for s in elf.symbols if 'open_helper_libraries' in s['name'] and s['size']]
    assert len(bodies) == 2, bodies
    data = bytearray(elf.data)
    changes = []
    for symbol in bodies:
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        assert data[offset] != 0xc3
        changes.append(dict(symbol=symbol['name'], address=symbol['value'], offset=offset,
                            old=data[offset], new=0xc3))
        data[offset] = 0xc3  # x86-64 RET: leave the redis table and stack untouched.
    PAD.write_bytes(data); PAD.chmod(0o755)
    assert len(data) == len(elf.data)
    assert sum(a != b for a, b in zip(data, elf.data)) == 2
    (OUT / 'pad-a.json').write_text(json.dumps(dict(
        kind='A: PRE behaviour with POST text size/layout', patches=changes,
        post_sha256=hashlib.sha256(elf.data).hexdigest(),
        pad_sha256=hashlib.sha256(data).hexdigest()), indent=2) + '\n')


def identity():
    sys.path.insert(0, str(ROOT / 'tests'))
    import reorder_noop
    hot_rows = []
    for namespace in ('src', 'db0/src'):
        for unit in ('t_string', 'xshard'):
            relative = Path(namespace) / 'cmd' / (unit + '.o')
            old_elf = psfix_artifacts.audit.Elf(BUILD / 'lualibs-pre' / relative)
            new_elf = psfix_artifacts.audit.Elf(BUILD / relative)
            old, new = old_elf.functions(), new_elf.functions()
            symbols = sorted(old)
            names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n', text=True).splitlines()
            for symbol, name in zip(symbols, names):
                if HOT.search(name):
                    hot_rows.append(dict(object=str(relative), name=name,
                        equal=symbol in new and old_elf.canonical(old[symbol]) == new_elf.canonical(new[symbol])))
    assert hot_rows and any('::xshard_execute(' in r['name'] for r in hot_rows)
    (OUT / 'hot-identity.json').write_text(json.dumps(hot_rows, indent=2) + '\n')
    scratch = BUILD / 'lualibs-identity'; scratch.mkdir(exist_ok=True)
    before = reorder_noop.Binary(PRE, scratch, literal_pools=True)
    after = reorder_noop.Binary(POST, scratch, literal_pools=True)
    changed = []
    compared = 0
    for name in sorted(set(before.groups) | set(after.groups)):
        old = sorted(before.groups.get(name, []), key=lambda b: b['addr'])
        new = sorted(after.groups.get(name, []), key=lambda b: b['addr'])
        compared += 1
        if [(b['ins'], b['encodings']) for b in old] == [(b['ins'], b['encodings']) for b in new]:
            continue
        def lines(bodies):
            return [f'{i}: {instruction} | {encoding}\n' for i,b in enumerate(bodies)
                    for instruction,encoding in zip(b['ins'],b['encodings'])]
        changed.append(dict(name=name, hot=bool(HOT.search(name)),
                            pre_size=sum(b['size'] for b in old), post_size=sum(b['size'] for b in new),
                            diff=''.join(difflib.unified_diff(lines(old),lines(new),fromfile='PRE',tofile='POST'))))
    with gzip.open(OUT / 'linked-differences.json.gz', 'wt') as f:
        json.dump(changed, f, indent=2)
    summary = dict(compared=compared, changed=len(changed),
                   changed_names=[r['name'] for r in changed],
                   hot_object_compared=len(hot_rows), hot_object_changed=[r for r in hot_rows if not r['equal']],
                   hot_linked_changed=[r['name'] for r in changed if r['hot']],
                   pre_sha256=before.sha256, post_sha256=after.sha256,
                   normalizers=['tools/psfix_artifacts.py', 'tests/reorder_noop.py (literal pools enabled)'])
    (OUT / 'identity.json').write_text(json.dumps(summary, indent=2) + '\n')
    for path in scratch.glob('*.objdump'):
        path.unlink()
    print(json.dumps({k:v for k,v in summary.items() if k!='changed_names'},indent=2),flush=True)


def memory():
    # All other objects are unchanged production code. Substituting only the
    # frozen PRE scripting objects selects the exact PRE sandbox constructor.
    objects = [p for ns in ('src', 'db0/src') for p in sorted((BUILD/ns).rglob('*.o'))
               if p.relative_to(BUILD/ns).as_posix() not in ('main.o','core/version.o')]
    helpers = sorted((BUILD / 'third_party/lua/helpers').glob('*.o'))
    results = {}
    for arm in ('pre','post'):
        selected = [BUILD/'lualibs-pre'/p.relative_to(BUILD) if arm=='pre' and p.name=='scripting.o'
                    else p for p in objects]
        binary = BUILD / ('lualibs-memory-' + arm)
        command = ['g++','-std=c++20','-O2','-g','-I.','tests/lualibs_memory.cc',
                   *map(str,selected), *([] if arm=='pre' else map(str,helpers)),
                   '-ljemalloc','-lssl','-lcrypto','-luring','-pthread','-lm','-o',str(binary)]
        subprocess.run(command,cwd=ROOT,check=True)
        raw = subprocess.check_output([str(binary)],text=True)
        results[arm] = [json.loads(line) for line in raw.splitlines()]
        binary.unlink()
    (OUT / 'memory.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('pad','identity','memory'))
    args = p.parse_args()
    globals()[args.action]()
