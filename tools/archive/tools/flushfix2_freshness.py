#!/usr/bin/env python3
"""Check every literal production-unit target with its actual makefile set."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    gate = (ROOT/'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    first = body.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r'build/[A-Za-z0-9_-]+', first)
    assert len(targets) == len(set(targets)) and len(targets) > 40
    checks = [([], t) for t in ['all', *targets, 'mdbqsbr-live-arms']]
    checks += [(['-f', 'Makefile', '-f', 'tools/blockfix_cost.mk'], t)
               for t in ['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']]
    checks += [(['-f', 'Makefile', '-f', 'tools/blockfix2.mk'], t)
               for t in ['build/blockfix2-unit', 'build/blockfix2-db0-unit']]
    checks += [(['-f', 'Makefile', '-f', 'tools/flushfix2.mk'], t)
               for t in ['build/flushfix2-unit', 'build/flushfix2-db0-unit']]
    rows = []
    for flags, target in checks:
        cmd = ['make', *flags, '-q', target]
        status = subprocess.run(cmd, cwd=ROOT).returncode
        path = ROOT/target
        rows.append(dict(target=target, command=cmd, status=status,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
    out = ROOT/'docs/flushfix2/production-freshness.json'
    out.write_text(json.dumps(rows, indent=2)+'\n')
    print('fresh', sum(r['status'] == 0 for r in rows), '/', len(rows))
    assert all(r['status'] == 0 for r in rows), [r for r in rows if r['status']]


if __name__ == '__main__':
    main()
