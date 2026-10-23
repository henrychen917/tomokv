#!/usr/bin/env python3
"""Run selected correctness jobs through gate.sh and retain their exact receipts."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name')
    p.add_argument('jobs', nargs='+')
    p.add_argument('--arm', choices=('PRE', 'POST', 'PAD-A'), default='POST')
    p.add_argument('--engine', choices=('uring', 'epoll'))
    p.add_argument('--fused', action='store_true')
    p.add_argument('--ports', default='32803-32839')
    p.add_argument('--server-cores', default='48-55')
    p.add_argument('--load-cores', default='56-63')
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(48, 64))
    first, last = map(int, a.ports.split('-'))
    assert 32800 <= first <= last <= 32899
    # These assigned listener ports overlap Linux's ephemeral range. Normal
    # unbound connect() prefers even ports; use an odd listener base while
    # retaining the gate's complete three-port slot and recording the range.
    requested_ports = a.ports
    first += first % 2 == 0
    assert last - first >= 2
    a.ports = f'{first}-{last}'
    def cpus(spec):
        result = set()
        for token in spec.split(','):
            bounds = list(map(int, token.split('-')))
            result.update(range(bounds[0], bounds[-1] + 1))
        return result
    server_cpus, load_cpus = cpus(a.server_cores), cpus(a.load_cores)
    assert len(server_cpus) == len(load_cpus) == 8 and not server_cpus & load_cpus
    assert server_cpus | load_cpus == set(range(48, 64))
    output = ROOT / 'docs/notifycompat' / a.name
    lock_path = ROOT / 'build/notifycompat' / (a.name + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('w')
    fcntl.flock(lock, fcntl.LOCK_EX)
    binary = ROOT / {'PRE': 'build/tomokv-pre', 'POST': 'build/tomokv',
                     'PAD-A': 'build/tomokv-pad-a'}[a.arm]
    original = binary
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    sources = {str(path.relative_to(a.root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for folder in ('tests', 'tools') for path in sorted((a.root / folder).rglob('*'))
               if path.is_file() and path.suffix in ('.py', '.sh', '.cc', '.json')}
    previous = Path(str(output) + '.json')
    if previous.exists():
        old = json.loads(previous.read_text())
        assert (old['jobs'], old['arm'], old['engine'], old['fused'], old['cwd'],
                old['sha256'], old.get('test_sources')) == (
                    a.jobs, a.arm, a.engine, a.fused, str(a.root), digest, sources), \
            'receipt name already used with different inputs; choose a new name'
        print('REUSED completed gate receipt: ' + str(previous), flush=True)
        return
    band = next(low for low, high in ((32800, 32839), (32840, 32859),
                                     (32860, 32879), (32890, 32899))
                if low <= first <= last <= high)
    port_lock = (ROOT / 'build/notifycompat' / f'ports-{band}.lock').open('w')
    fcntl.flock(port_lock, fcntl.LOCK_EX)
    # A bound, non-listening REUSEADDR socket keeps Linux's automatic client
    # port allocation out of the slot between server lifetimes. It neither
    # accepts traffic nor participates in the server's REUSEPORT listener group.
    # Redis and TomoKV already set REUSEADDR; their real listener/boot guards
    # remain authoritative. No host sysctl or application behavior is changed.
    port_guards = []
    guard_started = time.monotonic()
    while True:
        try:
            for port in range(first, first + 3):
                guard = socket.socket()
                port_guards.append(guard)
                guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                guard.bind(('127.0.0.1', port))
            break
        except OSError:
            for guard in port_guards:
                guard.close()
            port_guards.clear()
            if time.monotonic() - guard_started >= 90:
                raise
            time.sleep(1)
    binary = ROOT / 'build/notifycompat/arms' / (digest + '-tomokv')
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists():
        subprocess.run(['cp', '--reflink=auto', '--preserve=all', str(original), str(binary)], check=True)
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
    target = binary
    if a.engine or a.fused:
        target = ROOT / 'build/notifycompat' / (a.name + '-server')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Explicit job engine options remain authoritative. Fused is used only
        # to supplement a historical split-only job, and strips its ratio.
        script = '#!/usr/bin/env python3\nimport os, sys\nargs = sys.argv[1:]\n'
        if a.fused:
            script += "for option in ('--ratio', '--thread-mode', '--read-local'):\n while option in args:\n  i = args.index(option); del args[i:i+2]\n"
        extra = (['--net-io', a.engine] if a.engine else [])
        if a.fused:
            extra += ['--thread-mode', '1s', '--read-local', '1']
        # The config-file grammar requires the path to remain argv[1]. Explicit
        # job options still follow our defaults and therefore remain decisive.
        script += "prefix = args[:1] if args and not args[0].startswith('-') else []\n"
        script += f'os.execv({str(binary)!r}, [{str(binary)!r}] + prefix + {extra!r} + args[len(prefix):])\n'
        target.write_text(script)
        target.chmod(0o755)
    env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis',
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
               GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli',
               GATE_ONLY_JOBS=' '.join(a.jobs), GATE_NOTIFYCOMPAT_ARM=a.arm,
               GATE_NOTIFYCOMPAT_OBJECTS=str(ROOT / ('build' if a.arm == 'POST' else 'build/notifycompat-pre')),
               GATE_LEDGER=str(output) + '.ledger')
    if a.arm != 'POST':
        env['GATE_NOTIFYCOMPAT_REF'] = 'ef5204b2e'
    cmd = ['taskset', '-c', '48-63', 'tests/gate.sh', 'full',
           '--server-cores', a.server_cores, '--load-cores', a.load_cores,
           '--ports', a.ports, '--candidate-binary', str(target)]
    receipt = dict(command=cmd, cwd=str(a.root), jobs=a.jobs, arm=a.arm,
                   engine=a.engine, fused=a.fused, binary=str(binary), source_binary=str(original),
                   requested_ports=requested_ports,
                   nonlistening_port_guards=list(range(first, first + 3)),
                   port_guard_wait_seconds=time.monotonic() - guard_started,
                   sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   environment={k: v for k, v in env.items() if k.startswith('GATE_') or k == 'REDIS74_ROOT'})
    receipt['proof_driver_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if target != binary:
        receipt['candidate_wrapper'] = target.read_text()
    receipt['test_sources'] = sources
    with Path(str(output) + '.log').open('w') as log:
        result = subprocess.run(cmd, cwd=a.root, env=env, stdout=log, stderr=subprocess.STDOUT)
    receipt['exit'] = result.returncode
    log = Path(str(output) + '.log').read_text()
    match = re.search(r'artifacts: (\S+)', log)
    if match:
        directory = Path(match[1])
        receipt['artifacts'] = str(directory)
        # Retain protocol logs, row outcomes, boot commands, and hook receipts;
        # omit data files and disposable executables/objects.
        with tarfile.open(str(output) + '.evidence.tar.gz', 'w:gz') as archive:
            for path in sorted(directory.rglob('*')):
                if path.is_file() and (path.suffix in ('.log', '.json', '.tsv', '.sh', '.txt', '.held', '.replayed')
                                       or path.name.startswith('gate-srv-')
                                       or path.name in ('ledger', 'timings')):
                    archive.add(path, arcname=str(path.relative_to(directory)))
    Path(str(output) + '.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == '__main__':
    main()
