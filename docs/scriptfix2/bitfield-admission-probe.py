#!/usr/bin/env python3
"""Bounded diagnostic for the unrelated feature-split-1 growth-admission failure."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from scriptfix2 import Wire, server
ROOT = Path(__file__).resolve().parents[2]
out = ROOT / 'docs/scriptfix2/bitfield-admission-probe'
out.mkdir(exist_ok=True)
rows = []
for arm, binary in [('pre', ROOT / 'build/scriptfix2/pre/tomokv'),
                    ('post', ROOT / 'build/scriptfix2/tomokv-post-verified')]:
    args = argparse.Namespace(binary=binary, output=out / arm, port=20540,
                              cores='96-103', oracle_cores='104-111', mode='2s',
                              net_io='uring', databases=1, atomic=1, ratio='6:2')
    row = {'arm': arm, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
           'iterations': 0, 'failure': None}
    with server(args) as (port, argv):
        row['argv'] = argv
        c = Wire(port)
        try:
            assert c.cmd('CONFIG','SET','maxmemory-policy','noeviction') == b'+OK\r\n'
            for iteration in range(5000):
                assert c.cmd('CONFIG','SET','maxmemory','0') == b'+OK\r\n'
                assert c.cmd('FLUSHALL') == b'+OK\r\n'
                assert c.cmd('CONFIG','SET','maxmemory','65536') == b'+OK\r\n'
                key = f'bf:oom:{iteration % 64}'
                command = ['BITFIELD',key,'SET','u8','#100000','1']
                reply = c.cmd(*command)
                row['iterations'] += 1
                if reply != b"-OOM command not allowed when used memory > 'maxmemory'.\r\n":
                    row['failure'] = {'iteration': iteration, 'command': command,
                                      'reply': reply.decode('latin1'),
                                      'maxmemory': c.cmd('CONFIG','GET','maxmemory').decode('latin1'),
                                      'length': c.cmd('STRLEN',key).decode('latin1')}
                    break
        finally:
            c.cmd('CONFIG','SET','maxmemory','0')
            c.close()
    rows.append(row)
    (out / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(row), flush=True)
