#!/usr/bin/env python3
"""Audit every production_units target after its gate job finishes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    assert (run / 'jobs/production_units/done').exists(), 'production_units still running'
    gate = (ROOT / 'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    main_make = body.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r'build/[a-zA-Z0-9_-]+', main_make)
    assert len(targets) == len(set(targets))
    rows = []

    def check(name, command, marker=None, expected=0):
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        ready = (run / 'unit-ready' / marker).exists() if marker else None
        row = dict(name=name, command=command, exit=result.returncode,
                   expected=expected, output=result.stdout, marker=marker, ready=ready)
        row['pass'] = result.returncode == expected and ready is not False
        rows.append(row)
        print(name, result.returncode, 'PASS' if row['pass'] else 'FAIL', flush=True)

    check('make all', ['make', '-j32', 'all'])
    check('make -q all', ['make', '-q', 'all'])
    for target in targets:
        check(target, ['make', '-q', target], target.removeprefix('build/'))
    # Recursive $(MAKE) propagates -q to both arm builds. Also query each
    # actual arm dependency graph independently below.
    check('mdbqsbr-live-arms wrapper', ['make', '-q', 'mdbqsbr-live-arms'],
          'mdbqsbr-live-arms')
    for arm in ('park', 'no-wake'):
        check('mdbqsbr2-' + arm, ['make', '-q', 'BUILD_ROOT=build/mdbqsbr2-' + arm, 'all'])
    check('blockfix-cost', ['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk',
                           '-q', 'build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256'],
          'blockfix-cost')
    check('blockfix-cost binding', ['sha256sum', '-c', 'build/tomokv.blockfix-cost.sha256'])
    for target in ('blockfix2-unit', 'blockfix2-db0-unit'):
        check(target, ['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk', '-q', 'build/' + target],
              target)
    result = dict(run=str(run), binary_sha256=hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest(),
                  targets=len(targets) + 4, rows=rows, passed=all(r['pass'] for r in rows))
    (ROOT / 'docs/wave11/production-units.json').write_text(json.dumps(result, indent=2) + '\n')
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
