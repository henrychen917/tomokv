#!/usr/bin/env python3
"""Record make -q for every literal production-unit target and both FLUSH suites."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    gate = (ROOT/'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    first = body.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r'build/[A-Za-z0-9_-]+', first)
    assert len(targets) == len(set(targets)) and len(targets) > 40
    checks = [([], t) for t in ['all', *targets, 'mdbqsbr-live-arms']]
    for makefile, extra in (
        ('blockfix_cost', ['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
        ('blockfix2', ['build/blockfix2-unit', 'build/blockfix2-db0-unit']),
        ('flushfix2', ['build/flushfix2-unit', 'build/flushfix2-db0-unit']),
        ('flushfix3', ['build/flushfix3-unit', 'build/flushfix3-db0-unit']),
    ):
        checks += [(['-f', 'Makefile', '-f', f'tools/{makefile}.mk'], t) for t in extra]
    rows = []
    for flags, target in checks:
        cmd = ['make', *flags, '-q', target]
        status = subprocess.run(cmd, cwd=ROOT).returncode
        path = ROOT/target
        rows.append(dict(target=target, command=cmd, status=status,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    out = ROOT/'docs/flushfix3/production-freshness.json'
    out.write_text(json.dumps(rows, indent=2)+'\n')
    print('fresh', sum(r['status'] == 0 for r in rows), '/', len(rows))
    assert all(r['status'] == 0 for r in rows), [r for r in rows if r['status']]


if __name__ == '__main__':
    main()
