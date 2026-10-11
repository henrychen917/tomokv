#!/usr/bin/env python3
"""wave2: every function body of the integrated default build that differs from the 991d48f65
default build (attribute.py output), with the lane it belongs to and why. Offline; reads JSON.
usage: changed_bodies.py <attr.json> <out.tsv>"""
import json
from pathlib import Path
import re
import sys
from collections import Counter

REASONS = [  # (lane set, name pattern, reason) -- first match wins
    ('dbdefault', r'Config::Config\(\)', 'Config default databases 1 -> 16 (two immediate bytes)'),
    ('perfex', r'drain_tasks', 'EX4.13: received tasks constructed in byte storage; no batch zero-fill'),
    ('perfex', r'exec_batch', 'EX4.13: batch execution now inlined into the changed drain'),
    ('perfex', r'ExLoopT<(?:true|false)>::run\(\)', 'EX4.12: CPU clock sampled on the 100 us beat; wall clock read after it'),
    ('perfex', r'keyspace_sample_cycle', 'EX4.2: new noinline owner-beat TTL sampler'),
    ('perfex', r'owner_control_tail', 'EX4.2: owner beat calls the TTL sampler'),
    ('perfex', r'ExLoopT<(?:true|false)>::ExLoopT\(\)', 'EX4.2: sampler cursor initialized in existing padding'),
    ('perfex', r'publish_size|publish_keyspace_sample', 'EX4.2: batch publication keeps counts/field attention, sampling moves to the beat'),
    ('perfex', r'cmd_flush', 'perfex2: snapshot-time cold clear resets the TTL sample (inlined)'),
    ('perfex', r'^main(?:\.cold)?$', 'EX4.2: cursor construction inlined into cold boot code (main)'),
    ('perfio', r'commit_client_transfer', 'IO4.19: epoll DEL of the reserved source interest before closing its dup'),
    ('perfio', r'stream_xreadgroup_execute|infer_entries_read|tombstones_after|reply_group_info|cmd_xinfo',
     'PFDATATY.1: guarded entries-read/lag delivery and XINFO metadata'),
    ('perfio', r'.', 'PFDATATY.1 stream-group translation unit: inlining/code generation of unchanged stream bodies'),
    ('rlresize', r'atomic_prepare_capacity_read_local', 'D1: armed atomic growth reserves its resize retirement record'),
    ('rlresize', r'clear_read_local|FlatStore::clear\(\)', 'D2/D3: FLUSH keeps a prepared snapshot record and bounds the replacement table'),
    ('rlresize', r'prepare_resize_retirement', 'D1: GCC outlines the reservation helper (.isra clone)'),
    ('rlresize', r'maybe_start_shrink|snapshot_control_pass', 'D1 collateral: calls the outlined reservation helper instead of inlining it'),
    ('rlresize', r'.', 'cold collateral of the rlresize units (listed by rlresize: AOF teardown/manifest, '
                       'client migration, MULTI/SORT prep, LB scan, COMDAT helpers)'),
]


def lane_reasons():
    """The lanes' own per-body reasons where they published them (object, demangled name)."""
    import csv
    root = Path(__file__).resolve().parents[3]
    known = {}
    for r in csv.DictReader(open(root / 'docs/perfio/identity/changed-bodies.tsv'), delimiter='\t'):
        known[('perfio', r['object'], r['body'])] = 'perfio: ' + r['reason']
    for r in json.load(open(root / 'docs/perfex/final/changed-body-reasons.json')):
        known[('perfex', r['object'], r['name'])] = 'perfex: ' + r['reason']
    return known


KNOWN = None


def reason(row):
    global KNOWN
    if KNOWN is None:
        KNOWN = lane_reasons()
    lanes = row['lanes_changed']
    if row['cls'] == 'A':
        lane = lanes[0]
        if (lane, row['object'], row['name']) in KNOWN:
            return KNOWN[(lane, row['object'], row['name'])]
    if row['cls'] == 'C':
        return ('no lane changes it; same size and call targets as 991d48f65, register allocation '
                'only (every clean db0 aof.o budget shows it; the linker keeps another object\'s copy)'
                if 'make_room_for' in row['name'] else 'unattributed')
    if row['cls'] == 'D':
        return ('rlresize body with rlresize\'s exact call targets; code generation differs in the '
                'merged src genthread.o unit (D at every scanned budget)')
    if row['cls'] == 'B':
        return ('composite: each of ' + ' + '.join(lanes) + ' changes this body in its own build; '
                'merged translation unit (' + ('unbudgeted src reorder.o' if row['object'] == 'src/core/reorder.o'
                                              else 'shared header edits') + ')')
    for lane, pattern, text in REASONS:
        if lane in lanes and re.search(pattern, row['name']):
            return text
    return 'lane-identical'


def main():
    data = json.load(open(sys.argv[1]))
    rows = [x for r in data for x in r['rows']]
    with open(sys.argv[2], 'w') as out:
        out.write('object\tbody\tclass\tlane\thot\tkind\tpre_bytes\tpost_bytes\t'
                  'equals_lane_build\tcall_targets\treason\n')
        for x in sorted(rows, key=lambda x: (x['cls'], '+'.join(x['lanes_changed']), x['object'], x['name'])):
            targets = ('991d48f65' if x['targets_equal_pre'] else
                       '+'.join(x['targets_equal_lane']) if x['targets_equal_lane'] else 'new')
            out.write('\t'.join(map(str, [x['object'], x['name'], x['cls'], '+'.join(x['lanes_changed']) or '-',
                                          'hot' if x['hot'] else '', x['kind'], x['pre_size'], x['post_size'],
                                          '+'.join(x['merged_equals_lane']) or '-', targets, reason(x)])) + '\n')
    lanes = Counter('+'.join(x['lanes_changed']) or '-' for x in rows)
    print(json.dumps(dict(bodies=sum(r['total'] for r in data), changed=len(rows),
                          classes=dict(Counter(x['cls'] for x in rows)), by_lane=dict(lanes),
                          hot_changed=sum(x['hot'] for x in rows))))


if __name__ == '__main__':
    main()
