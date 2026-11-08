#!/usr/bin/env python3
"""Run selected correctness jobs on the lane's CPUs/ports; never iteration/perf."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from flushfix2_verify import BROAD

ROOT = Path(__file__).resolve().parents[1]
EXTRA = '''snapfix_shutdown snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables
scriptfix2 exec1s netcmd_units notifycompat racefix_counters racefix_climon'''.split()
# These families use the ordinary gate boot, rather than owning an internal
# engine product. Their explicit atomic/mode loops remain intact.
ENGINE = '''dump_restore debug-0 debug-1 aoforder
climonfix txnorder-fused-0 txnorder-fused-1
txnorder-split-0 txnorder-split-1 txn_group_fused txn_group_split script_bounds
scriptfix flip flipctl flip_saturated atomic_batteries atomic_floor
atomfix5_watch atomfix5_accounting fused-0 fused-1 release_batteries
feature-split-0 feature-split-1 feature-armed-0 feature-armed-1'''.split()
ENGINE += [f'multidb-{m}-{r}-{a}' for m in ('1s', '2s') for r in (0, 1) for a in (0, 1)]
# txn_proof_boot's companion fused run. The explicitly split-only FLIP rows
# remain split; fused automatic FLIP is deliberately unsupported.
FUSED = '''snapshot-uring snapshot-epoll aof-uring aof-epoll aof_frame
dump_restore debug-0 debug-1 script_bounds atomic_batteries'''.split()


def phases():
    result = {
        'idle': ('quick', ['flushfix3'], {}),
        'directed': ('quick', 'flushfix2 flushfix2_units flushfix3 flushfix3_units'.split(), {}),
        'broad': ('quick', BROAD + EXTRA, {}),
        'engine-epoll': ('quick', ENGINE, dict(GATE_NET_IO='epoll', GATE_PROOF_NET_IO='epoll')),
        'fused-uring': ('quick', FUSED, dict(GATE_TXN_FUSED='1', GATE_PROOF_NET_IO='uring')),
        'fused-epoll': ('quick', [j for j in FUSED if not j.startswith(('snapshot-', 'aof-'))],
                        dict(GATE_TXN_FUSED='1', GATE_NET_IO='epoll', GATE_PROOF_NET_IO='epoll')),
        'aof-frame-uring': ('quick', ['aof_frame'], dict(GATE_PROOF_NET_IO='uring')),
    }
    for engine in ('uring', 'epoll'):
        result['script-a1-'+engine] = ('quick', ['scriptfix'],
            dict(GATE_TXN_ATOMIC='1', GATE_NET_IO=engine, GATE_PROOF_NET_IO=engine))
        for mode in ('1s', '2s'):
            result['bounds-a0-'+mode+'-'+engine] = ('quick', ['script_bounds'],
                dict(GATE_TXN_ATOMIC='0', GATE_TXN_FUSED=str(int(mode == '1s')),
                     GATE_NET_IO=engine, GATE_PROOF_NET_IO=engine))
        result['differ-'+engine] = ('full', ['differ-split', 'differ-armed'],
                                    dict(GATE_DIFFER_NET_IO=engine))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT/'build/tomokv')
    parser.add_argument('--label', default='final')
    parser.add_argument('--phases', default=','.join(phases()))
    parser.add_argument('--omit-jobs', default='',
                        help='comma-separated jobs already covered or reserved for the owner')
    args = parser.parse_args()
    assert os.sched_getaffinity(0) <= set(range(16))
    binary = args.binary.resolve()
    assert binary.is_relative_to(ROOT/'build')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    out = ROOT/'build/flushfix3/verification'/args.label
    out.mkdir(parents=True, exist_ok=True)
    record = out/'runs.json'
    rows = json.loads(record.read_text()) if record.exists() else []
    failed = False
    for phase in args.phases.split(','):
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
        tier, jobs, overrides = phases()[phase]
        omitted = [job for job in jobs if job in args.omit_jobs.split(',')]
        jobs = [job for job in jobs if job not in omitted]
        assert jobs, f'empty selection for {phase}'
        env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
                   GATE_PROOF_NO_RATES='1', GATE_ONLY_JOBS=' '.join(jobs),
                   GATE_LEDGER=str(out/phase), GATE_LOAD_CORES='8-15',
                   GATE_DIFFER_ORACLE_CORES='0-7', **overrides)
        cmd = ['taskset', '-c', '0-15', 'tests/gate.sh', tier,
               '--server-cores', '0-7', '--load-cores', '8-15', '--load-smt', '',
               '--ports', '20100-20102', '--candidate-binary', str(binary)]
        log = out/(phase+'.log')
        assert not log.exists(), f'preserve prior evidence: choose a new label for {phase}'
        print('start', phase, flush=True)
        with log.open('w') as stream:
            status = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT).returncode
        rows.append(dict(phase=phase, status=status, command=cmd, binary_sha256=digest,
            omitted_selection=omitted,
            environment={k:v for k,v in env.items() if k.startswith(('GATE_', 'REDIS74_', 'LC_ALL'))}))
        record.write_text(json.dumps(rows, indent=2)+'\n')
        print('done', phase, status, flush=True)
        failed |= status != 0
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
