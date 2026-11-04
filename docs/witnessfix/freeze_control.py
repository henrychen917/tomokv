"""Compare old/new FLIP batteries on an isolated witnessed five-second pause."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server

os.environ['LC_ALL'] = 'C'
binary = ROOT / 'build/witnessfix/mutants/flip-freeze/tomokv'
base = ROOT / 'build/witnessfix/freeze-control-v2'
base.mkdir(parents=True, exist_ok=True)
old = base / 'old-flip-under-load.py'
old.write_bytes(subprocess.check_output(['git', 'show', '7d2f8a205:tests/flip_under_load.py']))
rows = []
for engine in ('uring', 'epoll'):
    for arm, test in (('old', old), ('repaired', ROOT / 'tests/flip_under_load.py')):
        output = base / engine / arm
        output.mkdir(parents=True, exist_ok=True)
        with server(binary, '80-87', 20557, output / 'server',
                    ['--shards', '16', '--ratio', '6:2', '--net-io', engine,
                     '--flip-auto', '0']) as (_admin, process):
            cmd = ['taskset', '-c', '88-95', 'python3', str(test),
                   '127.0.0.1', '20557', '20']
            result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=80,
                                    env=dict(os.environ, PYTHONPATH=str(ROOT/'tests')))
            (output / 'battery.log').write_text(result.stdout)
        logs = '\n'.join(p.read_text(errors='replace') for p in (output / 'server').rglob('*.log'))
        hits = logs.count('WITNESSFIX freeze-hit=1')
        row = dict(engine=engine, arm=arm, command=cmd, exit=result.returncode,
                   freeze_hits=hits, stdout=result.stdout,
                   timeout_detected='TIMEOUT(client 4s)' in result.stdout,
                   sha256=hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest())
        rows.append(row)
        (ROOT / 'docs/witnessfix/freeze-control.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(row, flush=True)
        assert hits == 1, row
        assert (result.returncode == 0) == (arm == 'old'), row
        if arm == 'repaired': assert row['timeout_detected'], row
old.unlink()
