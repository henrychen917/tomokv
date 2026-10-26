#!/usr/bin/env python3
"""Offline WB4.1 linked-body identity and exact-layout kind-A control."""
import argparse
import difflib
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop
from iofix_identity import MAIN
import iofix_pad


def identity(args):
    args.output.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / 'build/iofix3/identity-scratch'
    scratch.mkdir(exist_ok=True)
    pre = reorder_noop.Binary(args.pre, scratch, literal_pools=True)
    post = reorder_noop.Binary(args.post, scratch, literal_pools=True)
    rows, changes = [], []
    for name in sorted(pre.groups.keys() | post.groups.keys()):
        old = sorted(pre.groups.get(name, []), key=lambda body: body['addr'])
        new = sorted(post.groups.get(name, []), key=lambda body: body['addr'])
        aliases = [alias for body in old + new for alias in body['aliases']]
        hot = bool(MAIN.search(name) or any(MAIN.search(alias) for alias in aliases))
        before = [(body['ins'], body['encodings']) for body in old]
        after = [(body['ins'], body['encodings']) for body in new]
        equal = bool(old and new and before == after)
        row = dict(name=name, hot=hot, equal=equal,
                   pre_sizes=[body['size'] for body in old],
                   post_sizes=[body['size'] for body in new])
        rows.append(row)
        if not equal:
            def lines(bodies):
                return [f'clone {i}: {ins} | {encoding}\n'
                        for i, body in enumerate(bodies)
                        for ins, encoding in zip(body['ins'], body['encodings'])]
            changes.append(dict(row, diff=''.join(difflib.unified_diff(
                lines(old), lines(new), fromfile='PRE', tofile='POST'))))
    for filename, value in [('all-bodies.json.gz', rows), ('changed-bodies.json.gz', changes)]:
        with gzip.open(args.output / filename, 'wt') as out:
            json.dump(value, out, indent=2)
    hot = [row for row in rows if row['hot']]
    summary = dict(pre_sha256=pre.sha256, post_sha256=post.sha256,
                   normalizer='tests/reorder_noop.py Binary(literal_pools=True), unchanged',
                   linked_groups=len(rows), changed=len(changes), hot_compared=len(hot),
                   hot_changed=[row for row in hot if not row['equal']])
    (args.output / 'hot-bodies.json').write_text(json.dumps(hot, indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for path in scratch.glob('*.objdump'):
        path.unlink()
    print(json.dumps(summary, indent=2), flush=True)
    assert hot and not summary['hot_changed'], 'main-command body drift; see retained diffs'


def pad(args):
    # Reuse the existing guarded DWARF/disassembly patcher. It verifies every
    # emitted FIFO/R7 predicate site, then checks unchanged sections and symbols.
    # Force work=1 on deferral: PRE never reaches pending-FIFO grace/parking.
    sys.argv = ['iofix_pad.py', '--pre', str(args.pre), '--post', str(args.post),
                '--output', str(args.output), '--receipt', str(args.receipt)]
    iofix_pad.main()
    receipt = json.loads(args.receipt.read_text())
    receipt.update(kind='A: PRE deferred-work behaviour with exact POST ELF/text layout',
                   scope='WB4.1 is the only production behaviour changed from 3700b51d7',
                   limitation='POST grace bookkeeping remains but cannot trigger a pending-FIFO park; no other feature differs',
                   baseline='3700b51d7fb3074f32330dd81f138efbf1ddd980')
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('identity', 'pad'):
        command = commands.add_parser(name)
        command.add_argument('--pre', type=Path, required=True)
        command.add_argument('--post', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
        if name == 'pad':
            command.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    (identity if args.command == 'identity' else pad)(args)
