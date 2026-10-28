#!/usr/bin/env python3
"""Render the retained attempt history; never turn a failed attempt into a pass."""
import json
import re
from pathlib import Path

DOC = Path(__file__).resolve().parent
notes = {
    'integration-first': 'Pre-budget integration check; final POST rechecked normally and loaded.',
    'lane-rows': 'Four stale wound-hook anchors and three transient RESET boot failures during relinking; all rechecked on frozen POST.',
    'final-once': 'R7 affinity, T12 claim arming, exbatch negative-control diagnostic and obsolete APPLY-window fixture; each repaired and rechecked as a whole job.',
    'repair-rechecks': 'Atomic fixture initially omitted split inbox initialization; complete atomic/owner recheck passes.',
    'atomic-recheck2': 'Complete atomic_units and at412-owner after fixture repair.',
    'execfair-loaded': 'All eight mode/atomic/engine legs; four finite CPU burners share the server allocation.',
    'tcl-first': 'Both modes expose the mandatory XGROUP DESTROY INFO-statistics dependency.',
    'final-tcl': 'XGROUP statistics in both modes, one cross-connection WATCH ordering assertion in 1s; native compat2 legs run, its dependency verdict remains red.',
    'tcl-planted': 'Expected negative control: POST passes 64 GEO assertions; planted arm adds 16 mandatory GEO failures in each mode.',
    'final-selftest': 'Setup rejected a 14-core allocation before any job; minimum is 16 physical CPUs.',
    'final-selftest2': 'Incomplete throwaway source copy lacked tracked measurement fixture documents; copy completed.',
    'final-selftest3': 'Complete one-slot scheduler fixture exceeded 45s beside independent parallel fixtures; deadline and inventory preserved, serial fixture moved first.',
    'final-selftest4': 'Complete ABBA selftest after scheduler fixture sequencing repair; throwaway EXPECT 881/898 only.',
}
coverage = json.loads((DOC / 'coverage.json').read_text())
lines = ['# Wave9 correctness evidence', '',
         'All live runs use the gate’s whole-job interface. The per-invocation map is '
         '[coverage.json](coverage.json); each receipt records argv, environment, source/binary '
         'hashes, every declared leg and its finalizer. Raw logs and verdicts are retained in '
         '[job-evidence](job-evidence), with SHA-256s and per-file manifests indexed by '
         '[job-evidence-index.json](job-evidence-index.json).', '',
         'These are overlapping partial-job campaigns, not a full landing gate. '
         'Do not add their public row totals to infer the 881/898 landing count.', '',
         f"Requested whole-job invocations: **{coverage['summary']}**. "
         f"Added labels with passing frozen-POST evidence: **{coverage['new_rows_passing']}/74**.", '',
         '| Attempt | Exit | Public rows (ok / FAIL) | Disposition |',
         '| --- | ---: | ---: | --- |']
for path in sorted((DOC / 'jobs').glob('*.json')):
    item = json.loads(path.read_text())
    summary = re.search(r'(\d+) ok, (\d+) FAIL', ' '.join(item['summary']))
    counts = ' / '.join(summary.groups()) if summary else 'no rows'
    note = notes.get(path.stem, 'Whole declared job set, frozen POST; inspect the receipt for its modes/engines.')
    lines.append(f'| [{path.stem}](jobs/{path.name}) | {item["exit"]} | {counts} | {note} |')
lines += ['', 'The planted Tcl arm is deliberately broken and is never a passing candidate. '
          'Original failed attempts remain in this table after successful repairs.', '',
          'Standalone controls: `tests/gates_test.py` passes 73/73 after the sequencing repair '
          '([receipt](gates-test-serialized-final.json)); the earlier separate quiet run also passed. '
          'An intermediate launch was interrupted before its socket check because its required '
          '`GATE_TEST_PORT=20098` override was omitted; it is not counted as a completed test. '
          'Lottery’s runner and evidence controls each pass 17/17; both copied witness binaries '
          'built. `make all` succeeded and all 55 recorded `make -q` checks returned zero '
          '([freshness](build-freshness.json)).', '',
          '**NOT RUN:** throughput benchmarks, the 28-cell wave null, fixed-anchor race, '
          'contended-script performance storm and full `tests/gate.sh iteration` remain '
          'maintainer-owned. Lottery has no `gate.sh` job: its copied release/ASAN builds and '
          'serverless controls were exercised; its independent K=20 nightly campaign was not run. '
          'The parked layout-placement and pipelined stream-removal diagnostics were not added '
          'to the gate or represented as passing runs; their lane evidence is linked in '
          '[diagnostics.md](diagnostics.md).', '']
(DOC / 'validation.md').write_text('\n'.join(lines))
