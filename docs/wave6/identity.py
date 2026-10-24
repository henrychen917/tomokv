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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import HOT as GENERAL_HOT

OUT = ROOT / 'build/wave6/identity'
REFS = {'headline': '/home/user/Projects/bench-bins/tomokv-headline-ef5204b2e', 'execfair': '/home/user/Projects/bins/execfair-post-df6bef84', 'notifycompat': '/home/user/Projects/bins/notifycompat-post-76f31351', 'serverfix': '/home/user/Projects/bins/serverfix-post-c0b52731', 'dispatchfix': '/home/user/Projects/bins/dispatchfix-post-e7385e0c', 'datafix1': '/home/user/Projects/bins/datafix1-post-b05021db', 'prefetch_delete': '/home/user/Projects/bins/prefetch-del-b90cff5e', 'baseline_dispatchfix': '/home/user/Projects/bins/dispatchfix-pre-2d8265e5', 'baseline_datafix1': '/home/user/Projects/bins/datafix1-pre-194bcfa2'}

HOT = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<)|prepare_captured_local_mget|xshard_.*mset')


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
                                           re.search(r'ExLoopT<.*>::run\(', name)),
                         command_hot=bool(HOT.search(name)), equal=same,
                         headline_sizes=[r['size'] for r in before], post_sizes=[r['size'] for r in after],
                         matches=matches, changed_lanes=changed_lanes))
    return rows


def main():
    with ProcessPoolExecutor(max_workers=6) as pool:
        inventories = list(pool.map(inventory, [*REFS.values(), Path(sys.argv[1]) if len(sys.argv)>1 else ROOT / 'build/tomokv']))
    refs = dict(zip(REFS, inventories[:-1]))
    post = inventories[-1]
    rows = compare(post, refs)
    dest = ROOT / (sys.argv[2] if len(sys.argv)>2 else 'docs/wave6/identity')
    dest.mkdir(parents=True, exist_ok=True)
    changed = [r for r in rows if not r['equal']]
    for r in changed:
        if r['matches']:
            r['reason'] = 'Exact linked body from ' + ', '.join(r['matches']) + '; lane change retained.'
        elif len(r['changed_lanes']) > 1:
            r['reason'] = 'Composition of ' + ', '.join(r['changed_lanes']) + '; residual instructions/layout require merit review.'
        elif r['changed_lanes']:
            r['reason'] = r['changed_lanes'][0] + ' changes this body; merged compiler propagation differs from isolated POST.'
        else:
            r['reason'] = 'Unedited body: compiler/link layout propagation in merged source; no single optimizer decision isolated.'
    summary = dict(function_groups=len(rows), unchanged=sum(r['equal'] for r in rows), changed=len(changed),
                   lane_equal=sum(bool(r['matches']) for r in changed),
                   residual=sum(not r['matches'] for r in changed),
                   hot_groups=sum(r['hot'] for r in rows), hot_headline=sum(r['hot'] and r['equal'] for r in rows),
                   hot_lane=sum(r['hot'] and not r['equal'] and bool(r['matches']) for r in rows),
                   command_hot_groups=sum(r['command_hot'] for r in rows),
                   command_hot_headline=sum(r['command_hot'] and r['equal'] for r in rows),
                   command_hot_lane=sum(r['command_hot'] and not r['equal'] and bool(r['matches']) for r in rows),
                   hot_residual=[r for r in changed if r['hot'] and not r['matches']],
                   references={arm: {k:v for k,v in inv.items() if k!='groups'} for arm,inv in refs.items()},
                   post={k:v for k,v in post.items() if k!='groups'})
    (dest/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    with gzip.open(dest/'all-bodies.json.gz', 'wt') as stream:
        json.dump(rows, stream, indent=2)
    (dest/'changed-bodies.json').write_text(json.dumps(changed, indent=2)+'\n')
    (dest/'changed-bodies.md').write_text('\n'.join([
        '# Linked body differences', '',
        'Strict gate instruction/address normalization; local clone multiplicity retained. Identity is a proxy.', '',
        '| Function | Headline sizes | Merged sizes | Reason |', '|---|---|---|---|',
        *[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in changed]])+'\n')
    print(json.dumps({k:v for k,v in summary.items() if not isinstance(v,(dict,list))}), flush=True)


if __name__ == '__main__':
    main()
