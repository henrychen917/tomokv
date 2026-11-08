#!/usr/bin/env python3
"""Run the unmodified at412 diagnostics in the snapfix allocation (no rates)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', default='build/snapfix/pre/tomokv')
    p.add_argument('--output', type=Path, default=Path('docs/snapfix/pre'))
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--attempts', type=int, default=5)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode in ('1s', '2s'):
        for engine in ('uring', 'epoll'):
            for defect, mix in (('XS-SHUT-1', 'scripts'),
                                ('SNAP-STORM-1', 'execs,writers'),
                                ('SNAP-STORM-1', 'scripts,writers')):
                label = f'{mode}-{engine}-{defect}-{mix.replace(",", "-")}'
                out = args.output/label
                cmd = ['taskset', '-c', '24-31', 'python3', 'tests/at412_diagnostics.py',
                       '--binary', args.binary, '--defect', defect, '--mode', mode,
                       '--engine', engine, '--cores', '16-23', '--port', '20200',
                       '--atomic', '1', '--attempts', str(args.attempts),
                       '--seconds', str(args.seconds), '--mix', mix, '--pre-control',
                       '--output', str(out)]
                started = time.monotonic()
                with (args.output/(label+'.log')).open('w') as log:
                    child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                             start_new_session=True)
                    timed_out = False
                    try:
                        rc = child.wait(timeout=args.attempts*(args.seconds+15)+15)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(child.pid, signal.SIGKILL)
                        rc = child.wait()
                row = dict(label=label, argv=cmd, rc=rc, timeout=timed_out,
                           seconds=round(time.monotonic()-started, 3))
                rows.append(row)
                print(json.dumps(row), flush=True)
                (args.output/'runs.json').write_text(json.dumps(dict(
                    binary=str(Path(args.binary).resolve()),
                    sha256=hashlib.sha256(Path(args.binary).read_bytes()).hexdigest(),
                    rows=rows), indent=2)+'\n')


if __name__ == '__main__':
    main()
