#!/usr/bin/env python3
"""Run the audit's T12/T12b scripts without touching their originals.

Only paths, ports and CPUs are adapted (round-4 netlib: tomo binary, Redis 7.4.10
oracle path, tomo CPUs 64-71, Redis CPU 72, ports 22536-22539 -> 25436-25439); the
driver runs on 73-79. The scripts' measurement code is unchanged. The NT4 probe has
its own driver (tools/respresume_probe.py).
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NETLIB = Path('/home/user/Projects/round4-read/tests/net/netlib.py')
REDIS = '/home/user/Projects/redis74/src/redis-server'


def replace_once(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def prepare(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    netlib = NETLIB.read_text()
    netlib = replace_once(netlib, '"/home/user/Projects/bench-bins/tomokv-headline-6b50f447f"',
                          repr(str(args.binary.resolve())))
    netlib = replace_once(netlib, '"/tmp/claude-1000/redis74/src/redis-server"', repr(REDIS))
    netlib = replace_once(netlib, 'CORES = "96-111"', 'CORES = "64-71"\nREDIS_CORES = "72"')
    netlib = replace_once(netlib, 'cmd = ["taskset", "-c", CORES, self.binary]',
                          'cmd = ["taskset", "-c", CORES if kind == "tomo" else REDIS_CORES, self.binary]')
    netlib = replace_once(netlib, '22500 <= port <= 22599', '25400 <= port <= 25449')
    (out / 'netlib.py').write_text(netlib)
    scripts = []
    for name in ('t12_multibulk_reparse.py', 't12b_multibulk_stall.py'):
        code = (ROOT / 'docs/respresume/audit' / name).read_text()
        code = replace_once(code, '/home/user/Projects/round4-read/tests/net', str(out))
        for old, new in ((22536, 25436), (22537, 25437), (22538, 25438), (22539, 25439)):
            if str(old) in code:
                code = replace_once(code, str(old), str(new))
        (out / name).write_text(code)
        scripts.append(out / name)
    return scripts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(73, 80)), 'pin the driver to 73-79'
    scripts = prepare(args)
    (args.output / 'binary.sha256').write_text(
        hashlib.sha256(args.binary.read_bytes()).hexdigest() + '  ' + str(args.binary) + '\n')
    for script in scripts:
        with (args.output / (script.stem + '.out')).open('w') as log:
            subprocess.run([sys.executable, str(script)], cwd=args.output, stdout=log,
                           stderr=subprocess.STDOUT, timeout=900, check=True)
        print((args.output / (script.stem + '.out')).read_text(), end='', flush=True)


if __name__ == '__main__':
    main()
