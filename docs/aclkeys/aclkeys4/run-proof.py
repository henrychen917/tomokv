#!/usr/bin/env python3
"""Owned correctness children on the owner's authorized CPUs; no gate or measurement."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn
from psfix import boot

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--rounds', type=int, default=6)
p.add_argument('--negative', action='store_true')
p.add_argument('--blocking', action='store_true')
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
assert a.rounds > 0
rows = []
for mode in ('split', 'armed-fused'):
    for atomic in (0, 1):
        for n in range(a.rounds):
            label = f'{mode}-a{atomic}-r{n+1}'
            d = a.output / label; d.mkdir()
            shape = ['--ratio', '6:2'] if mode == 'split' else ['--thread-mode', 'fused', '--read-local', '1']
            argv = [str(a.binary.resolve()), '--port', '18340', '--bind', '127.0.0.1',
                    '--shards', '16', '--databases', '16', '--atomic', str(atomic),
                    '--save', '', '--dir', str(d.resolve()), '--enable-debug-command', 'yes', *shape]
            if a.blocking:
                argv += ['--notify-keyspace-events', 'KEAmn']
            with boot(argv, '112-119', 18340, d / 'server.log'):
                if a.blocking:
                    admin = Conn('127.0.0.1', 18340, timeout=2)
                    try: assert admin.cmd('SWAPDB', 0, 1) == b'OK'
                    finally: admin.close()
                start = time.monotonic()
                test = 'blocking.py' if a.blocking else 'aclkeys_wake_state.py'
                result = subprocess.run([sys.executable, str(ROOT/'tests'/test), '127.0.0.1', '18340'],
                                        capture_output=True, text=True, timeout=90)
                output = result.stdout + result.stderr
                (d / 'test.log').write_text(output)
                expected = (result.returncode != 0 and 'TimeoutError: timed out' in output
                            and 'assert worker.read()' in output) if a.negative else result.returncode == 0
                row = dict(label=label, expected=expected, returncode=result.returncode,
                           seconds=time.monotonic()-start, negative=a.negative, test=test)
                rows.append(row)
                print(json.dumps(row), flush=True)
                (a.output/'results.json').write_text(json.dumps(dict(
                    binary=str(a.binary), sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),
                    server_cpus='112-119', client_cpus='120-127', rows=rows), indent=2)+'\n')
                assert expected, output
