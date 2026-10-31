#!/usr/bin/env python3
"""Run complete selected gate jobs on the lane's CPUs/ports; never run perf.

The first phase includes all persistence/script families and the standard
differential inventory. The second covers ordinary epoll boots. The last two
exercise jobs whose optional fused boot is selected by GATE_TXN_FUSED.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/persistfmt'
BASE = ('persistfmt persistfmt_aof_error redis_tcl release_batteries compat3 dump_restore '
        'persistfix2_lastsave persistfix2_shutdown persistfix2_commands persistfix2_errors '
        'snapshot-epoll snapshot-uring aof-epoll aof-uring snapfix_shutdown '
        'snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables scriptfix scriptfix2 '
        'lualibs script_bounds streamfix aof_frame aoforder notify_aof')
ORDINARY = ('feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 '
            'fused-0 fused-1 debug-0 debug-1 ' +
            ' '.join(f'multidb-{m}-{r}-{a}' for m in ('1s', '2s')
                     for r in (0, 1) for a in (0, 1)))
FUSED = 'debug-0 debug-1 dump_restore release_batteries'
PHASES = [
    ('matrix-uring', 'uring', '0', BASE + ' ' + ORDINARY + ' differ-split differ-armed'),
    ('matrix-epoll', 'epoll', '0', ORDINARY + ' differ-split differ-armed'),
    ('fused-uring', 'uring', '1', FUSED + ' snapshot-epoll snapshot-uring aof-epoll aof-uring'),
    ('fused-epoll', 'epoll', '1', FUSED),
]


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
    binary = ROOT / 'build/persistfmt/POST/tomokv'
    digest = sha(binary)
    records = []
    for name, engine, fused, jobs in PHASES:
        env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
                   GATE_ONLY_JOBS=jobs, GATE_NET_IO=engine, GATE_DIFFER_NET_IO=engine,
                   GATE_TXN_FUSED=fused, GATE_PROOF_NO_RATES='1', GATE_PERSISTFMT_REPEATS='240')
        argv = ['bash', 'tests/gate.sh', 'full', '--server-cores', '96-103',
                '--load-cores', '104-111', '--ports', '20500-20599',
                '--candidate-binary', str(binary)]
        log = DOC / ('validated-' + name + '.log')
        print('START', name, flush=True)
        with log.open('w') as output:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        assert sha(binary) == digest, 'candidate bytes changed during validation'
        match = re.search(r'^  artifacts: (.+)$', log.read_text(), re.M)
        run = Path(match[1]) if match else None
        ledger = (run / 'ledger.partial').read_text() if run and (run / 'ledger.partial').exists() else ''
        record = dict(phase=name, argv=argv, env={k: env[k] for k in
                      ('LC_ALL', 'REDIS74_ROOT', 'GATE_ONLY_JOBS', 'GATE_NET_IO',
                       'GATE_DIFFER_NET_IO', 'GATE_TXN_FUSED', 'GATE_PROOF_NO_RATES',
                       'GATE_PERSISTFMT_REPEATS')}, binary_sha256=digest,
                      returncode=result.returncode, run_dir=str(run), ledger=ledger)
        records.append(record)
        (DOC / 'validation.json').write_text(json.dumps(records, indent=2) + '\n')
        print('DONE', name, result.returncode, flush=True)
    # Preserve all legs even if a preceding job/phase failed.
    raise SystemExit(int(any(r['returncode'] for r in records)))


if __name__ == '__main__':
    main()
