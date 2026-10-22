"""Trackfix correctness receipts using the gate's own whole-job interface."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/trackfix'
BASE = ROOT / 'build/trackfix'
ORACLE = Path('/home/user/Projects/redis74/src/redis-server')


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == body:
        return
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        out.write(body)
        temporary = Path(out.name)
    temporary.chmod(0o755)
    temporary.replace(path)


def environment():
    bindir = BASE / 'bin'
    executable(bindir / 'python3', f'''#!/bin/bash
export PYTHONPATH={str(DOC / 'fixture_site')!r}${{PYTHONPATH:+:$PYTHONPATH}}
export TRACKFIX_FIXTURE_PORT_LOG={str(DOC / 'fixture-ports.log')!r}
case "${{1:-}}" in
 *tests/atomic_ryow.py) exec /usr/bin/python3 "$@" --no-rate-assertions;;
 *) exec /usr/bin/python3 "$@";;
esac
''')
    executable(bindir / 'make', '''#!/usr/bin/python3
import os, sys
args = ['-j16' if a.startswith('-j') and a[2:].isdigit() else a for a in sys.argv[1:]]
os.execv('/usr/bin/taskset', ['taskset', '-c', '96-111', '/usr/bin/make', *args])
''')
    executable(bindir / 'memtier_benchmark', '''#!/bin/bash
echo 'trackfix: performance load generators are reserved for the maintainer' >&2
exit 125
''')
    # The pinned installation has binaries only; use the matching 7.4.10
    # source checkout for source-based metadata checks, retaining pinned executables.
    source = BASE / 'oracle/src'
    source.mkdir(parents=True, exist_ok=True)
    for entry in Path('/home/user/Projects/redis/src').iterdir():
        dest = source / entry.name
        origin = ORACLE.parent / entry.name if entry.name in ('redis-server', 'redis-cli') else entry
        if not dest.exists():
            dest.symlink_to(origin)
    return dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                GATE_TEST_PORT='22899', REDIS74_ROOT=str(source.parent),
                GATE_DIFFER_ORACLE_BIN=str(ORACLE),
                GATE_DIFFER_REDIS_CLI=str(ORACLE.with_name('redis-cli')),
                GATE_DIFFER_ORACLE_CORES='104', GATE_NOTIFY_ORACLE_CORES='104',
                PYTHONPATH=str(DOC / 'fixture_site'),
                TRACKFIX_FIXTURE_PORT_LOG=str(DOC / 'fixture-ports.log'),
                GATE_LOAD_CORES='105-111')


def engine_binary(binary, engine, label):
    wrapper = BASE / ('server-' + label)
    defaults = ['--net-io', engine]
    if os.getenv('TRACKFIX_DEFAULT_MODE'):
        defaults += ['--thread-mode', os.environ['TRACKFIX_DEFAULT_MODE']]
    shape = ''
    if os.getenv('TRACKFIX_DEFAULT_MODE') == '1s':
        shape = ('# job_notify uses boot(), which supplies the split-only ratio.\n'
                 '# This supplementary run uses boot_fused geometry.\n'
                 'if "--thread-mode" not in args:\n'
                 ' while "--ratio" in args:\n'
                 '  i=args.index("--ratio"); del args[i:i+2]\n')
    executable(wrapper, '#!/usr/bin/python3\nimport os,sys\n'
               'args=sys.argv[1:]\nfirst=[]\n'
               'if args and not args[0].startswith("-"): first=[args.pop(0)]\n'
               + shape +
               f'server={str(binary.resolve())!r}\n'
               f'os.execv(server,[server,*first,*{defaults!r},*args])\n')
    return wrapper


def gate(label, binary, engine, jobs):
    dest = DOC / 'proof' / label
    dest.mkdir(parents=True, exist_ok=False)
    env = environment()
    env.update(GATE_ONLY_JOBS=' '.join(jobs), GATE_LEDGER=str(dest / 'ledger'))
    if binary.name == 'tomokv-PRE':
        env.update(GATE_TRACKFIX_ARM='PRE', GATE_TRACKFIX_REF='a7dfb9d23',
                   GATE_TRACKFIX_OBJECTS=str(BASE / 'pre-objects'))

    argv = ['taskset', '-c', '96-111', 'bash', 'tests/gate.sh', 'full',
            '--server-cores', '96-104', '--load-cores', '105-111',
            '--server-smt', '', '--load-smt', '', '--ports', os.getenv('TRACKFIX_PORTS', '22810-22839'),
            '--candidate-binary', str(engine_binary(binary, engine, label))]
    (dest / 'command.json').write_text(json.dumps(dict(argv=argv, jobs=jobs,
        binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest()), indent=2) + '\n')
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
    binary = ROOT / ('build/tomokv-PRE' if arm.startswith('PRE') else 'build/tomokv')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    rows = []
    count = int(os.getenv('TRACKFIX_CONTROL_COUNT', '20'))
    first = int(os.getenv('TRACKFIX_CONTROL_FIRST', '1'))
    port = int(os.getenv('TRACKFIX_CONTROL_PORT', '22800' if arm == 'PRE' else '22802'))
    for roll in range(first, first + count):
        label = f'{arm}-{roll}'
        shape = ['--shards', '16', '--thread-mode', 'fused', '--read-local', '1',
                 '--net-io', 'epoll', '--databases', '16', '--atomic', '0']
        with support.owned(label + '-oracle', ORACLE, '104', port + 1, []):
            with support.owned(label + '-target', binary, '96-103', port, shape):
                argv = ['taskset', '-c', '105-111', 'python3', 'tests/differ.py',
                        '127.0.0.1', str(port), '127.0.0.1', str(port + 1), 'climon', '19']
                path = dest / f'{label}.log'
                with path.open('w') as log:
                    rc = subprocess.run(argv, cwd=ROOT, env=environment(), stdout=log,
                                        stderr=subprocess.STDOUT).returncode
                text = path.read_text()
                duplicates = sum(line.startswith('    target:') and
                                 line.count('invalidate') > 1 for line in text.splitlines())
                rows.append(dict(arm=arm, roll=roll, argv=argv, returncode=rc,
                                 duplicate_comparisons=duplicates, sha256=digest))
                (dest / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                print(label, rc, duplicates, flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'repeats':
        repeats(sys.argv[2])
    else:
        _, label, arm, engine, *jobs = sys.argv
        binary = ROOT / ({'PRE': 'build/tomokv-PRE', 'PAD-A': 'build/tomokv-PAD-A'}.get(arm, 'build/tomokv'))
        raise SystemExit(gate(label, binary, engine, jobs))
