#!/usr/bin/env python3
"""Run final correctness jobs sequentially after the initial selected gate exits."""
import json
import os
from pathlib import Path
import subprocess
import time
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/execfair/correctness'
OUT.mkdir(exist_ok=True)
base = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis',
            GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server')
while not (ROOT / 'build/execfair-correctness.exit').exists(): time.sleep(5)
wrapper = ROOT / 'build/execfair-epoll'
wrapper.write_text('#!/bin/bash\nexec /home/user/Projects/cx-execfair/build/tomokv "$@" --net-io epoll\n')
wrapper.chmod(0o755)
rows = []
for name,jobs,binary,tier,expected in [
    ('final-txnorder2', 'txnorder2', None, 'quick', 0),
    ('alt-witness', 'execfair', ROOT / 'build/post-alt/tomokv', 'quick', 0),
    ('pad-witness', 'execfair', ROOT / 'build/pad-a/tomokv', 'quick', 1),
    ('retry-split-1', 'differ-split-1', None, 'full', 0),
    ('stress', '', None, '', 0),
    ('epoll-differ', 'differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence', wrapper, 'full', 0),
]:
    if name == 'stress':
        with (ROOT / 'build/execfair-stress.log').open('w') as stream:
            stress = subprocess.run(['taskset','-c','64-79','python3','docs/execfair/drivers/stress.py'],
                                    cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        (ROOT / 'build/execfair-stress.exit').write_text(str(stress.returncode)+'\n')
        rows.append(dict(name='stress',exit_code=stress.returncode,expected_exit=0))
        (OUT / 'followups.json').write_text(json.dumps(rows,indent=2)+'\n')
        print('stress',stress.returncode,flush=True)
        continue
    env = dict(base, GATE_ONLY_JOBS=jobs, GATE_LEDGER=str(ROOT / ('build/execfair-'+name+'.tsv')))
    argv = ['taskset','-c','64-79','bash','tests/gate.sh',tier,'--server-cores','64-71',
            '--load-cores','72-79','--load-smt','','--ports','30800-30899']
    if binary: argv += ['--candidate-binary',str(binary)]
    log = ROOT / ('build/execfair-'+name+'.log')
    with log.open('w') as stream:
        result = subprocess.run(argv,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    rows.append(dict(name=name,command=argv,environment={k:env[k] for k in base.keys() | {'GATE_ONLY_JOBS','GATE_LEDGER'} if k.startswith('GATE_') or k=='REDIS74_ROOT'},
                     log=str(log.relative_to(ROOT)),exit_code=result.returncode,expected_exit=expected))
    (OUT / 'followups.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(name,result.returncode,flush=True)
assert all(r['exit_code']==r['expected_exit'] for r in rows)
