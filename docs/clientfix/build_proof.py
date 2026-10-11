#!/usr/bin/env python3
"""Build exactly the gate's production targets and record every freshness check."""
import gzip
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/clientfix'
BUILD = ROOT / 'build/clientfix'
gate = (ROOT / 'tests/gate.sh').read_text()
job = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
targets = ['build/' + name for name in re.search(r'for target in (.*?); do', job)[1].split()]
assert len(targets) == 28, targets
receipt = dict(affinity='112-127', targets=targets, runs=[])


def run(name, argv):
    command = ['taskset', '-c', '112-127', *argv]
    log = BUILD / (name + '.log')
    with log.open('w') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    with gzip.open(OUT / (name + '.log.gz'), 'wb') as output:
        output.write(log.read_bytes())
    receipt['runs'].append(dict(name=name, command=command, exit_code=result.returncode,
                                log='docs/clientfix/' + name + '.log.gz'))
    (OUT / 'production-units.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(name, result.returncode, flush=True)
    return result.returncode


assert run('post-build-final', ['make', '-j16', 'all']) == 0
run('production-units-build', ['make', '-k', '-j16', *targets, 'build/climon-mask-unit'])
for target in targets + ['build/climon-mask-unit']:
    run('fresh-' + target.removeprefix('build/'), ['make', '-q', target])
run('mdbqsbr-live-arms-build', ['make', '-j16', 'mdbqsbr-live-arms'])
run('climon-mask-unit', ['build/climon-mask-unit'])
raise SystemExit(any(row['exit_code'] for row in receipt['runs']))
