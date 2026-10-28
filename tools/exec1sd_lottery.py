#!/usr/bin/env python3
"""Bounded W16 smoke for the copied-source witness image, not a nightly verdict."""
import json
import os
import subprocess
import uuid

import exec1sd as d


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
            with (folder/'run.log').open('w') as log:
                result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            receipt=json.loads((folder/'receipt.json').read_text())
            correct=(result.returncode==0 and receipt['completed'] and
                     receipt['passed'] and receipt['evidence_complete'])
            hit=correct and all(receipt['counters'].get(w,0)>0 for w in row['requires'])
            attempts.append(dict(command=cmd,returncode=result.returncode,correct=correct,hit=hit,
                receipt=str(folder/'receipt.json'),receipt_sha256=d.sha(folder/'receipt.json'),
                counters=receipt['counters']))
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
