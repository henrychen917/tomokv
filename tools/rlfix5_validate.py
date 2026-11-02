#!/usr/bin/env python3
"""Run selected gate jobs within the rlfix5 CPU/port allocation and retain receipts."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import blockfix2_receipts as receipts
from wave13_counts import sha

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/rlfix5/jobs'


def retire_private_builds(root):
    """Drop archived, completed jobs' disposable ELF files; retain release outputs."""
    assert root.parent == ROOT / 'build' and root.name.startswith('gate-run.')
    retired = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as file:
            if file.read(4) != b'\x7fELF':
                continue
        retired.append(dict(path=str(path.relative_to(root)), bytes=path.stat().st_size,
                            sha256=sha(path)))
        path.unlink()
    return retired


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tag')
    p.add_argument('--jobs-file', type=Path, required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/rlfix5/POST')
    p.add_argument('--fused', action='store_true')
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(24, 32))
    names = a.jobs_file.read_text().split()
    assert names and not {'flip_saturated', 'efficiency', 'tailgen_build', 'zc'} & set(names)
    DOC.mkdir(parents=True, exist_ok=True)
    assert not (DOC / (a.tag + '.json')).exists(), 'use a fresh attempt tag'
    binary = a.binary.resolve(); digest = sha(binary)
    boot_binary = binary
    if binary == ROOT / 'build/rlfix5/POST':
        # Legacy transaction jobs locate matching native helpers beside the
        # server. Keep the three delivery arms separate, and boot an immutable
        # byte-identical POST copy beside job_production_units' real outputs.
        boot_binary = ROOT / 'build' / ('rlfix5-POST-' + digest[:12])
        if not boot_binary.exists():
            shutil.copy2(binary, boot_binary)
        assert sha(boot_binary) == digest
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
        GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',
        GATE_PROOF_NO_RATES='1', GATE_NET_IO=a.engine, GATE_PROOF_NET_IO=a.engine,
        GATE_DIFFER_NET_IO=a.engine, GATE_ONLY_JOBS=' '.join(names),
        GATE_TEST_PORT='21598', GATE_LEDGER=str(DOC / a.tag),
        CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    if a.fused:
        env['GATE_TXN_FUSED'] = '1'
    cmd = ['taskset', '-c', '24-31', 'tests/gate.sh', 'full', '--shared-correctness-cpus',
           '--server-cores', '24-31', '--load-cores', '24-31', '--server-smt', '', '--load-smt', '',
           '--ports', '21500-21599', '--candidate-binary', str(boot_binary)]
    metadata = dict(command=cmd, binary_sha256=digest, engine=a.engine,
        frozen_binary=str(binary), boot_binary=str(boot_binary),
        env={k: v for k, v in env.items() if k.startswith('GATE_') or k in ('LC_ALL', 'CXX', 'CC', 'REDIS74_ROOT')})
    (DOC / (a.tag + '-started.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    with (DOC / (a.tag + '.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    runs = re.findall(r'^  artifacts: (.+)$', (DOC / (a.tag + '.log')).read_text(), re.M)
    assert len(runs) == 1, runs
    root = Path(runs[0]); assert root.parent == ROOT / 'build'
    # The gate's feature cells use a shared artifact directory outside RUN_DIR.
    # Bring their raw result/boot evidence into this attempt's archive as well.
    output = (DOC / (a.tag + '.log')).read_text()
    for path in root.glob('jobs/feature-cell-*/output.log'):
        output += path.read_text()
    feature_roots = sorted(set(re.findall(re.escape(str(ROOT / 'build')) +
                                         r'/gate-feature\.[A-Za-z0-9]+', output)))
    for name in feature_roots:
        directory = Path(name)
        assert directory.parent == ROOT / 'build'
        for path in directory.rglob('*'):
            if path.is_file() and not path.is_symlink() and receipts.selected(path, directory):
                target = root / 'feature-matrix' / directory.name / path.relative_to(directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    record = receipts.collect(a.tag, root, DOC)
    record.update(metadata, exit_code=result.returncode)
    assert sha(binary) == digest, 'candidate changed during proof'
    assert sha(boot_binary) == digest, 'boot copy changed during proof'
    record['retired_build_artifacts'] = retire_private_builds(root)
    (DOC / (a.tag + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(a.tag, 'exit', result.returncode, 'passed', sum(j['passed'] for j in record['jobs']),
          'failed', sum(j['failed'] for j in record['jobs']), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
