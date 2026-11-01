#!/usr/bin/env python3
"""Sequential complete gate jobs on the lane's one 6:2 correctness slot."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from select_jobs import job_names

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'
MATRIX = json.loads((DOC / 'correctness-matrix.json').read_text())
RESERVED = {'flip_saturated', 'efficiency', 'tailgen_build'}
DEFERRED = {'abba_selftest', 'redis_tcl', 'compat2', 'flushfix3'}


def run(name, jobs, *options, env=None):
    assert not set(jobs) & RESERVED
    command = ['python3', str(DOC / 'run_jobs.py'), name, *jobs,
               '--binary', 'build/wave13/tomokv-POST', '--single-slot', *options]
    result = subprocess.run(command, cwd=ROOT, env=env)
    print('CAMPAIGN', name, 'exit', result.returncode, flush=True)
    return result.returncode


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['primary', 'supplements', 'differ', 'tcl', 'idle'])
    a = parser.parse_args()
    exits = []
    if a.phase == 'primary':
        jobs = [j for j in job_names() if j not in RESERVED | DEFERRED and not j.startswith('differ-')]
        exits.append(run('landing-primary', jobs))
    elif a.phase == 'supplements':
        exits.append(run('landing-epoll', sorted(set(MATRIX['each_engine'] + MATRIX['each_mode_engine'])), '--engine', 'epoll'))
        for engine in ('uring', 'epoll'):
            exits.append(run('landing-fused-' + engine,
                             sorted(set(MATRIX['each_mode'] + MATRIX['each_mode_engine'])),
                             '--engine', engine, '--fused'))
            for fused in (False, True):
                exits.append(run('landing-script0-' + engine + '-' + str(int(fused)), ['script_bounds'],
                                 '--engine', engine, *(['--fused'] if fused else []),
                                 env=dict(os.environ, GATE_TXN_ATOMIC='0')))
    elif a.phase == 'differ':
        for engine in ('uring', 'epoll'):
            exits.append(run('landing-differ-' + engine,
                             ['differ-split-0', 'differ-split-1', 'differ-armed-0', 'differ-armed-1', 'differ-equivalence'],
                             '--engine', engine))
    elif a.phase == 'tcl':
        exits.append(run('landing-tcl-quiet', ['redis_tcl', 'compat2']))
    else:
        exits.append(run('landing-flush-idle', ['flushfix3']))
    return int(any(exits))


if __name__ == '__main__':
    raise SystemExit(main())
