#!/usr/bin/env python3
"""Verify saved correctness receipts, final hashes, freshness, and listener cleanup."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/ntfix/ntfix4'


def main():
    runtime=json.loads((OUT/'runtime.json').read_text())
    differ=json.loads((OUT/'differ/results.json').read_text())
    production=json.loads((OUT/'production/results.json').read_text())
    assert len(runtime['jobs'])==10 and all(r['returncode']==0 for r in runtime['jobs'])
    assert len(differ)==2 and all(r['returncode']==0 for r in differ)
    assert len(production)==38 and all(r['returncode']==0 for r in production)
    digest=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()
    assert digest==runtime['post_sha256']
    assert all(r['binary_sha256']==digest for r in differ)
    fragments=[]
    for p in sorted((OUT/'post/fragments').glob('*/fragment-*.log')):
        row=json.loads(p.read_text().strip())
        assert row['result']=='PASS' and row['fragment_trials']==4692
        fragments.append(dict(log=str(p.relative_to(ROOT)),**row))
    assert len(fragments)==8
    for p in (OUT/'post/limits').glob('*/differences.json'):
        assert json.loads(p.read_text())==[]
    assert len(list((OUT/'post/limits').glob('*/differences.json')))==4
    fresh=[]
    for row in production:
        if row['command'][:2]!=['make','-q']:continue
        cmd=['taskset','-c','80-95',*row['command']]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        fresh.append(dict(command=cmd,returncode=p.returncode,output=p.stdout+p.stderr))
    (OUT/'production/final-freshness.json').write_text(json.dumps(fresh,indent=2)+'\n')
    assert len(fresh)==36 and all(r['returncode']==0 for r in fresh)
    listeners=subprocess.check_output(['taskset','-c','80-95','ss','-Hlnpt'],text=True)
    lane=[line for line in listeners.splitlines()
          if re.search(r':228\d\d\b',line)]
    assert not lane,lane
    gate=(ROOT/'tests/gate.sh').read_text()
    base=subprocess.check_output(['git','show','bce4eb0aa:tests/gate.sh'],cwd=ROOT,text=True)
    constants=lambda s:re.findall(r'^EXPECT_(?:QUICK|FULL)=.*$',s,re.M)
    assert constants(gate)==constants(base)
    artifacts=dict(post='build/tomokv',post_sha256=digest,
                   headline='build/ntfix4/headline-src/build/tomokv',
                   headline_sha256=hashlib.sha256((ROOT/'build/ntfix4/headline-src/build/tomokv').read_bytes()).hexdigest(),
                   source_commit='47fa7d9b1',build_cpus='80-95',server_cpus='80-87',
                   oracle_cpus='88',client_cpus='89-95',ports='22800-22899',
                   fragments=fragments,fragment_trials=sum(r['fragment_trials'] for r in fragments),
                   production_freshness_checks=len(fresh),lane_listeners=lane,
                   expect_constants=constants(gate),required_counts=dict(quick=669,full=686,DQ=4,DF=4),
                   not_run={'performance/null/ABBA/landing gate':'maintainer-owned; excluded from correctness authorization',
                            'broad standard differential matrix':'outside the ntfix4 requested focused matrix'})
    (OUT/'artifacts.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    print(json.dumps({k:v for k,v in artifacts.items() if k!='fragments'},indent=2))


if __name__=='__main__':
    main()
