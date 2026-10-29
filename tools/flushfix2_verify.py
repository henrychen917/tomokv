#!/usr/bin/env python3
"""Owned correctness jobs and standard differential seeds; never iteration/perf."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BROAD = '''snapshot-epoll snapshot-uring persistfix2_lastsave persistfix2_shutdown
persistfix2_commands persistfix2_errors persistfix_units dump_restore debug-0 debug-1
aof-epoll aof-uring aof_frame aoforder notify_aof serverfix_waitaof iofix-signal
climonfix txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1
txnorder2 txnorder_wake txnorder_index txnorder_wound execfair txn_group_fused
txn_group_split script_bounds scriptfix lualibs flip flipctl flip_saturated
fliplisten flip_unit flipfix_units core_units atomic_units atomic_batteries atomic_floor
atomfix5_watch atomfix5_accounting moverfix fused-0 fused-1 storage_units
release_batteries feature-split-0 feature-split-1 feature-armed-0 feature-armed-1'''.split()
BROAD += [f'multidb-{m}-{r}-{a}' for m in ('1s', '2s') for r in (0, 1) for a in (0, 1)]
BROAD += [f'multifix-{m}-{e}' for m in ('1s', '2s') for e in ('uring', 'epoll')]
BROAD += [f'at412-{s}' for s in ('T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16 owner'.split())]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--phases', default='directed,broad,differ-uring,differ-epoll')
    p.add_argument('--server-cores', default='0-7')
    p.add_argument('--load-cores', default='8-15')
    p.add_argument('--ports', default='20100-20102')
    p.add_argument('--differ-ports', nargs=2, default=['20110', '20111'])
    a = p.parse_args()
    binary = a.binary.resolve()
    assert binary.is_relative_to(ROOT/'build')
    out = ROOT/'build/flushfix2/verification'/a.label
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
               GATE_LOAD_CORES=a.load_cores, GATE_DIFFER_ORACLE_CORES=a.server_cores,
               GATE_PROOF_NO_RATES='1')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    rows = []
    for phase in a.phases.split(','):
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
        run_env = env.copy()
        if phase in ('directed', 'broad'):
            run_env['GATE_ONLY_JOBS'] = 'flushfix2 flushfix2_units' if phase == 'directed' else ' '.join(BROAD)
            run_env['GATE_LEDGER'] = str(out/phase)
            cmd = ['taskset', '-c', '0-15', 'tests/gate.sh', 'quick',
                   '--server-cores', a.server_cores, '--load-cores', a.load_cores, '--load-smt', '',
                   '--ports', a.ports, '--candidate-binary', str(binary)]
        else:
            assert phase in ('differ-uring', 'differ-epoll')
            run_env.update(GATE_DIFFER_NET_IO=phase.removeprefix('differ-'),
                           GATE_DIFFER_OUT=str(out/phase), GATE_DIFFER_GEOMETRY='split')
            cmd = ['taskset', '-c', a.load_cores, 'tests/differ_gate.sh', str(binary),
                   *a.differ_ports, a.server_cores, '6:2']
        with (out/(phase+'.log')).open('w') as log:
            status = subprocess.run(cmd, cwd=ROOT, env=run_env, stdout=log, stderr=subprocess.STDOUT).returncode
        rows.append(dict(phase=phase, status=status, command=cmd, binary_sha256=digest,
                         environment={k:v for k,v in run_env.items() if k.startswith(('GATE_', 'REDIS74_', 'LC_ALL'))}))
        (out/'runs.json').write_text(json.dumps(rows, indent=2)+'\n')
        print(phase, status, flush=True)
    return int(any(r['status'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
