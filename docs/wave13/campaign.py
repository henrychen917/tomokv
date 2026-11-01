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
# The original nonconforming attempt is retained, but must never be repeated
# by this C-only campaign. Its assertion is unchanged and remains NOT RUN.
CONSTRAINT_EXCLUSIONS = {'datafix1_locale'}
BUILD_ONLY = {'production_units', 'core_tsan_build', 'waits_tsan_build'}
DEFERRED = {'abba_selftest', 'redis_tcl', 'compat2', 'flushfix3'}


def run(name, jobs, *options, env=None):
    assert not set(jobs) & (RESERVED | CONSTRAINT_EXCLUSIONS)
    command = ['python3', str(DOC / 'run_jobs.py'), name, *jobs,
               '--binary', 'build/wave13/tomokv-POST', '--single-slot', *options]
    result = subprocess.run(command, cwd=ROOT, env=env)
    print('CAMPAIGN', name, 'exit', result.returncode, flush=True)
    return result.returncode


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['primary', 'repairs', 'supplements', 'differ', 'tcl', 'idle'])
    a = parser.parse_args()
    exits = []
    if a.phase == 'primary':
        jobs = [j for j in job_names() if j not in RESERVED | CONSTRAINT_EXCLUSIONS | DEFERRED | BUILD_ONLY and not j.startswith('differ-')]
        exits.append(run('landing-primary', jobs))
    elif a.phase == 'repairs':
        helper = (ROOT / 'tests/datafix1_common.py').read_text()
        assert 'boot_locale' in helper, 'Apply the reviewed C-locale helper patch first'
        assert 'failure_window_unarmed' in (ROOT / 'tests/persistfmt.py').read_text()
        exits.append(run('landing-persistfmt-window', ['persistfmt', 'persistfmt_aof_error']))
        exits.append(run('landing-blockfix-companions', ['blockfix2', 'blockfix_registry']))
        exits.append(run('landing-datafix1-C', [
            'datafix1_randscan', 'datafix1_hexpire', 'datafix1_bitfield',
            'datafix1_lists', 'datafix1_spop', 'datafix1_geo']))
    elif a.phase == 'supplements':
        exits.append(run('landing-epoll', sorted(set(MATRIX['each_engine'] + MATRIX['each_mode_engine'])), '--engine', 'epoll'))
        for engine in ('uring', 'epoll'):
            exits.append(run('landing-footprints-' + engine,
                             MATRIX['release_footprints_each_engine'],
                             '--engine', engine, '--release-footprints'))
            # These four jobs name their engine explicitly. Their missing fused
            # legs need one invocation each, independent of GATE_NET_IO.
            named_engine_jobs = MATRIX['each_mode'] if engine == 'uring' else []
            exits.append(run('landing-fused-' + engine,
                             sorted(set(named_engine_jobs + MATRIX['each_mode_engine'])),
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
        # Scheduler selftests claim their slot's otherwise idle server CPUs.
        # Run them alone, then the controller hold witness, before Tcl starts.
        # Preserve the earlier overlapping attempts and keep every bound intact.
        exits.append(run('landing-abba-selftest-isolated', ['abba_selftest'],
                         '--root', str(ROOT / 'build/wave13/abba-final-copy'), '--port', '20050'))
        if exits[-1]:
            return 1
        exits.append(run('landing-flipctl-epoll-isolated', ['flipctl'], '--engine', 'epoll'))
        if exits[-1]:
            return 1
        exits.append(run('landing-tcl-quiet', ['redis_tcl', 'compat2']))
    else:
        exits.append(run('landing-flush-idle', ['flushfix3']))
    return int(any(exits))


if __name__ == '__main__':
    raise SystemExit(main())
