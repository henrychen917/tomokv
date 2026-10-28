#!/usr/bin/env python3
"""Serverless instruction, selected-definition, layout, and binary receipts."""
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from infofields_artifacts import layouts
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/scriptfix2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    pre = ROOT / 'build/scriptfix2/pre/tomokv'
    post = ROOT / 'build/scriptfix2/tomokv-post-verified'
    pad = ROOT / 'build/scriptfix2/tomokv-pad-a'
    before = [json.loads(line) for line in (DOC / 'pre-counts.jsonl').read_text().splitlines()]
    after = [json.loads(line) for line in (DOC / 'post-counts.jsonl').read_text().splitlines()]
    assert len(before) == len(after) == 40
    counts = []
    for a, b in zip(before, after):
        key = {k: a[k] for k in ('mode', 'command', 'batch', 'slowlog_us')}
        assert all(b[k] == v for k, v in key.items())
        key.update(pre=min(a['counts']), post=min(b['counts']))
        key['delta'] = key['post'] - key['pre']
        assert key['delta'] == 0, key
        counts.append(key)
    old_layout, new_layout = layouts(pre), layouts(post)
    assert old_layout == new_layout
    # The broad inventory includes every emitted weak COMDAT copy, even copies
    # discarded by the production link. Resolve the three changed weak copies
    # against the actual, unchanged production object order before judging them.
    summary = json.loads((DOC / 'object-audit/summary.json').read_text())
    with gzip.open(DOC / 'object-audit/bodies.json.gz', 'rt') as stream:
        bodies = json.load(stream)
    changed = [r for r in bodies if not r['equal']]
    assert all(r['object'].endswith(('/cmd/functions.o', '/cmd/scripting.o')) for r in changed)
    recipes = subprocess.check_output(['make', '-Bn', 'all'], cwd=ROOT, text=True)
    links = [shlex.split(line) for line in recipes.splitlines() if line.startswith('g++ ')
             and ' -c ' not in line and ' -o build/tomokv ' in line]
    link, = links
    object_order = [arg.removeprefix('build/') for arg in link if arg.endswith('.o')]
    discarded = []
    for item in summary['other_hot']:
        candidates = [row for row in bodies if row['symbol'] == item['symbol'] and
                      row['object'] in object_order]
        selected = min(candidates, key=lambda row: object_order.index(row['object']))
        assert selected['equal'] and selected['object'] != item['object'], (item, selected)
        for candidate in candidates:
            for base in (ROOT / 'build/scriptfix2/pre', ROOT / 'build'):
                symbol = Elf(base / candidate['object']).functions()[item['symbol']]
                assert symbol['info'] >> 4 == 2, 'expected only weak definitions'
        # The linked image must carry the selected copy's size in both arms.
        assert Elf(pre).functions()[item['symbol']]['size'] == selected['pre_size']
        assert Elf(post).functions()[item['symbol']]['size'] == selected['post_size']
        discarded.append(dict(symbol=item['symbol'], discarded=item['object'],
                              selected=selected['object'], selected_bytes_equal=True))
    report = dict(
        base_commit='a214652ec262aa9a5eeaeadf129c0ef76ba6c99c',
        binaries={str(path.relative_to(ROOT)): sha(path) for path in (pre, post, pad)},
        oracle_sha256=sha(Path('/home/user/Projects/redis74/src/redis-server')),
        counts=counts,
        count_scope='Production executor command entry plus callees, no sockets or workers. '
                    'Minimum of nine user-space retired-instruction readings. '
                    'MGET/MSET use eight repetitions of one local key; parsing/routing/setup '
                    'are outside the counter. Counters are not throughput evidence.',
        counter_binaries={arm: sha(ROOT / f'build/scriptfix2/{arm}-counts')
                          for arm in ('pre', 'post')},
        layouts_equal=True, layouts=new_layout,
        object_inventory=dict(total=summary['total'], equal=summary['equal'],
                              hot_emitted=summary['hot'], hot_emitted_equal=summary['hot_equal'],
                              changed_selected_hot=0, discarded_weak_copies=discarded,
                              limitation='The generic ccfix audit rejects these discarded copies '
                                         'before this link-order resolution; its raw failure is retained.'))
    (DOC / 'artifacts.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('counts', 'layouts')}, indent=2))


if __name__ == '__main__':
    main()
