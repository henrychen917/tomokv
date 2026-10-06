#!/usr/bin/env python3
"""Require every focused proof leg; retain failures and count actual TTL checks."""
import json
from pathlib import Path
import re
import sys

out = Path(sys.argv[1])
root = Path(__file__).resolve().parent
suites = (root / 'suites.txt').read_text().splitlines()
seeds = list(map(int, (root / 'seeds.txt').read_text().splitlines()))
counts = {row['seed']: row for row in json.loads((root / 'expected-counts.json').read_text())}
expected_runs = [(condition, lifetime, geometry)
                 for condition, lifetimes in (('contended', range(1, 4)), ('quiet', range(1, 2)))
                 for lifetime in lifetimes for geometry in ('split', 'armed-fused')]
expected_names = [f'{c}-{n}-{g}' for c, n, g in expected_runs]
rows = [line.split('\t') for line in (out / 'runs.tsv').read_text().splitlines()]
assert [row[0] for row in rows] == expected_names, 'missing, duplicate, or reordered lifetime'
results = []
for (condition, lifetime, geometry), (name, rc) in zip(expected_runs, rows):
    folder = out / name
    record = dict(condition=condition, lifetime=lifetime, geometry=geometry,
                  rc=int(rc), legs=0, failed_legs=0, ttl_checks={suite: 0 for suite in suites},
                  errors=[])
    for atomic in (0, 1):
        for seed in seeds:
            for suite in suites:
                path = folder / f'{suite}-a{atomic}-s{seed}.txt'
                if not path.exists():
                    record['errors'].append(f'missing {path.name}')
                    continue
                log = path.read_text()
                summaries = re.findall(r'^DIFFER (\w+): (\d+) ops, (\d+) diffs, '
                                       r'(\d+) deadline-bounded TTL checks -> (PASS|FAIL)$',
                                       log, re.M)
                if len(summaries) != 1 or summaries[0][0] != suite:
                    record['errors'].append(f'missing/invalid summary {path.name}')
                    continue
                _, _, diffs, checks, verdict = summaries[0]
                record['legs'] += 1
                record['ttl_checks'][suite] += int(checks)
                record['failed_legs'] += int(verdict != 'PASS' or int(diffs) != 0)
                if int(checks) != counts[seed][suite]['expected_integer_checks']:
                    record['errors'].append(f'missing or extra TTL checks {path.name}: {checks}')
                try:
                    coverage = json.loads(path.with_suffix('.txt.coverage.json').read_text())
                    witnessed = sum(coverage['commands'].get(cmd, 0)
                                    for cmd in ('PTTL', 'TTL', 'HPTTL', 'HTTL'))
                    required = counts[seed][suite].get('generated_queries', int(checks))
                    if coverage.get('schema') != 1 or witnessed != required:
                        record['errors'].append(f'incorrect TTL coverage {path.name}: {witnessed}')
                except (OSError, ValueError, KeyError):
                    record['errors'].append(f'missing/invalid comparison coverage {path.name}')
    record['passed'] = (record['rc'] == 0 and record['failed_legs'] == 0 and
                        not record['errors'] and record['legs'] == 2 * len(seeds) * len(suites))
    results.append(record)
report = dict(passed=all(row['passed'] for row in results), results=results,
              legs=sum(row['legs'] for row in results),
              failed_legs=sum(row['failed_legs'] for row in results),
              ttl_checks={suite: sum(row['ttl_checks'][suite] for row in results) for suite in suites})
(out / 'proof-results.json').write_text(json.dumps(report, indent=2) + '\n')
print('| Condition | Lifetime | Geometry | Legs | Failed legs | TTL checks | Result |')
print('| --- | ---: | --- | ---: | ---: | ---: | --- |')
for row in results:
    print('| %s | %d | %s | %d | %d | %d | %s |' %
          (row['condition'], row['lifetime'], row['geometry'], row['legs'], row['failed_legs'],
           sum(row['ttl_checks'].values()), 'PASS' if row['passed'] else 'FAIL'))
print(json.dumps(report['ttl_checks'], sort_keys=True))
sys.exit(0 if report['passed'] else 1)
