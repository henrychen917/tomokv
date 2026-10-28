#!/usr/bin/env python3
"""Run selected whole gate jobs serially on the lane's CPUs and ports."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl
import blockfix2_receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stages', nargs='+', choices=('directed', 'broad', 'tcl',
        'tcl-negative', 'differ-uring', 'differ-epoll', 'pre', 'pad-a'))
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    output = ROOT / 'docs/blockfix3/gate-receipts'
    output.mkdir(parents=True, exist_ok=True)
    folder = ROOT / 'build/blockfix3'
    for stage in args.stages:
        label = args.tag + '-' + stage
        assert not (output / (label + '.json')).exists(), label
        binary = ROOT / 'build/tomokv'
        tier = 'quick'
        env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis',
            GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
            GATE_PROOF_NO_RATES='1',
            GATE_LEDGER=str(folder / (label + '.ledger')))
        if stage == 'broad':
            jobs = (ROOT / 'docs/blockfix3/required-jobs.txt').read_text().strip()
        elif stage.startswith('differ-'):
            tier = 'full'
            jobs = 'differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence'
            env['GATE_DIFFER_NET_IO'] = stage.split('-', 1)[1]
        elif stage in ('tcl', 'tcl-negative'):
            jobs = 'redis_tcl'
            if stage == 'tcl-negative': binary = folder / 'controls/statistics/tomokv'
        else:
            jobs = 'blockfix2'
            env['GATE_BLOCKFIX2_CONTROLS'] = '1' if stage == 'directed' else '0'
            if stage in ('pre', 'pad-a'): binary = folder / stage / 'tomokv'
        env['GATE_ONLY_JOBS'] = jobs
        command = ['taskset', '-c', '0-15', 'tests/gate.sh', tier,
            '--candidate-binary', str(binary), '--server-cores', '0-7', '--server-smt', '',
            '--load-cores', '8-15', '--load-smt', '', '--ports', '20100-20189']
        before = set((ROOT / 'build').glob('gate-run.*'))
        log = folder / (label + '.log')
        print('START', label, flush=True)
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        created = set((ROOT / 'build').glob('gate-run.*')) - before
        assert len(created) == 1, created
        run = created.pop()
        receipt = blockfix2_receipts.collect(label, run, output)
        receipt.update(command=command, env={k: v for k, v in env.items() if k.startswith('GATE_') or k == 'REDIS74_ROOT'},
            exit_code=result.returncode, binary_sha256=redis_tcl.sha(binary))
        (output / (label + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        print('DONE', label, result.returncode,
            sum(j['passed'] for j in receipt['jobs']), sum(j['failed'] for j in receipt['jobs']), flush=True)
        # All gate workers have stopped. Retain receipts; remove only generated
        # Tcl checkouts and server state, never any binary or production source.
        for path in sorted(run.rglob('*'), reverse=True):
            if path.is_dir() and (path.name in ('checkout', 'data', 'appendonlydir') or
                                  path.name.startswith('gate-data-')):
                shutil.rmtree(path)


if __name__ == '__main__':
    main()
