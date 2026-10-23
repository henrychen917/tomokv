#!/usr/bin/env python3
"""Attribute every residual linked body to source and its nearest references."""
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import identity

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = identity.ROOT
DOC = ROOT / 'docs/wave5/identity-landing'
rows = json.loads((DOC / 'changed-bodies.json').read_text())
post = identity.inventory(ROOT / 'build/tomokv')
addresses = sorted({b['address'] for r in rows for b in post['groups'].get(r['name'], [])})
lines = subprocess.check_output(['addr2line', '-a', '-f', '-C', '-e', str(ROOT / 'build/tomokv'),
                                 *addresses], text=True).splitlines()
source = {}
for at in range(0, len(lines), 3):
    source[hex(int(lines[at], 16))] = lines[at + 2].replace(str(ROOT) + '/', '')
calls = {}
for name in ('callsites-landing', 'callsites-scatter'):
    for row in json.loads((ROOT / 'docs/wave5' / name / 'summary.json').read_text()):
        calls[row['name']] = row
for row in rows:
    name = row['name']
    row['source'] = sorted({source.get(b['address'], '?') for b in post['groups'].get(name, [])})
    if row['matches']:
        continue
    if re.search(r'execute_timed|exec_batch_exact|SlowlogTiming|slowlog_complete|flush_commits_timed', name):
        reason = 'Integration adds threshold-first completion before Done; this is a separate cold timing specialization.'
    elif re.search(r'function_execute_exec|invoke_fcall', name):
        reason = 'Integration resolves FUNCTION once and admits EXEC version preparation inside its memory scope.'
    elif re.search(r'ExLoopT.*::execute<', name):
        reason = ('Writer/WATCH and tracking behavior compose here. Integration also exposes the existing plain/no-hazard '
                  'early return before the cold deferral call; directed WATCH retry and instruction counts cover it.')
    elif 'exec_batch_timed' in name:
        reason = 'Exact timing/identity ownership moved to a cold helper; average-batch timing still calls the ordinary executor.'
    elif not row['headline_sizes']:
        reason = ('New emitted specialization/closure from ' + ', '.join(row['changed_lanes'])
                  if row['changed_lanes'] else 'New compiler specialization/closure required by the integration timing or FUNCTION callback') + '.'
    elif not row['post_sizes']:
        reason = 'The merged compiler no longer emits this standalone body; callers and surviving specializations remain in the full inventory.'
    elif row['changed_lanes']:
        reason = 'Source/instantiation changes from ' + ', '.join(row['changed_lanes']) + '; the merged body has no exact isolated reference.'
    else:
        reason = 'Compiler propagation in an otherwise unchanged source body: inlining, register allocation, cold splitting, or resolved layout differs.'
    if name in calls:
        comparisons = calls[name]['callsites']
        same = [arm for arm, comparison in comparisons.items() if comparison['same']]
        reason += (' Named call/jump inventories match ' + ', '.join(same) + '.' if same else
                   ' Full call/jump additions and removals against all eight references are retained in the callsite audit.')
    row['reason'] = reason
(DOC / 'changed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
(DOC / 'changed-bodies.md').write_text('\n'.join([
    '# Every changed linked body', '',
    'Strict instruction/encoding normalization is unchanged. Clone multiplicity is retained. '
    'All residuals are listed; identity does not establish throughput merit.', '',
    '| Function | Source | PRE bytes | POST bytes | Attribution |', '|---|---|---:|---:|---|',
    *['| `' + r['name'] + '` | ' + ', '.join('`' + p + '`' for p in r['source']) +
      ' | ' + str(r['headline_sizes']) + ' | ' + str(r['post_sizes']) + ' | ' + r['reason'] + ' |'
      for r in rows]]) + '\n')
print(len(rows), 'changed groups;', sum(not r['matches'] for r in rows), 'residuals attributed')
