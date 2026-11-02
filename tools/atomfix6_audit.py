#!/usr/bin/env python3
"""Run a copied round-5 correctness detector inside this lane's CPU/port limits.

Only lifecycle defaults change; detector code and assertions are copied verbatim.
T01/T03 rate/perf collection is deliberately left to the maintainer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
AUDIT = Path('/home/user/Projects/round5-read/tests/server-atomics')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--read-local', choices=['0', '1'], default='0')
    p.add_argument('--databases', choices=['1', '16'], default='16')
    p.add_argument('--engine', choices=['uring', 'epoll'], default='uring')
    p.add_argument('script', choices=['t07_flush_torn.py', 't08_torn_freeze.py',
        't15_torn_capture.py', 't16_capture_dump.py', 't17_capture_freeze.py'])
    p.add_argument('arguments', nargs='+')
    a = p.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
    assert 21700 <= int(a.arguments[0]) <= 21799
    a.output = a.output.resolve()
    source = a.output / 'source'
    source.mkdir(parents=True, exist_ok=True)
    digests = {}
    for path in sorted(AUDIT.glob('*.py')):
        data = path.read_bytes()
        digests[path.name] = hashlib.sha256(data).hexdigest()
        (source / path.name).write_bytes(data)
    path = source / 'resp.py'
    s = path.read_text()
    s = s.replace('HEADLINE = "/home/user/Projects/bench-bins/tomokv-headline-105c5818cc"',
                  'HEADLINE = os.environ["ATOMFIX6_BINARY"]')
    s = s.replace('LOGS = os.path.join(HERE, "logs")', 'LOGS = os.environ["ATOMFIX6_LOGS"]')
    s = s.replace('assert 22600 <= port <= 22699', 'assert 21700 <= port <= 21799')
    marker = '        if port_open(port):'
    assert s.count(marker) == 1
    s = s.replace(marker, '''        cpus = "74-81"
        if not oracle:
            args = list(args) + ["--shards", "16",
                "--read-local", os.environ["ATOMFIX6_READ_LOCAL"],
                "--databases", os.environ["ATOMFIX6_DATABASES"],
                "--net-io", os.environ["ATOMFIX6_ENGINE"]]
            if not ("--thread-mode" in args and args[args.index("--thread-mode") + 1] == "1s"):
                args += ["--ratio", "6:2"]
''' + marker)
    path.write_text(s)
    env = dict(os.environ, LC_ALL='C', ATOMFIX6_BINARY=str(a.binary.resolve()),
               ATOMFIX6_LOGS=str(a.output / 'logs'), ATOMFIX6_READ_LOCAL=a.read_local,
               ATOMFIX6_DATABASES=a.databases, ATOMFIX6_ENGINE=a.engine)
    argv = ['python3', '-u', str(source / a.script), *a.arguments]
    (a.output / 'source-sha256.json').write_text(json.dumps(digests, indent=2) + '\n')
    (a.output / 'argv.json').write_text(json.dumps(argv) + '\n')
    with (a.output / 'result.log').open('w') as log:
        result = subprocess.run(argv, env=env, cwd=source, stdout=log, stderr=subprocess.STDOUT)
    print((a.output / 'result.log').read_text(), end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
