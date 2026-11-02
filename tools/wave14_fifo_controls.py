#!/usr/bin/env python3
"""Repeat the unchanged FIFO gate job with explicit client CPU controls."""
import argparse
import json
import os
import subprocess
import time

from wave14 import ROOT, DOC, save, sha


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane-four-after-final', action='store_true')
    parser.add_argument('--isolated-after-uring', action='store_true')
    args = parser.parse_args()
    deadline = time.monotonic() + 12 * 3600
    predecessor = DOC / ('jobs/fifo-final-eight-client-cpus.json'
        if args.lane_four_after_final else 'jobs/flip-refusal-contract-final.json')
    while not predecessor.exists():
        assert time.monotonic() < deadline, 'predecessor did not release its allocation'
        time.sleep(1)
    if args.isolated_after_uring:
        results_path = DOC / 'final-uring-results.json'
        while not results_path.exists() or len(json.loads(results_path.read_text())) != 7:
            assert time.monotonic() < deadline, 'uring followthrough did not release CPUs 0-15'
            time.sleep(1)
        while not (DOC / 'jobs/fifo-final-eight-client-cpus.json').exists():
            assert time.monotonic() < deadline, 'overlapping FIFO attempt did not finalize'
            time.sleep(1)
    plans = [
        ('fifo-lane-four-client-cpus-valid',
         '/home/user/Projects/bins/execfifo3-post-6f9af8cd', '0-3', '16-27'),
        ('fifo-final-eight-client-cpus',
         str(ROOT / 'build/wave14/post-r7/tomokv'), '0-7', '16-23'),
    ]
    if args.lane_four_after_final:
        plans = plans[:1]
    if args.isolated_after_uring:
        plans = [
            ('fifo-lane-four-client-cpus-isolated',
             '/home/user/Projects/bins/execfifo3-post-6f9af8cd', '12-15', '0-11'),
            ('fifo-final-eight-client-cpus-isolated',
             str(ROOT / 'build/wave14/post-r7/tomokv'), '8-15', '0-7'),
        ]
    results = []
    for tag, binary, load, server in plans:
        command = ['python3', 'tools/wave14.py', 'jobs', '--tag', tag,
            '--engine', 'uring', '--jobs', 'txnorder_fifo_live', '--binary', binary,
            '--server-cores', server, '--load-cores', load, '--ports', '20093-20095']
        print('START', tag, flush=True)
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, LC_ALL='C'))
        results.append(dict(tag=tag, command=command, binary_sha256=sha(binary),
                            exit_code=result.returncode))
        suffix = ('-isolated' if args.isolated_after_uring else
                  '-valid' if args.lane_four_after_final else '')
        save(DOC / ('fifo-allocation-control-results' + suffix + '.json'), results)
        print('DONE', tag, result.returncode, flush=True)
    raise SystemExit(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    main()
