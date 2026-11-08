#!/usr/bin/env python3
"""Build/check the exact production_units inventory plus Makefile token controls."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/readability-a2/builds'
OUT.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check-only', action='store_true')
args = parser.parse_args()
body = (ROOT / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}\n', 1)[0]
first = body.split('>"$TMPDIR/build.log"', 1)[0]
targets = list(dict.fromkeys(re.findall(r'\bbuild/[A-Za-z0-9_-]+', first)))
assert len(targets) == 61, targets
groups = [dict(name='primary', flags=[], targets=['all', *targets]),
          dict(name='mdbqsbr', flags=[], targets=['mdbqsbr-live-arms']),
          dict(name='blockfix-cost', flags=['-f', 'Makefile', '-f', 'tools/blockfix_cost.mk'],
               targets=['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
          dict(name='blockfix2', flags=['-f', 'Makefile', '-f', 'tools/blockfix2.mk'],
               targets=['build/blockfix2-unit', 'build/blockfix2-db0-unit']),
          dict(name='token-controls', flags=[], targets=['build/climon-mask-unit',
               'build/climon-mask-old-unit', 'build/l4prebuild-unit'])]
env = dict(os.environ, LC_ALL='C', TOMO_INFO_GIT_SHA1='5c363128', TOMO_INFO_GIT_DIRTY='0')
results = []
for group in groups:
    command = ['taskset', '-c', '48-63', 'make', '-k', '-j16', *group['flags'], *group['targets']]
    status = None
    if not args.check_only:
        with (OUT / (group['name'] + '.log')).open('w') as log:
            status = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    row = dict(**group, command=command, exit=status, freshness=[])
    checks = [(target, []) for target in group['targets']]
    if group['name'] == 'mdbqsbr':
        common = '-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_MDBQSBR_LIVE_PARK'
        checks = [('all', ['BUILD_ROOT=build/mdbqsbr2-park', 'CXXFLAGS=' + common]),
                  ('all', ['BUILD_ROOT=build/mdbqsbr2-no-wake', 'CXXFLAGS=' + common + ' -DTOMO_MDBQSBR_NO_WAKE'])]
    for target, variables in checks:
        check = subprocess.run(['taskset', '-c', '48-63', 'make', *group['flags'], *variables, '-q', target],
                               cwd=ROOT, env=env, text=True, capture_output=True)
        row['freshness'].append(dict(target=target, variables=variables, exit=check.returncode, stderr=check.stderr))
    results.append(row)
    (ROOT / 'build/readability-a2/builds.json').write_text(json.dumps(results, indent=2) + '\n')
    print(group['name'], 'build', status, 'fresh', sum(x['exit'] == 0 for x in row['freshness']),
          '/', len(row['freshness']), flush=True)
raise SystemExit(any(r['exit'] or any(c['exit'] for c in r['freshness']) for r in results))
