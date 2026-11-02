#!/usr/bin/env python3
"""Repeat debug jobs after applying the gate's existing no-rate policy to XACCT."""
import os
import subprocess
import time

from wave14 import ROOT, DOC, save


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    deadline = time.monotonic() + 1800
    while not (DOC / 'jobs/fifo-final-eight-client-cpus.json').exists():
        assert time.monotonic() < deadline
        time.sleep(1)
    results = []
    for engine, fused in [('uring', False), ('epoll', False), ('uring', True)]:
        tag = 'xacct-policy-final-' + engine + ('-1s' if fused else '-2s')
        command = ['python3', 'tools/wave14.py', 'jobs', '--tag', tag,
            '--engine', engine, '--jobs', 'debug-0 debug-1',
            '--binary', str(ROOT / 'build/wave14/post-r7/tomokv'),
            '--server-cores', '16-23', '--load-cores', '0-7', '--ports', '20093-20095']
        if fused:
            command.append('--fused')
        print('START', tag, flush=True)
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, LC_ALL='C'))
        results.append(dict(tag=tag, command=command, exit_code=result.returncode))
        save(DOC / 'xacct-companion-results.json', results)
        print('DONE', tag, result.returncode, flush=True)
    raise SystemExit(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    main()
