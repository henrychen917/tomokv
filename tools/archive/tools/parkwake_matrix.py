#!/usr/bin/env python3
"""parkwake: run tests/parkwake.py over every declared case x mode x engine for one arm.

usage: parkwake_matrix.py --arm NAME --binary PATH --output DIR [--diag] [--cases ...]
Each row is one tests/parkwake.py invocation (the gate's own job body), server CPUs 32-39,
load CPUs 40-47, port 23300. --diag selects the diagnostic arm's bounded call counts (a missed
wake costs 2 s there, so the long forms run only a few calls). Prints one summary line per row
and writes DIR/ARM/summary.json. No rates are measured.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ROWS = [(c, m, e) for c in ('retry', 'control', 'epoch', 'slotless', 'watchdog')
        for m in ('2s', '1s') for e in ('uring', 'epoll')] + \
       [('script', '2s', e) for e in ('uring', 'epoll')] + \
       [('swapdb', '2s', 'epoll')]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--arm', required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--diag', action='store_true')
    p.add_argument('--cases', nargs='*')
    a = p.parse_args()
    out = a.output / a.arm
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for case, mode, engine in ROWS:
        if a.cases and case not in a.cases:
            continue
        if case == 'swapdb' and not a.diag:
            continue   # F3's live window needs the diagnostic arm (the gate uses the unit)
        databases = '16' if case in ('watchdog', 'swapdb') else '16,1'
        argv = [sys.executable, str(ROOT / 'tests/parkwake.py'), '--binary', str(a.binary),
                '--case', case, '--cores', '32-39', '--port', '23300', '--mode', mode,
                '--engine', engine, '--databases', databases,
                '--output', str(out / f'{case}-{mode}-{engine}')]
        if a.diag:
            argv += ['--conn-timeout', '150']
            argv += {'retry': ['--calls', '4'], 'control': ['--config-calls', '4', '--unpause-calls', '4'],
                     'epoch': ['--calls', '20'], 'slotless': ['--rounds', '3'],
                     'swapdb': ['--calls', '30', '--deadline-ms', '1000']}.get(case, [])
        t0 = time.monotonic()
        run = subprocess.run(['taskset', '-c', '40-47', *argv], capture_output=True, text=True,
                             env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}, timeout=3600)
        legs = []
        for line in run.stdout.splitlines():
            try:
                legs.append(json.loads(line))
            except ValueError:
                pass
        row = dict(case=case, mode=mode, engine=engine, rc=run.returncode, seconds=round(time.monotonic() - t0, 1),
                   legs=[{k: v for k, v in leg.items() if k not in ('traceback',)} for leg in legs])
        summary.append(row)
        print(json.dumps(dict(row=f'{case}-{mode}-{engine}', rc=run.returncode,
                              reasons=[r for leg in legs for r in leg.get('reasons', [])][:4])), flush=True)
        (out / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
