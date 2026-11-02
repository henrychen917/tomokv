#!/usr/bin/env python3
"""Repeat the unchanged FIFO gate job with explicit client CPU controls."""
import json
import os
import subprocess
import time

from wave14 import ROOT, DOC, save, sha


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    deadline = time.monotonic() + 1800
    predecessor = DOC / 'jobs/flip-refusal-contract-final.json'
    while not predecessor.exists():
        assert time.monotonic() < deadline, 'FLIP job did not release its allocation'
        time.sleep(1)
    plans = [
        ('fifo-lane-four-client-cpus',
         '/home/user/Projects/bins/execfifo3-post-6f9af8cd', '0-3'),
        ('fifo-final-eight-client-cpus',
         str(ROOT / 'build/wave14/post-r7/tomokv'), '0-7'),
    ]
    results = []
    for tag, binary, load in plans:
        command = ['python3', 'tools/wave14.py', 'jobs', '--tag', tag,
            '--engine', 'uring', '--jobs', 'txnorder_fifo_live', '--binary', binary,
            '--server-cores', '16-23', '--load-cores', load, '--ports', '20093-20095']
        print('START', tag, flush=True)
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, LC_ALL='C'))
        results.append(dict(tag=tag, command=command, binary_sha256=sha(binary),
                            exit_code=result.returncode))
        save(DOC / 'fifo-allocation-control-results.json', results)
        print('DONE', tag, result.returncode, flush=True)
    raise SystemExit(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    main()
