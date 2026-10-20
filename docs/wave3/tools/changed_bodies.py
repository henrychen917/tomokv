#!/usr/bin/env python3
"""wave3: every function body of the integrated default build that differs from the f821104a9 default
build (attribute.py output), with the change-set it belongs to and why. Offline; reads JSON.
usage: changed_bodies.py <attr.json> <composite.json> <out.tsv>"""
import json
import re
import sys
from collections import Counter

REASONS = [  # (lane, name pattern, reason) -- first match wins for class A
    ('respresume', r'parse_and_dispatch', 'NT4.2: pending-bit test on the cursor word (Client+0x4c) and the frontier '
                                          'argument (Client+0x60) in the dispatcher window; resumable parser calls'),
    ('respresume', r'resp_(?:parse|resume|suspend)|RespFrontier', 'NT4.2/NT4.3: resumable parser bodies (no stack canary)'),
    ('respresume', r'resume_multibulk|mark_closing|mark_dead|cmd_quit', 'NT4.2: frontier release on close/teardown paths'),
    ('respresume', r'.', 'respresume code generation: the same body as respresume\'s own build (its unit grew '
                         'with unchanged budgets)'),
    ('rlfix', r'prepare_local_read', 'RL4.3: validated read-local GET miss served locally (exact keyspace accounting)'),
    ('rlfix', r'ReadLocalDemotionPlan|demotion', 'RL4.4: one-key DEL/UNLINK refines the staged ROB generation'),
    ('rlfix', r'.', 'rlfix code generation: the same body as rlfix\'s own build'),
    ('mkfix', r'IoLoop::init.*lambda', 'mkfix2 A: IO retirement callback consumes the published MSET reply'),
    ('mkfix', r'ScatterArenaPool', 'mkfix2 B: common 16 KiB arenas retained at peak demand (free link in the arena)'),
    ('mkfix', r'xshard_|assemble_final|scatter', 'mkfix2 A/B: completed atomic MSET reply at Done / arena retention'),
    ('mkfix', r'.', 'mkfix2 A/B code generation: the same body as mkfix2 AB\'s own build'),
    ('aoforder', r'Aof|aof_|resolve_groups|manifest|record_', 'F3: AOF staging windows emitted in mutation ticket order'),
    ('aoforder', r'.', 'aoforder code generation in the AOF units: the same body as aoforder\'s own build'),
    ('hexpread', r'hexpread|hash_read|parked|atomic_read_owns_value', 'HX-1: hash reads of a parked version filter '
                                                                      'expired fields without reaping'),
    ('hexpread', r'objectpread|cmd_object', 'HX-2: OBJECT IDLETIME/FREQ resolve at the read cut before key expiry'),
    ('hexpread', r'.', 'hexpread hash/server_tail code generation (54 outside-scope bodies, accepted on merit): '
                       'the same body as hexpread\'s own build'),
]


def reason(row, composite):
    lanes = row['lanes_changed']
    if row['cls'] == 'A':
        for lane, pattern, text in REASONS:
            if lane == lanes[0] and re.search(pattern, row['name']):
                return text
    if row['cls'] == 'B':
        c = composite.get((row['object'], row['name']))
        extra = f"; decomposition: {c['level']}" if c else ''
        if set(row['merged_equals_lane']) >= set(l for l in lanes if l != 'wave2') and 'wave2' not in lanes:
            return 'every changing lane builds this exact body (identical code generation)' + extra
        if row['merged_equals_lane']:
            return ('equals ' + '+'.join(row['merged_equals_lane']) + "'s own body; the other lane's change in "
                    'this body is code generation only') + extra
        return 'composite: each of ' + ' + '.join(lanes) + ' changes this body in its own build' + extra
    if row['cls'] == 'D':
        if 'record_post_image_impl' in row['name']:
            return ('aoforder body; at every scanned db0 aof.o budget the merged unit calls Slice::key_eq out of line '
                    'where aoforder\'s build inlines it (memcmp); cold AOF post-image path')
        if 'atomic_prepare_capacity_read_local' in row['name']:
            return ('wave2 (rlresize) body; same size and call targets as f821104a9, two field preparations emitted in '
                    'the other order at every clean src genthread.o budget; cold armed-growth path')
        return 'single change-set body that differs from its own build'
    return 'unattributed'


def main():
    data = json.load(open(sys.argv[1]))
    composite = {(c['object'], c['name']): c for c in json.load(open(sys.argv[2]))}
    rows = [x for r in data for x in r['rows']]
    with open(sys.argv[3], 'w') as out:
        out.write('object\tbody\tclass\tchange_sets\thot\tkind\tpre_bytes\tpost_bytes\t'
                  'equals_lane_build\tcall_targets\treason\n')
        for x in sorted(rows, key=lambda x: (x['cls'], '+'.join(x['lanes_changed']), x['object'], x['name'])):
            targets = ('f821104a9' if x['targets_equal_pre'] else
                       '+'.join(x['targets_equal_lane']) if x['targets_equal_lane'] else 'new')
            out.write('\t'.join(map(str, [x['object'], x['name'], x['cls'], '+'.join(x['lanes_changed']) or '-',
                                          'hot' if x['hot'] else '', x['kind'], x['pre_size'], x['post_size'],
                                          '+'.join(x['merged_equals_lane']) or '-', targets,
                                          reason(x, composite)])) + '\n')
    by = Counter('+'.join(x['lanes_changed']) or '-' for x in rows)
    hot = Counter((x['cls'], '+'.join(x['lanes_changed'])) for x in rows if x['hot'])
    print(json.dumps(dict(bodies=sum(r['total'] for r in data), changed=len(rows),
                          classes=dict(Counter(x['cls'] for x in rows)), by_change_set=dict(by),
                          hot_changed=sum(x['hot'] for x in rows),
                          hot_by=[f'{c} {l}: {n}' for (c, l), n in sorted(hot.items())]), indent=1))


if __name__ == '__main__':
    main()
