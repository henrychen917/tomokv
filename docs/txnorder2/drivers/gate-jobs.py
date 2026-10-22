#!/usr/bin/env python3
"""Run complete selected correctness jobs through the gate's own dispatcher.

This never requests iteration, ABBA, NIC or a full source receipt. Preserve the
PARTIAL designation, every job completion record, and small textual evidence.
Binary data and large artifacts are represented by size and SHA-256 only.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suffix', default='final2c')
    p.add_argument('--binary', default=str(ROOT / 'build/tomokv'))
    p.add_argument('--jobs')
    p.add_argument('--server-cores', default='64-71')
    p.add_argument('--load-cores', default='72-95')
    args = p.parse_args()
    out = ROOT / 'docs/txnorder2' / ('gate-' + args.suffix)
    out.mkdir(parents=True, exist_ok=False)
    jobs = args.jobs or ' '.join(json.loads(
        (ROOT / 'docs/txnorder2/resume/scope.json').read_text())['gate_jobs'])
    binary = Path(args.binary).resolve()
    env = dict(GATE_ONLY_JOBS=jobs, GATE_LEDGER=str(out / 'ledger.tsv'),
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
               GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',
               # redis74 contains only the pinned executables. The gate also
               # validates source metadata; this is the matching 7.4.10 tree.
               REDIS74_ROOT='/home/user/Projects/redis')
    command = ['taskset', '-c', '64-95', 'bash', 'tests/gate.sh', 'full',
               '--server-cores', args.server_cores, '--server-smt', '',
               '--load-cores', args.load_cores, '--load-smt', '',
               '--ports', '27820-27889', '--candidate-binary', str(binary)]
    before_dirs = set((ROOT / 'build').glob('gate-run.*'))
    result = dict(command=command, environment=env, started=time.time(),
                  binary=str(binary), sha256=digest(binary), status='RUNNING')
    receipt = out / 'result.json'

    def save():
        receipt.write_text(json.dumps(result, indent=2) + '\n')

    save()
    with (out / 'console.log').open('w') as f:
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, **env),
                                   stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        result['pid'] = process.pid
        save()
        result['returncode'] = process.wait()
    result['finished'] = time.time()
    result['sha256_after'] = digest(binary)
    result['stable_binary'] = result['sha256'] == result['sha256_after']
    created = set((ROOT / 'build').glob('gate-run.*')) - before_dirs
    assert len(created) == 1, sorted(map(str, created))
    run = created.pop()
    result['run_dir'] = str(run)
    result['jobs'] = {f.parent.name: f.read_text().strip()
                      for f in sorted((run / 'jobs').glob('*/done'))}
    excluded = []
    for source in sorted(run.rglob('*')):
        if not source.is_file() or source.is_symlink():
            continue
        relative = source.relative_to(run)
        size = source.stat().st_size
        with source.open('rb') as f:
            prefix = f.read(min(size, 8192))
        if size > 1_000_000 or b'\0' in prefix or source.suffix in ('.gz', '.rdb', '.tomo', '.o'):
            excluded.append(dict(path=str(relative), bytes=size, sha256=digest(source)))
            continue
        target = out / 'run' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (out / 'excluded-artifacts.json').write_text(json.dumps(excluded, indent=2) + '\n')
    ledger = (out / 'ledger.tsv.partial').read_text().splitlines()
    result['ledger_verdicts'] = dict(collections.Counter(
        row.split('\t')[0] for row in ledger if row.startswith(('ok\t', 'FAIL\t'))))
    result['status'] = 'PASS' if result['returncode'] == 0 and result['stable_binary'] else 'FAIL'
    save()
    print(json.dumps({k: v for k, v in result.items() if k not in ('jobs', 'environment')}, indent=2))


if __name__ == '__main__':
    main()
