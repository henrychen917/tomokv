#!/usr/bin/env python3
"""Summarize the unchanged ccfix auditor, retaining every failed identity record."""
import collections
import gzip
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf, HOT
from overlapaxe_artifacts import reason

AUDIT = ROOT / 'build/overlapaxe2/body-audit'
DOCS = ROOT / 'docs/overlapaxe2'
with gzip.open(AUDIT / 'bodies.json.gz', 'rt') as stream:
    rows = json.load(stream)
with gzip.open(ROOT / 'docs/overlapaxe/bodies.json.gz', 'rt') as stream:
    old_rows = json.load(stream)
old_index = {(r['object'], r['symbol']): r for r in old_rows}


def hot(row):
    return bool(HOT.search(row['name']) or re.search(r'ExLoopT<.*>::run\(', row['name']))


summary = json.loads((AUDIT / 'summary.json').read_text())
summary = {k: v for k, v in summary.items() if not isinstance(v, list)}
summary.update(
    base='165d268bed1bae72947263fa951985d8a83eb0c8',
    post_source='56618ef9b220d048f639ed4ec18d3a4d144e4ef6',
    audit_command='taskset -c 112-127 python3 tools/ccfix_audit.py build/overlapaxe2/BASE build build/overlapaxe2/body-audit',
    audit_returncode=1,
    interpretation='Hot-body identity FAIL, as in the original report. The audit retains opcodes, member offsets, and callee identities; no normalization was relaxed. The owner judged the earlier 18-cell nulls; this merge proof makes no new performance claim.')
changed = []
for row in rows:
    if row['equal']:
        continue
    record = dict(row, reason=reason(row))
    if 'normalize_multi_blocking_pop' in row['name']:
        record['reason'] = ('No source change to xshard.cc against merged upstream. The retained '
            'ACL/blocking-key normalization is recompiled with the reduced overlap/header '
            'instantiation graph; compiler body/inlining and relocation differences are '
            'recorded, not asserted performance-neutral.')
        if '[clone .cold]' in row['name']:
            record['reason'] = ('No source change to xshard.cc. Compiler stack-frame changes '
                'in normalize_multi_blocking_pop also change this 45-byte cleanup body: '
                'LEA stack slot 0x50 -> 0x40 and saved-canary slot 0x148 -> 0x138. '
                'Equal size is not byte identity.')
    if 'command_client_migration_extract' in row['name']:
        record['reason'] = ('Client migration extraction source is unchanged against merged upstream. '
            'Removing overlap CONFIG/INFO code in the same translation unit perturbs compiler '
            'code generation; this body grows by 16 bytes and is not byte-identical.')
    changed.append(record)
summary['changed_by_object'] = dict(sorted(collections.Counter(r['object'] for r in changed).items()))
summary['changed_by_reason'] = dict(collections.Counter(r['reason'] for r in changed))
summary['new_changed_vs_original_report'] = [
    r for r in changed if old_index.get((r['object'], r['symbol']), {}).get('equal', True)]
summary['now_equal_vs_original_report'] = [
    r for r in rows if r['equal'] and (r['object'], r['symbol']) in old_index
    and not old_index[(r['object'], r['symbol'])]['equal']]
fields = ('equal', 'raw_equal', 'pre_size', 'post_size')
summary['hot_inventory_signature_differences_vs_original_report'] = [
    dict(object=r['object'], name=r['name'],
         before={f: old_index.get((r['object'], r['symbol']), {}).get(f) for f in fields},
         after={f: r[f] for f in fields})
    for r in rows if hot(r) and any(
        r[f] != old_index.get((r['object'], r['symbol']), {}).get(f) for f in fields)]
for kind, predicate in (
        ('fused_objects', lambda r: r['object'].endswith('/core/genthread.o')),
        ('fused_hot', lambda r: r['object'].endswith('/core/genthread.o') and hot(r))):
    subset = [r for r in rows if predicate(r)]
    summary[kind] = dict(total=len(subset), equal=sum(r['equal'] for r in subset),
                         changed=sum(not r['equal'] for r in subset))
commands = [r for r in rows if re.search(r'::cmd_(?:get|set|mget|mset)(?:<|\()', r['name'])]
assert len(commands) == 10 and all(r['equal'] and r['raw_equal'] for r in commands)
summary['get_set_bodies'] = dict(total=len(commands), equal=len(commands), raw_equal=len(commands))
summary['changed_handlers'] = [r for r in changed if re.search(r'::cmd_\w+(?:<|\()', r['name'])]
summary['prefetch'] = []
for arm, binary in [('BASE', ROOT / 'build/overlapaxe2/BASE/tomokv'), ('POST', ROOT / 'build/tomokv')]:
    symbols = [s for s in Elf(binary).functions().values()
               if 'prefetch_overlap_batch' in s['name'] or 'prefetch_owner_batch' in s['name']]
    fused = [s for s in symbols if 'ExLoopTILb1EE' in s['name']]
    assert len(fused) == 2
    assert arm != 'POST' or len(symbols) == 2, 'split prefetch body survived'
    for symbol in fused:
        disassembly = subprocess.check_output(
            ['objdump', '-dw', '--disassemble=' + symbol['name'], str(binary)], text=True)
        count = len(re.findall(r'\bprefetcht0\b', disassembly))
        assert count == 2
        summary['prefetch'].append(dict(arm=arm, symbol=symbol['name'],
                                         bytes=symbol['size'], prefetcht0=count))
for filename, contents in (
        ('changed-bodies.json.gz', changed),
        ('changed-fused-bodies.json.gz', [r for r in changed if r['object'].endswith('/core/genthread.o')])):
    with gzip.GzipFile(filename=str(DOCS / filename), mode='wb', mtime=0) as stream:
        stream.write(json.dumps(contents, indent=2).encode() + b'\n')
(DOCS / 'bodies.json.gz').write_bytes((AUDIT / 'bodies.json.gz').read_bytes())
(DOCS / 'body-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, (dict, list))}, indent=2))
print('Fused objects:', summary['fused_objects'])
print('Fused hot:', summary['fused_hot'])
print('Hot inventory signature differences:', len(summary['hot_inventory_signature_differences_vs_original_report']))
