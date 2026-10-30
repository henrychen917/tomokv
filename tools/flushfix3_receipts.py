#!/usr/bin/env python3
"""Archive completed selected-job evidence, preserving earlier failures."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from flushfix2_verification_receipts import gate, ref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from differ_fanout import fold, load_plan


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    runs, gates, observations, differential = [], {}, {}, []
    for record in sorted((ROOT/'build/flushfix3/verification').glob('*/runs.json')):
        for row in json.loads(record.read_text()):
            label = record.parent.name + '/' + row['phase']
            runs.append(dict(label=label, **row))
            log = (record.parent/(row['phase']+'.log')).resolve()
            folder = Path(re.search(r'artifacts: (.+)', log.read_text())[1])
            completed = [p.parent.name for p in (folder/'jobs').glob('*/done')]
            evidence = gate(log, completed=completed)
            evidence['complete_selection'] = not evidence['omitted_unfinished_jobs']
            assert row['status'] or evidence['complete_selection'], 'successful incomplete selection'
            evidence['explicit_not_run'] = []
            for job in evidence['jobs']:
                output = folder/'jobs'/job['name']/'output.log'
                if not output.exists():
                    continue
                job['output_log'] = ref(output)
                for line in output.read_text().splitlines():
                    if re.search(r'\b(?:NOT RUN|SKIP)\b', line):
                        evidence['explicit_not_run'].append(dict(job=job['name'], line=line))
            gates[label] = evidence
            folder = ROOT/evidence['root']
            if row['phase'].startswith('differ-'):
                plan = load_plan(folder/'differ-plan.json')
                for group in ('split', 'armed'):
                    result = dict(label=label, group=group, seeds=plan['manifest']['seeds'])
                    try:
                        result.update(fold(plan, group, folder), inventory_valid=True)
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        result.update(inventory_valid=False, error=str(error))
                    differential.append(result)
            for job in evidence['jobs']:
                name = job['name']
                if name not in ('flushfix2', 'flushfix2_units', 'flushfix3', 'flushfix3_units'):
                    continue
                for path in sorted((folder/'jobs'/name).rglob('*')):
                    if path.is_file() and (path.suffix == '.json' or path.name in
                            ('ledger', 'done', 'output.log', 'flushfix3-unit.log',
                             'flushfix3-db0-unit.log', 'flushfix2-unit.log', 'flushfix2-db0-unit.log')):
                        observations[str(path.relative_to(ROOT))] = path.read_text()
    result = dict(binary=ref(ROOT/'build/flushfix3/post/tomokv'),
                  gate_source=ref(ROOT/'tests/gate.sh'),
                  runs=runs, gates=gates, differential_inventory=differential)
    out = ROOT/'docs/flushfix3'
    (out/'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    (out/'directed-observations.json.gz').write_bytes(
        gzip.compress(json.dumps(observations, sort_keys=True).encode(), mtime=0))
    print({name: data['verdicts'] for name, data in gates.items()})
    print('Differential inventories:', [(r['label'],r['group'],r['inventory_valid']) for r in differential])


if __name__ == '__main__':
    main()
