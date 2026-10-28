#!/usr/bin/env python3
"""Offline linked-body inventory using the gate's strict instruction normalizer.

No source-line immediate, opcode, branch condition, member offset or register is
masked. Resolved address operands and literal pools use reorder_noop unchanged.
References are the supplied frozen binaries; no reference build is required.
"""
from concurrent.futures import ProcessPoolExecutor
import gzip
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import HOT as GENERAL_HOT

OUT = ROOT / 'build/rlfix4/identity'
REFS = {a: '/home/user/Projects/bench-bins/tomokv-headline-'+rev for a,rev in [('anchor','991d48f65'),('wave6','05a5e01a9'),('wave7','3700b51d7'),('base','a214652ec')]}

HOT = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)|prepare_captured_local_mget|xshard_.*mset')
COUNTED_HOT = set()


def _inventory(path):
    path = Path(path)
    digest = audit.digest(path)
    folder = OUT / digest
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / 'inventory.json.gz'
    if cache.exists():
        with gzip.open(cache, 'rt') as stream:
            return json.load(stream)
    binary = audit.Binary(path, folder, literal_pools=True)
    groups = {}
    for name, bodies in binary.groups.items():
        groups[name] = [dict(size=b['size'], address=hex(b['addr']),
                            digest=hashlib.sha256(json.dumps([b['ins'], b['encodings']]).encode()).hexdigest())
                        for b in sorted(bodies, key=lambda b: b['addr'])]
    result = dict(path=str(path), sha256=digest, groups=groups)
    with gzip.open(cache, 'wt') as stream:
        json.dump(result, stream)
    for f in folder.glob('*.objdump'):
        f.unlink()
    return result


def inventory(path):
    path = Path(path)
    folder = OUT / audit.digest(path)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'inventory.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = folder / 'inventory.json.gz'
        if cache.exists():
            try:
                with gzip.open(cache, 'rt') as stream: json.load(stream)
            except (OSError, EOFError, ValueError):
                cache.unlink()
        return _inventory(path)


def signature(rows):
    return [r['digest'] for r in rows]


def compare(post, refs):
    rows = []
    head = refs['headline']['groups']
    names = sorted(set(head) | set(post['groups']))
    for name in names:
        before, after = head.get(name, []), post['groups'].get(name, [])
        same = signature(before) == signature(after)
        matches = [arm for arm, ref in refs.items()
                   if not arm.startswith('baseline_') and signature(ref['groups'].get(name, [])) == signature(after)]
        changed_lanes = [arm for arm, ref in refs.items() if arm != 'headline' and not arm.startswith('baseline_') and
                         signature(ref['groups'].get(name, [])) != signature(refs.get('baseline_'+arm, refs['headline'])['groups'].get(name, []))]
        rows.append(dict(name=name, hot=bool(GENERAL_HOT.search(name) or HOT.search(name) or
                                           re.search(r'::reply_(?:int|bulk|array_header)<|Op::Sink::reserve\(', name) or
                                           re.search(r'ExLoopT<.*>::run\(', name) or name in COUNTED_HOT),
                         counted_command_scope=name in COUNTED_HOT,
                         command_hot=bool(HOT.search(name)), equal=same,
                         headline_sizes=[r['size'] for r in before], post_sizes=[r['size'] for r in after],
                         matches=matches, changed_lanes=changed_lanes))
    return rows



if __name__ == '__main__':
    with ProcessPoolExecutor(max_workers=4) as pool:
        inventories=list(pool.map(inventory,REFS.values()))
    dest=ROOT/'docs/rlfix4/identity';dest.mkdir(parents=True,exist_ok=True)
    for label,inv in zip(REFS,inventories):
        with gzip.open(dest/(label+'.json.gz'),'wt') as f:json.dump(inv,f)
    print('four headline inventories saved',flush=True)
