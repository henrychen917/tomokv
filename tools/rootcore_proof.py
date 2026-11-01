#!/usr/bin/env python3
"""Selected correctness jobs only, on rootcore's CPUs/ports; no rate workloads."""
import datetime
import json
import hashlib
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16, 32))
out = root / 'build/rootcore/proof'
out.mkdir(parents=True, exist_ok=True)
binary = root / 'build/tomokv'
frozen = root / 'build/rootcore/POST'
assert frozen.is_file()
def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
frozen_sha = digest(frozen)
common = """feature-split-0 feature-split-1 feature-armed-0 feature-armed-1
release_batteries atomic_batteries debug-0 debug-1
flip fliplisten lb-stationary-1s lb-stationary-2s
blockfix_structure blockfix_mkstream
multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1
multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1
fused-0 fused-1 txn_group_fused txn_group_split
txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1
script_bounds scriptfix lualibs aof_frame aoforder atomic_floor
""".split()
once = """flip_unit lbplanner_units atomic_units core_units
blockfix_registry blockfix2 txnorder_index txnorder_wound txnorder2 txnorder_wake
execfair exec1s maxmemrace netio-1s netio-2s
persistfix_units persistfix2_lastsave persistfix2_shutdown persistfix2_commands persistfix2_errors
aof-uring aof-epoll snapshot-uring snapshot-epoll
snapfix_shutdown snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables
scriptfix2 notify notify_order notify_aof serverfix_waitaof
""".split()
differ = 'differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence'.split()
phases = [
    ('directed', 'uring', 0, ['rootcore-' + s for s in
        ('inbox','eval','segments','notify','functions','waitaof','misconf')]),
    ('main-uring', 'uring', 0, common + once + differ),
    ('main-epoll', 'epoll', 0, common + differ),
    ('fused-uring', 'uring', 1, 'release_batteries atomic_batteries debug-0 debug-1 script_bounds'.split()),
    ('fused-epoll', 'epoll', 1, 'release_batteries atomic_batteries debug-0 debug-1 script_bounds'.split()),
    ('notify-order-pre', 'uring', 0, ['notify_order']),
    ('notify-order-post', 'uring', 0, ['notify_order']),
    # The original AOF scanner only knew GCMT control records. After teaching
    # it the FUNCTION record, rerun both full AOF jobs on each arm and mode.
    ('aof-pre-split', 'uring', 0, ['aof-uring', 'aof-epoll']),
    ('aof-pre-fused', 'uring', 1, ['aof-uring', 'aof-epoll']),
    ('aof-final-split', 'uring', 0, ['aof-uring', 'aof-epoll']),
    ('aof-final-fused', 'uring', 1, ['aof-uring', 'aof-epoll']),
]
for name, engine, fused, jobs in phases:
    receipt = out / (name + '.json')
    if receipt.exists():
        print('already completed', name, flush=True)
        continue
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        CXX='g++ -gz=zlib', CC='cc -gz=zlib',
        GATE_ONLY_JOBS=' '.join(jobs), GATE_PROOF_NO_RATES='1',
        GATE_PROOF_NET_IO=engine, GATE_DIFFER_NET_IO=engine,
        GATE_TXN_FUSED=str(fused))
    use_pre = name.startswith('aof-pre-') or name == 'notify-order-pre'
    candidate = root / 'build/rootcore/PRE' if use_pre else binary
    candidate_sha = digest(candidate)
    cmd = ['tests/gate.sh', 'full', '--server-cores', '16-23', '--load-cores', '24-31',
           '--ports', '20100-20199', '--candidate-binary', str(candidate)]
    assert digest(binary) == frozen_sha, 'candidate changed after freezing POST'
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print('START', name, started, flush=True)
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    record = dict(name=name, command=cmd, jobs=jobs, engine=engine, fused=fused,
                  sha256=candidate_sha, rootcore_test_sha256=digest(root / 'tests/rootcore.py'),
                  aof_test_sha256=digest(root / 'tests/aof.py'),
                  started=started, ended=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  exit_code=result.returncode)
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    print('DONE', name, 'exit', result.returncode, flush=True)
