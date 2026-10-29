#!/usr/bin/env python3
"""Bounded correctness/oracle sweep; no rate or timing verdict."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--cases', default='semantics,swapdb,debug-reload,debug-loadaof,live-cut,live-script,live-watch,live-bgsave,live-flip,bgsave-straddle,aof-restart')
    p.add_argument('--databases', default='16,1')
    p.add_argument('--port', type=int, default=20190)
    p.add_argument('--cores', default='0-7')
    p.add_argument('--load-cores', default='8-15')
    a = p.parse_args()
    base = ROOT / 'build/flushfix2/siblings' / a.label
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in a.cases.split(','):
        for databases in map(int, a.databases.split(',')):
            output = base / f'{case}-{databases}'
            cmd = ['taskset', '-c', a.load_cores, 'python3', 'tests/flushfix2_siblings.py',
                   '--case', case, '--databases', str(databases), '--binary', str(a.binary.resolve()),
                   '--oracle', '/home/user/Projects/redis/src/redis-server',
                   '--cores', a.cores, '--port', str(a.port), '--seconds', '4',
                   '--output', str(output)]
            if case == 'live-flip':
                cmd += ['--modes', '2s']
            with (base / f'{case}-{databases}.log').open('w') as log:
                result = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            row = dict(case=case, databases=databases, command=cmd, status=result.returncode)
            rows.append(row)
            (base / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(case, databases, result.returncode, flush=True)


if __name__ == '__main__':
    main()
