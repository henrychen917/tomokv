"""Trackfix correctness receipts using the gate's own whole-job interface."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/trackfix'
BASE = ROOT / 'build/trackfix'
ORACLE = Path('/home/user/Projects/redis74/src/redis-server')


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def environment():
    bindir = BASE / 'bin'
    executable(bindir / 'make', '''#!/usr/bin/python3
import os, sys
args = ['-j16' if a.startswith('-j') and a[2:].isdigit() else a for a in sys.argv[1:]]
os.execv('/usr/bin/taskset', ['taskset', '-c', '96-111', '/usr/bin/make', *args])
''')
    executable(bindir / 'memtier_benchmark', '''#!/bin/bash
echo 'trackfix: performance load generators are reserved for the maintainer' >&2
exit 125
''')
    return dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                GATE_TEST_PORT='22899', REDIS74_ROOT=str(ORACLE.parent.parent),
                GATE_DIFFER_ORACLE_BIN=str(ORACLE),
                GATE_DIFFER_REDIS_CLI=str(ORACLE.with_name('redis-cli')),
                GATE_DIFFER_ORACLE_CORES='104', GATE_NOTIFY_ORACLE_CORES='104',
                GATE_LOAD_CORES='105-111')


def engine_binary(binary, engine, label):
    wrapper = BASE / ('server-' + label)
    executable(wrapper, '#!/usr/bin/python3\nimport os,sys\n'
               'args=sys.argv[1:]\nfirst=[]\n'
               'if args and not args[0].startswith("-"): first=[args.pop(0)]\n'
               f'server={str(binary.resolve())!r}\n'
               f'os.execv(server,[server,*first,"--net-io",{engine!r},*args])\n')
    return wrapper


def gate(label, binary, engine, jobs):
    dest = DOC / 'proof' / label
    dest.mkdir(parents=True, exist_ok=False)
    env = environment()
    env.update(GATE_ONLY_JOBS=' '.join(jobs), GATE_LEDGER=str(dest / 'ledger'))
    argv = ['taskset', '-c', '96-111', 'bash', 'tests/gate.sh', 'full',
            '--server-cores', '96-104', '--load-cores', '105-111',
            '--server-smt', '', '--load-smt', '', '--ports', '22810-22839',
            '--candidate-binary', str(engine_binary(binary, engine, label))]
    (dest / 'command.json').write_text(json.dumps(dict(argv=argv, jobs=jobs), indent=2) + '\n')
    with (dest / 'gate.log').open('w') as log:
        rc = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    (dest / 'returncode').write_text(str(rc) + '\n')
    print(label, rc, flush=True)
    return rc


def repeats(arm):
    spec = importlib.util.spec_from_file_location('support', ROOT / 'docs/wave4/run_supplemental.py')
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    support.ROOT = ROOT
    support.OUT = BASE / 'tracking-controls' / arm
    dest = DOC / 'tracking-controls' / arm
    dest.mkdir(parents=True, exist_ok=False)
    binary = ROOT / ('build/tomokv-PRE' if arm == 'PRE' else 'build/tomokv')
    rows = []
    for roll in range(1, 21):
        label = f'{arm}-{roll}'
        shape = ['--shards', '16', '--thread-mode', 'fused', '--read-local', '1',
                 '--net-io', 'epoll', '--databases', '16', '--atomic', '0']
        with support.owned(label + '-oracle', ORACLE, '104', 22801, []):
            with support.owned(label + '-target', binary, '96-103', 22800, shape):
                argv = ['taskset', '-c', '105-111', 'python3', 'tests/differ.py',
                        '127.0.0.1', '22800', '127.0.0.1', '22801', 'climon', '19']
                path = dest / f'{label}.log'
                with path.open('w') as log:
                    rc = subprocess.run(argv, cwd=ROOT, env=environment(), stdout=log,
                                        stderr=subprocess.STDOUT).returncode
                text = path.read_text()
                duplicates = sum(line.startswith('    target:') and
                                 line.count('invalidate') > 1 for line in text.splitlines())
                rows.append(dict(arm=arm, roll=roll, argv=argv, returncode=rc,
                                 duplicate_comparisons=duplicates))
                (dest / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                print(label, rc, duplicates, flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'repeats':
        repeats(sys.argv[2])
    else:
        _, label, arm, engine, *jobs = sys.argv
        binary = ROOT / ('build/tomokv-PRE' if arm == 'PRE' else 'build/tomokv')
        raise SystemExit(gate(label, binary, engine, jobs))
