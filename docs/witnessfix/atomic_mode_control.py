"""Restore-removal control for TM4.1, using the real live flag assertion."""
from pathlib import Path
import json
import os
import subprocess
import sys
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server
os.environ['LC_ALL'] = 'C'
output = ROOT / 'build/witnessfix/atomic-mode-control-v2'
output.mkdir(parents=True, exist_ok=True)
original = (ROOT / 'tests/atomic_mode.py').read_text()
line = "        assert c.must('CONFIG', 'SET', 'atomic', atomic) == b'OK'\n"
assert original.count(line) == 1
control = output / 'no-restore.py'
control.write_text(original.replace(line, ''))
rows = []
for mode in ('split', 'fused'):
    shape = ['--shards', '16', '--thread-mode', mode,
             '--read-local', '1' if mode == 'fused' else '0']
    if mode == 'split': shape += ['--ratio', '6:2']
    with server(ROOT / 'build/witnessfix/tomokv-7d2f8a205', '80-87', 20558,
                output / mode, shape) as (admin, _process):
        for atomic in ('0', '1'):
            admin.must('CONFIG', 'SET', 'atomic', str(1-int(atomic)))
            for arm, path in (('no-restore', control), ('restored', ROOT/'tests/atomic_mode.py')):
                command = ['python3', str(path), '127.0.0.1', '20558', atomic]
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONPATH=str(ROOT/'tests')))
                rows.append(dict(mode=mode, atomic=atomic, arm=arm, command=command,
                                 exit=result.returncode, stdout=result.stdout))
                assert (result.returncode == 0) == (arm == 'restored'), rows[-1]
                if arm == 'no-restore':assert 'TM4.1 live atomic mismatch' in result.stdout
(ROOT / 'docs/witnessfix/atomic-mode-control.json').write_text(json.dumps(rows,indent=2)+'\n')
control.unlink()
print('All four live settings reject removed restoration and accept restoration.')
