#!/usr/bin/env python3
"""Run unchanged strict identity tools; retain their verdicts, including failures."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/ntfix/ntfix4/identity'
HEAD=ROOT/'build/ntfix4/headline-src/build'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    jobs=[('full',['python3','tools/ccfix_audit.py',str(HEAD),'build',str(OUT/'full')]),
          ('hot',['python3','tools/lbstall_artifacts.py','compare',str(HEAD),'build',str(OUT/'hot.json')]),
          ('linked',['python3','docs/deadswitch/linked_bytes.py',str(HEAD/'tomokv'),
                     'build/tomokv',str(OUT/'linked.json')]),
          ('dual-reference',['python3','docs/ntfix/ntfix4/identity.py'])]
    rows=[]
    for name,args in jobs:
        cmd=['taskset','-c','80-95',*args]
        with (OUT/(name+'.log')).open('w') as log:
            p=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(tool=name,command=cmd,returncode=p.returncode))
        (OUT/'tools.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(name,p.returncode,flush=True)
    assert rows[-1]['returncode']==0


if __name__=='__main__':
    main()
