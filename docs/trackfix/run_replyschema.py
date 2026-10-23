"""Run the unchanged standalone tracking-schema assertions; no gate job exists."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from run_proof import ROOT, BASE, DOC, environment

spec = importlib.util.spec_from_file_location('support', ROOT / 'docs/wave4/run_supplemental.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
support.ROOT = ROOT
support.OUT = BASE / 'replyschema'
dest = DOC / 'replyschema'
dest.mkdir(exist_ok=False)
results = []
for arm in ('PRE', 'POST'):
    binary = ROOT / ('build/tomokv-PRE' if arm == 'PRE' else 'build/tomokv')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    for mode in ('1s', '2s'):
        for engine in ('epoll', 'uring'):
            for atomic in (0, 1):
                label = f'{arm}-{mode}-{engine}-a{atomic}'
                shape = ['--shards', '16', '--thread-mode', mode, '--atomic', str(atomic),
                         '--net-io', engine, '--read-local', '1' if mode == '1s' else '0']
                if mode == '2s':
                    shape += ['--ratio', '6:2']
                with support.owned(label, binary, '96-103', 22870, shape):
                    argv = ['taskset', '-c', '105-111', 'python3', 'tests/replyschema.py',
                            '127.0.0.1', '22870', str(BASE / 'oracle')]
                    with (dest / (label + '.log')).open('w') as output:
                        result = subprocess.run(argv, cwd=ROOT, env=environment(),
                            stdout=output, stderr=subprocess.STDOUT, timeout=300)
                    row = dict(label=label, arm=arm, mode=mode, engine=engine, atomic=atomic,
                               sha256=digest, argv=argv, returncode=result.returncode)
                    results.append(row)
                    (dest / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
                    print(label, result.returncode, flush=True)
