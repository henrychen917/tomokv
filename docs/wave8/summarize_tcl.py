#!/usr/bin/env python3
"""Preserve compact exact-name evidence from gate-owned Tcl invocations."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
current = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())
before = json.loads(subprocess.check_output(
    ['git', 'show', 'cx-harness5:tests/redis_tcl_passing.json'], cwd=ROOT, text=True))
removed = {(file, name) for file, row in before['files'].items()
           for name in row['skip_tests'] if name not in current['files'][file]['skip_tests']}
added = {(file, name) for file, row in current['files'].items()
         for name in row['skip_tests'] if name not in before['files'][file]['skip_tests']}
promotions = {(r['file'], r['name']) for r in current['wave8_promotions']}
assert removed == promotions and len(removed) == 19 and not added
out = dict(removed_names=sorted(removed), added_names=sorted(added),
           named_known_failures=sum(len(r['skip_tests']) for r in current['files'].values()), runs={})
for run in sys.argv[1:] or ['tcl-final']:
    receipt = json.loads((ROOT / 'docs/wave8/jobs' / (run + '.json')).read_text())
    rows = []
    for mode in ('2s', '1s'):
        path = Path(receipt['artifacts']) / 'jobs/redis_tcl' / ('redis-tcl-' + mode) / 'summary.json'
        summary = json.loads(path.read_text())
        files = summary['rows']
        promoted = []
        for file, name in sorted(promotions):
            row, = [r for r in files if r['file'] == file]
            events = [e for e in row['events'] if e['test'] == name + ' in tests/' + file + '.tcl'
                      and e['status'] in ('ok', 'err')]
            expected = 2 if file == 'unit/scripting' else 1
            assert len(events) == expected and all(e['status'] == 'ok' for e in events), (run, mode, name, events)
            promoted.append(dict(file=file, name=name, passing_occurrences=len(events)))
        failures = [dict(file=r['file'], test=e['test'], data=e['data']) for r in files
                    for e in r['events'] if e['status'] == 'err' and e['test']]
        rows.append(dict(mode=mode, files=len(files), passed=sum(r['passed'] for r in files),
                         named_failures=failures, file_errors={r['file']:r['error'] for r in files if r['error']},
                         promoted=promoted, source_summary=str(path)))
    out['runs'][run] = dict(exit=receipt['exit'], binary_sha256=receipt['binary_sha256'], modes=rows)
(ROOT / 'docs/wave8/tcl-validation.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({run: [(r['mode'], r['passed'], len(r['named_failures'])) for r in data['modes']]
                  for run, data in out['runs'].items()}))
