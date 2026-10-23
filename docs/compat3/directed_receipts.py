#!/usr/bin/env python3
"""Check presence and recorded observations for every directed gate leg."""
import argparse, hashlib, itertools, json, re
from pathlib import Path
DOC=Path(__file__).resolve().parent
CASES=("pubsub","pending","history","grammar","glob","flags")
ARMS={"POST":"POST-final","PRE":"PRE-final-control","PAD-A":"PAD-A-final"}
p=argparse.ArgumentParser();p.add_argument("--prefix",default="");args=p.parse_args()
all_rows={}
provenance={}
for arm,logname in ARMS.items():
    text=(DOC/(args.prefix+logname+".log")).read_text()
    run=Path(re.search(r"artifacts: (.+/build/gate-run\.\w+)",text)[1])/"jobs/compat3"
    assert (run/'done').read_text().strip()==('0\t6\t0' if arm=='POST' else '0\t0\t6')
    provenance[arm]=dict(log=args.prefix+logname+".log",run=str(run.parent.parent))
    rows=[]
    for case,db,atomic,engine,shape in itertools.product(CASES,(1,16),(0,1),("epoll","uring"),(("1s",0),("1s",1),("2s",0))):
        mode,rl=shape;filename=f"{case}-db{db}-{mode}-{engine}-a{atomic}-rl{rl}.log"
        lines=(run/filename).read_text().splitlines()
        oracle=[json.loads(x[7:]) for x in lines if x.startswith(("ORACLE {","ORACLE ["))]
        target=[json.loads(x[7:]) for x in lines if x.startswith(("TARGET {","TARGET ["))]
        geometry=[json.loads(x[9:]) for x in lines if x.startswith("GEOMETRY ")]
        assert len(oracle)==len(geometry)==1,(arm,filename,"missing oracle/geometry")
        assert geometry[0]==dict(thread_mode=mode,net_io=engine,atomic=str(atomic),read_local=str(rl),shards="16")
        passed="PASS "+case in lines
        failure=next((x for x in reversed(lines) if x.startswith("AssertionError:")),None)
        assert passed if arm=="POST" else not passed and failure,(arm,filename)
        if arm=="POST":assert target==oracle,(arm,filename)
        rows.append(dict(file=filename,case=case,passed=passed,oracle=oracle[0],target=target[0] if target else None,failure=failure))
    assert len(rows)==144
    all_rows[arm]=rows
pre={r['file']:r for r in all_rows['PRE']}
matched=0;witnesses=0
for pad in all_rows['PAD-A']:
    original=pre[pad['file']]
    assert pad['oracle']==original['oracle'],pad['file']
    assert pad['target']==original['target'],pad['file']
    if pad['target'] is not None: matched+=1
    else:
        assert 'both owners must apply' in pad['failure'] and pad['failure']==original['failure']
        witnesses+=1
summary=dict(arms={a:{case:dict(legs=sum(r['case']==case for r in rs),passed=sum(r['case']==case and r['passed'] for r in rs)) for case in CASES} for a,rs in all_rows.items()},
             pad_pre_observations_equal=matched,pad_pre_same_apply_witness_failure=witnesses,
             provenance=provenance)
(DOC/'directed-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
observations=DOC.parents[1]/'build/compat3/large-receipts/final-directed-observations.json'
observations.parent.mkdir(parents=True,exist_ok=True)
observations.write_text(json.dumps(all_rows,indent=2)+'\n')
manifest=dict(retained=str(observations.relative_to(DOC.parents[1])),bytes=observations.stat().st_size,
              sha256=hashlib.sha256(observations.read_bytes()).hexdigest(),
              reason='Exact observations exceed 1 MB; per-leg logs are retained in the small gate receipt archives.')
(DOC/'directed-observations-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(summary,indent=2))
