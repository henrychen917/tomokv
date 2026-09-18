#!/usr/bin/env python3
"""Serverless split no-op witness, including real-path and transient-allocation controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(binary, *args):
    return subprocess.run([str(binary), *map(str, args)], cwd=ROOT, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)


def witness(result):
    assert result.returncode == 0, result.stdout
    rows = [line for line in result.stdout.splitlines() if line.startswith('WITNESS ')]
    assert len(rows) == 1, result.stdout
    return dict((key, int(value)) for key, value in
                (entry.split('=') for entry in rows[0].split()[1:]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'use the compile CPUs'
    # Split role entries are direct baseline calls, including both FLIP owner paths.
    # These checks complement the 169-body machine-code audit, not replace it.
    for file in ('src/main.cc', 'src/core/rl2s.cc'):
        text = (ROOT / file).read_text()
        assert 'r7_' not in text and 'run_owner[' not in text, file
    import r7shadow_sync as sync
    assert 'reorder' not in sync.function((ROOT / 'src/core/io_loop.h').read_text(), 'run').replace(
        '// This is a split-role entry, including after FLIP. It has no R7 arm.', '')
    split_local = sync.function((ROOT / 'src/core/reorder.cc').read_text(),
                                'IoLoop::run_split_read_local', False)
    assert 'cfg().reorder' not in split_local and 'return run_split_read_local_baseline();' in split_local
    positive = run(args.binary, 'positive')
    assert positive.returncode == 0 and 'positive control' in positive.stdout, positive.stdout
    rows = []
    for overlap in (0, 1):
        for read_local in (0, 1):
            baseline = witness(run(args.binary, 0, overlap, read_local))
            assert baseline['paths'] == baseline['reorder_allocations'] == 0
            for requested in (0, 1, -1):
                observed = witness(run(args.binary, requested, overlap, read_local))
                assert observed == baseline, (overlap, read_local, requested, baseline, observed)
                rows.append(dict(overlap=overlap, read_local=read_local, requested=requested, **observed))
            print(f'PASS split overlap={overlap} read-local={read_local}: raw 0/1/-1, zero paths/state, identical allocations')
            for leak in ('parse', 'policy', 'sample'):
                negative = run(args.binary, 1, overlap, read_local, leak)
                assert negative.returncode == 1 and 'reorder-specific path executed' in negative.stdout, negative.stdout
            # This mutant frees its sidecar before inspection. The whole allocation
            # trace, not the final pointer/counter, must detect the extra allocation.
            allocation = witness(run(args.binary, 1, overlap, read_local, 'allocation'))
            assert allocation != baseline and allocation['heap_calls'] == baseline['heap_calls'] + 1, (
                baseline, allocation)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(dict(binary=str(args.binary),
        sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(), rows=rows, positive=True,
        rejected=['parse', 'policy', 'sample', 'transient allocation']), indent=2) + '\n')
    print('PASS split witness: 12 cells and 16 forbidden-path/allocation negative controls')


if __name__ == '__main__':
    main()
