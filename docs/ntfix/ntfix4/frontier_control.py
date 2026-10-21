#!/usr/bin/env python3
"""Compile current frontier witness against unmodified bce4eb0aa headers/objects."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
HEAD=ROOT/'build/ntfix4/headline-src'
OUT=ROOT/'docs/ntfix/ntfix4/headline'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    commands=subprocess.check_output(['taskset','-c','80-95','make','-n','build/netcap-unit'],
                                     cwd=HEAD,text=True).splitlines()
    rows=[]
    for line in commands:
        if not line.startswith('g++ '): continue
        argv=shlex.split(line)
        argv=[str(ROOT/'tests/netcap_unit.cc') if x=='tests/netcap_unit.cc' else
              str(ROOT/'build/ntfix4/headline-frontier.o') if x=='build/tests/netcap_unit.o' else
              str(ROOT/'build/ntfix4/headline-frontier') if x=='build/netcap-unit' else x for x in argv]
        cmd=['taskset','-c','80-95',*argv]
        with (OUT/('frontier-compile.log' if '-c' in argv else 'frontier-link.log')).open('w') as log:
            p=subprocess.run(cmd,cwd=HEAD,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(command=cmd,returncode=p.returncode))
        assert p.returncode==0
    cmd=['taskset','-c','89-95',str(ROOT/'build/ntfix4/headline-frontier'),'frontier']
    with (OUT/'frontier-unit.log').open('w') as log:
        p=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    rows.append(dict(command=cmd,returncode=p.returncode))
    (OUT/'frontier-control.json').write_text(json.dumps(rows,indent=2)+'\n')
    assert p.returncode==1
    assert 'completed argv excluded even when queued MULTI equals the limit' in (OUT/'frontier-unit.log').read_text()
    print('PASS: current frontier witness fails on headline at completed-argv/queued-MULTI assertion')


if __name__=='__main__':
    main()
