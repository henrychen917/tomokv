#!/usr/bin/env python3
"""Prepare/run the supplied audit scripts without touching their originals.

`prepare` creates local path/port/CPU adaptations; `run` is for the maintainer's
reserved runtime slot. T12/T12b code is otherwise unchanged. Probe arming accepts
POST retention only after an actual Incomplete event, and requires zero replay.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    netlib = Path('/home/user/Projects/round4-read/tests/net/netlib.py').read_text()
    netlib = netlib.replace('/home/user/Projects/bench-bins/tomokv-headline-6b50f447f', str(args.binary.resolve()))
    netlib = netlib.replace('/tmp/claude-1000/redis74/src/redis-server', '/home/user/Projects/redis74/src/redis-server')
    netlib = netlib.replace('CORES = "96-111"', 'CORES = "112-119"')
    netlib = netlib.replace('22500 <= port <= 22599', '25400 <= port <= 25449')
    (out / 'netlib.py').write_text(netlib)
    scripts = []
    for name in ('t12_multibulk_reparse.py', 't12b_multibulk_stall.py'):
        code = (ROOT / 'docs/respresume/audit' / name).read_text()
        code = code.replace('/home/user/Projects/round4-read/tests/net', str(out))
        for old, new in ((22536, 25436), (22537, 25437), (22538, 25438), (22539, 25439)):
            code = code.replace(str(old), str(new))
        p = out / name
        p.write_text(code)
        scripts.append(p)
    # The audit probe depends on lane perfio's boot helper, which was not part
    # of the supplied archive. Snapshot that helper locally; never edit its lane.
    helper = Path('/home/user/Projects/cx-perfio/tests/perfio.py')
    (out / 'perfio.py').write_text(helper.read_text())
    code = (ROOT / 'docs/respresume/audit/nt4_probe.py').read_text()
    code = code.replace('ROOT = Path(__file__).resolve().parents[2]', f'ROOT = Path({str(ROOT)!r})')
    if args.post:
        code = code.replace('assert int(fired["perfio_reparsed_arguments"]) > int(armed["perfio_reparsed_arguments"])',
                            'assert int(fired["perfio_reparsed_arguments"]) == int(armed["perfio_reparsed_arguments"])')
        code = code.replace('assert delta[2] >= 1_000_000, delta',
                            'assert delta[2] >= 1_000_000, delta\n                assert delta[1] == 0, delta')
    (out / 'nt4_probe.py').write_text(code)
    commands = [['taskset', '-c', '112-127', sys.executable, str(p)] for p in scripts]
    for mode in ('1s', '2s'):
        for cell in ('MSET-64-p8-c512', 'SET-1024-p32-c512'):
            commands.append(['taskset', '-c', '112-127', sys.executable, str(out / 'nt4_probe.py'),
                             '--binary', str(args.observer.resolve()), '--port', '25410',
                             '--output', str(out / f'probe-{mode}-{cell}'), '--only', f'{mode}-{cell}'])
    (out / 'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    return commands


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['prepare', 'run'])
    ap.add_argument('--binary', type=Path, required=True)
    ap.add_argument('--observer', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--post', action='store_true')
    args = ap.parse_args()
    commands = prepare(args)
    if args.action == 'run':
        assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin driver to 112-127'
        for i, command in enumerate(commands):
            with (args.output / f'run-{i}.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=300, check=True)
    print(args.output / 'commands.json')


if __name__ == '__main__': main()
