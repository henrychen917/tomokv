#!/usr/bin/env python3
"""Build exactly the production_units target inventory and check freshness."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/readability-a1b/builds'
OUT.mkdir(parents=True, exist_ok=True)
body = (ROOT / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}\n', 1)[0]
first = body.split('>"$TMPDIR/build.log"', 1)[0]
targets = list(dict.fromkeys(re.findall(r'\bbuild/[A-Za-z0-9_-]+', first)))
assert len(targets) == 61, targets
groups = [dict(name='primary', flags=[], targets=['all', *targets]),
          dict(name='mdbqsbr', flags=[], targets=['mdbqsbr-live-arms']),
          dict(name='blockfix-cost', flags=['-f', 'Makefile', '-f', 'tools/blockfix_cost.mk'],
               targets=['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
          dict(name='blockfix2', flags=['-f', 'Makefile', '-f', 'tools/blockfix2.mk'],
               targets=['build/blockfix2-unit', 'build/blockfix2-db0-unit'])]
env = dict(os.environ, LC_ALL='C', TOMO_INFO_GIT_SHA1='5c363128', TOMO_INFO_GIT_DIRTY='0')
results = []
for group in groups:
    command = ['taskset', '-c', '80-95', 'make', '-k', '-j16', *group['flags'], *group['targets']]
    with (OUT / (group['name'] + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    row = dict(**group, command=command, exit=result.returncode, freshness=[])
    for target in group['targets']:
        check = subprocess.run(['taskset', '-c', '80-95', 'make', *group['flags'], '-q', target],
                               cwd=ROOT, env=env, text=True, capture_output=True)
        row['freshness'].append(dict(target=target, exit=check.returncode, stderr=check.stderr))
    results.append(row)
    (ROOT / 'docs/readability-a1b/evidence/builds.json').write_text(json.dumps(results, indent=2) + '\n')
    print(group['name'], 'build', row['exit'], 'fresh', sum(x['exit'] == 0 for x in row['freshness']),
          '/', len(row['freshness']), flush=True)
raise SystemExit(any(r['exit'] or any(c['exit'] for c in r['freshness']) for r in results))
