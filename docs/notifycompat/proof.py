#!/usr/bin/env python3
"""Run selected correctness jobs through gate.sh and retain their exact receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name')
    p.add_argument('jobs', nargs='+')
    p.add_argument('--arm', choices=('PRE', 'POST'), default='POST')
    p.add_argument('--engine', choices=('uring', 'epoll'))
    p.add_argument('--fused', action='store_true')
    p.add_argument('--ports', default='32800-32889')
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(48, 64))
    first, last = map(int, a.ports.split('-'))
    assert 32800 <= first <= last <= 32899
    output = ROOT / 'docs/notifycompat' / a.name
    binary = ROOT / ('build/tomokv-pre' if a.arm == 'PRE' else 'build/tomokv')
    original = binary
    binary = ROOT / 'build/notifycompat/arms' / (a.name + '-tomokv')
    binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, binary)
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
        script += f'os.execv({str(binary)!r}, [{str(binary)!r}] + {extra!r} + args)\n'
        target.write_text(script)
        target.chmod(0o755)
    env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis',
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
               GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli',
               GATE_ONLY_JOBS=' '.join(a.jobs), GATE_NOTIFYCOMPAT_ARM=a.arm,
               GATE_NOTIFYCOMPAT_OBJECTS=str(ROOT / ('build/notifycompat-pre' if a.arm == 'PRE' else 'build')),
               GATE_LEDGER=str(output) + '.ledger')
    if a.arm == 'PRE':
        env['GATE_NOTIFYCOMPAT_REF'] = 'ef5204b2e'
    cmd = ['taskset', '-c', '48-63', 'tests/gate.sh', 'full',
           '--server-cores', '48-55', '--load-cores', '56-63',
           '--ports', a.ports, '--candidate-binary', str(target)]
    receipt = dict(command=cmd, cwd=str(a.root), jobs=a.jobs, arm=a.arm,
                   engine=a.engine, fused=a.fused, binary=str(binary), source_binary=str(original),
                   sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   environment={k: v for k, v in env.items() if k.startswith('GATE_') or k == 'REDIS74_ROOT'})
    receipt['test_sources'] = {
        str(path.relative_to(a.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ('tests', 'tools') for path in sorted((a.root / folder).rglob('*'))
        if path.is_file() and path.suffix in ('.py', '.sh', '.cc', '.json')}
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
