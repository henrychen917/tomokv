#!/usr/bin/env python3
"""Bind the final command-family/differential gate jobs to the delivered POST."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cmdfix2'

COMMON = ('feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 '
          'acl_metadata acl_subcommands acl_recheck aclfix auth serverfix_hll '
          'serverfix_acllog streamfix blockfix_mkstream blockfix4 release_batteries '
          'atomic_batteries differ-split differ-armed')
EXTRA = {
    'uring': ('fused-0 fused-1 debug-0 debug-1 txn_group_fused txn_group_split '
              'txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 '
              'txnorder_fifo txnorder_fifo_live txnorder_chain txnorder_index '
              'txnorder_wound txnorder2 txnorder_wake execfair exec1s atomic_units '
              'atomfix5_watch atomfix5_accounting aclkeys_wake datafix1_geo '
              'multifix-1s-uring multifix-1s-epoll multifix-2s-uring multifix-2s-epoll '
              'clientcompat-multi-controls clientcompat-multi-tracking'),
    'epoll': 'authfix atomic_floor perfio_stream',
}


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    parser = argparse.ArgumentParser(); parser.add_argument('engine', choices=tuple(EXTRA))
    args = parser.parse_args(); label = 'post-v2-main-' + args.engine
    binary = OUT/'POST'; digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    command = ['taskset', '-c', '100-111', 'tests/gate.sh', 'full',
               '--server-cores', '100-107', '--load-cores', '108-111', '--load-smt', '',
               '--ports', '21300-21309' if args.engine == 'uring' else '21310-21319',
               '--candidate-binary', str(binary)]
    changes = dict(LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
                   GATE_ONLY_JOBS=COMMON+' '+EXTRA[args.engine], GATE_PROOF_NO_RATES='1',
                   GATE_NET_IO=args.engine, GATE_DIFFER_NET_IO=args.engine,
                   CXX='g++ -gz=zlib', CC='cc -gz=zlib', GATE_LEDGER=str(OUT/label))
    record = dict(command=command, environment=changes, candidate_sha256=digest)
    receipt = OUT/(label+'.json'); receipt.write_text(json.dumps(record, indent=2)+'\n')
    with (OUT/(label+'.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **changes),
                                stdout=log, stderr=subprocess.STDOUT)
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
    record['exit_code'] = result.returncode
    receipt.write_text(json.dumps(record, indent=2)+'\n')
    raise SystemExit(result.returncode)
