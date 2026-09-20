#!/usr/bin/env python3
"""Strict R7-off witness, with linkage/caller proof for armed-only local clones.

The original audit compared pre-R7 mainline against R7 (169 bodies). Comparing
R7 itself also sees two R7 ThreadCtx callbacks and two TU-local parser clones in
reorder.cc. Prove their armed-only provenance; keep the original byte normalizer
and every off-path occurrence, register, branch, immediate and layout operand.
"""
import argparse
import bisect
from collections import Counter
import json
from pathlib import Path
import re
import sys

import reorder_noop as audit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lbstall_artifacts import Elf


def off_roles(binary):
    elf = Elf(binary.path)
    owner, locals_ = '', set()
    for symbol in elf.symbols:
        if symbol['info'] & 15 == 4:
            owner = symbol['name']
        elif symbol['info'] & 15 == 2 and symbol['info'] >> 4 == 0 and owner == 'reorder.cc':
            locals_.add(symbol['value'])
    functions = {f['addr']: (name, f) for name, bodies in binary.groups.items() for f in bodies}
    starts = sorted(functions)
    callers = {a: set() for a in starts}
    for at, (_, asm) in binary.instructions.items():
        index = bisect.bisect_right(starts, at) - 1
        if index < 0: continue
        source = starts[index]
        if at >= source + functions[source][1]['size']: continue
        for ref in audit.REFERENCE.finditer(asm):
            target = int(ref[1], 16)
            if target in callers and target != source: callers[target].add(source)

    def armed(name):
        return '::r7_' in name or '_reordered(' in name

    def prove_local(at, visited):
        name = functions[at][0]
        if armed(name): return
        if at in visited: return
        if at not in locals_:
            raise AssertionError('excluded clone reachable from a non-R7 entry: ' + name)
        visited.add(at)
        for caller in callers[at]: prove_local(caller, visited)

    removed = []
    for name, bodies in list(binary.groups.items()):
        keep = []
        for body in bodies:
            if not audit.category(name):
                keep.append(body)
                continue
            reason = None
            ancestors = set()
            if armed(name): reason = 'explicit R7 specialization'
            elif body['addr'] in locals_:
                prove_local(body['addr'], ancestors)
                reason = 'STB_LOCAL in reorder.cc; all incoming paths local or armed'
            if reason:
                if audit.category(name):
                    removed.append(dict(name=name, address=hex(body['addr']), reason=reason,
                                        local_ancestors=[functions[x][0] for x in sorted(ancestors)]))
            else: keep.append(body)
        if keep: binary.groups[name] = keep
        else: del binary.groups[name]
    return removed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre')
    parser.add_argument('post')
    parser.add_argument('output')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    audit.self_test()
    pre = audit.Binary(args.pre, out, literal_pools=True)
    post = audit.Binary(args.post, out, literal_pools=True)
    excluded = {'pre': off_roles(pre), 'post': off_roles(post)}
    rows = audit.compare(pre, post, out)
    # The boot-selected db0 runtime duplicates this inventory. The current
    # reference has 168 bodies per variant; the old single-runtime audit had 169.
    expected = {'tomo': 168, 'tomo_db0': 168} if any(
        'tomo_db0::' in row['name'] for row in rows) else {'tomo': 169}
    counts = Counter('tomo_db0' if 'tomo_db0::' in row['name'] else 'tomo' for row in rows)
    assert counts == expected, f'off-path inventory changed: {counts}, expected {expected}'
    def inventory(binary):
        return {name: len(bodies) for name, bodies in binary.groups.items() if audit.category(name)}
    assert inventory(pre) == inventory(post), 'off-path symbols/clone counts changed'
    passed = all(row['equal'] for row in rows)
    result = dict(pre=str(pre.path), post=str(post.path), pre_sha256=pre.sha256,
                  post_sha256=post.sha256, literal_pools=True, excluded_armed=excluded,
                  expected_bodies=expected, rows=rows, strict_noop=passed)
    (out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    for row in rows:
        if not row['equal']: print('DIFF', row['diff'], row['name'])
    print(f'strict_noop={passed}: {sum(r["equal"] for r in rows)}/{len(rows)} identical bodies')
    raise SystemExit(0 if passed else 1)
