#!/usr/bin/env python3
"""Build every production_units target and record make -q without hand-copying its list."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cmdfix2'


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    p = argparse.ArgumentParser(); p.add_argument('--check-only', action='store_true'); a = p.parse_args()
    source = (ROOT/'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    first_make = source.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r'build/[a-zA-Z0-9_-]+', first_make)
    assert len(targets) == len(set(targets)) and len(targets) >= 50
    rows = []
    env = dict(os.environ, LC_ALL='C', CXX='g++ -gz=zlib', CC='cc -gz=zlib')

    def run(label, command):
        with (OUT/(label+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        rows.append(dict(label=label, command=command, exit_code=result.returncode))
        print(label, result.returncode, flush=True)
        return result.returncode

    commands = [
        ('production', ['make', '-k', '-j12', 'all', *targets]),
        ('live-arms', ['make', '-j12', 'mdbqsbr-live-arms']),
        ('blockfix-cost', ['make', '-j12', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk',
                          'build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
        ('blockfix2', ['make', '-j12', '-f', 'Makefile', '-f', 'tools/blockfix2.mk',
                      'build/blockfix2-unit', 'build/blockfix2-db0-unit']),
    ]
    if not a.check_only:
        for label, command in commands: run('final-build-'+label, command)
    for label, command in commands:
        if label == 'live-arms':
            # This recipe-bearing phony target is always stale by definition.
            # Check the two real all targets that its recipe builds instead.
            for variant in ('park', 'no-wake'):
                run('fresh-live-'+variant, ['make', '-q', 'BUILD_ROOT=build/mdbqsbr2-'+variant, 'all'])
        else:
            run('fresh-'+label, ['make', '-q', *[v for v in command[1:] if v not in ('-k', '-j12')]])
    binary = ROOT/'build/tomokv'
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest == hashlib.sha256((OUT/'POST').read_bytes()).hexdigest(), 'production binary changed'
    result = dict(targets=targets, production_sha256=digest, checks=rows,
                  loaded_section_only_debug_compression='docs/cmdfix2/unit-debug-compression.json')
    (ROOT/'docs/cmdfix2/freshness.json').write_text(json.dumps(result, indent=2)+'\n')
    raise SystemExit(int(any(r['exit_code'] for r in rows)))
