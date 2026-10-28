#!/usr/bin/env python3
"""Bounded W16 smoke for the copied-source witness image, not a nightly verdict."""
import json
import os
import subprocess
import sys
import uuid

import exec1sd as d
sys.path.insert(0,str(d.ROOT/'tests'))
from lottery_runner import run_child


def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    subprocess.run(['make','-q','build/lottery/tomokv'],check=True)
    saved=json.loads((d.DOCS/'lottery-build.json').read_text())
    assert d.sha(saved['binary'])==saved['sha256']
    assert d.sha(d.ROOT/'build/tomokv')==saved['production_sha256']
    out=d.OUT/'lottery-witness';out.mkdir(exist_ok=False)
    rows=[]
    inventory=json.loads((d.ROOT/'tests/lottery_rows.json').read_text())
    for row in [x for x in inventory if x['family']=='multi_exec']:
        attempts=[];hit=False
        for index in range(8):
            folder=out/row['id']/str(index);folder.mkdir(parents=True)
            cmd=['python3','tests/lottery_attempt.py','--row',row['id'],
                 '--output',str(folder),'--nonce',uuid.uuid4().hex,
                 '--binary',saved['binary'],'--production-binary',str(d.ROOT/'build/tomokv'),
                 '--port','20002','--server-cpus','64-71','--client-cpus','72-95']
            rc,expired=run_child(cmd,folder/'run.log',180)
            path=folder/'receipt.json'
            receipt=json.loads(path.read_text()) if path.exists() else {}
            correct=(not expired and rc==0 and receipt.get('completed') is True and
                     receipt.get('passed') is True and receipt.get('evidence_complete') is True and
                     receipt.get('row')==row['id'] and receipt.get('nonce')==cmd[cmd.index('--nonce')+1] and
                     all(type(receipt.get('counters',{}).get(w)) is int for w in row['requires']))
            hit=correct and all(receipt['counters'].get(w,0)>0 for w in row['requires'])
            attempts.append(dict(command=cmd,returncode=rc,timed_out=expired,correct=correct,hit=hit,
                receipt=str(path),receipt_sha256=d.sha(path) if path.exists() else None,
                counters=receipt.get('counters',{})))
            # A failed assertion is final evidence. Only a correct attempt
            # without a witnessed window can re-arm on fresh state.
            if hit or not correct:break
        rows.append(dict(row=row,passed=hit,attempts=attempts))
        d.save(d.DOCS/'lottery-witness.json',dict(binary_sha256=saved['sha256'],
            production_sha256=saved['production_sha256'],nightly_verdict=False,
            rows=rows,passed=all(x['passed'] for x in rows)))
        print(row['id'],'PASS' if hit else 'FAIL',len(attempts),flush=True)
    raise SystemExit(0 if all(x['passed'] for x in rows) else 1)


if __name__=='__main__':main()
