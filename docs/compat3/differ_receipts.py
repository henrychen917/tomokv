#!/usr/bin/env python3
"""Require every standard suite/seed leg and its recorded engine geometry."""
import json, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/compat3"
standard=subprocess.check_output(["python3","tests/differ.py","--list-generators"],cwd=ROOT,text=True).split()
results=[]
for engine in ("uring","epoll"):
    log=(DOC/("differ-"+engine+".log")).read_text()
    run=Path(re.search(r"artifacts: (.+/build/gate-run\.\w+)",log)[1])
    plan=json.loads((run/"differ-plan.json").read_text())
    assert plan['suites']==standard
    seeds=plan['manifest']['seeds']
    assert {7,19,20,23}<=set(seeds) and plan['manifest']['rotating'] in seeds
    parts=[]
    for mode in ("split","armed"):
        for atomic in (0,1):
            part=f"{mode}-{atomic}";directory=run/"jobs"/("differ-"+part)/"differ"
            complete=json.loads((directory/"complete.json").read_text())
            assert complete['complete'] and complete['seeds']==seeds
            expected={(suite,atomic,seed,0) for suite in standard for seed in seeds
                      if not (mode=="armed" and suite=="sort")}
            if atomic==1:expected|={("multi",1,19,r) for r in range(1,plan['repeats']+1)}
            rows=[x.split("\t") for x in (directory/"legs.tsv").read_text().splitlines()]
            actual={(r[0],int(r[1]),int(r[2]),int(r[3])) for r in rows}
            assert len(rows)==len(actual)==complete['comparisons'] and actual==expected
            assert all(int(r[4])==0 and (directory/(r[5]+".coverage.json")).is_file() for r in rows)
            banner=(directory/f"target-atomic-{atomic}.log").read_text()
            marker=", io_uring," if engine=="uring" else ", epoll,"
            assert marker in banner and "8 threads" in banner and "16 shard(s)" in banner
            assert "8 cpus [96,97,98,99,100,101,102,103]" in banner
            assert ("thread-mode=2s" if mode=="split" else "thread-mode=1s") in banner
            if mode=="split":assert "6 io + 2 ex" in banner
            else:assert "read-local=1" in banner
            parts.append(dict(part=part,comparisons=len(rows),complete=True))
    eq=json.loads((run/"jobs/differ-equivalence/differ/complete.json").read_text())
    assert eq['complete'] and eq['comparisons']==16*len(plan['equivalence_seeds'])
    eqout=(run/"jobs/differ-equivalence/output.log").read_text()
    assert re.search(r"all 32 execution/knob combinations\s+ok", eqout)
    results.append(dict(engine=engine,run=str(run),manifest=plan,parts=parts,
                        equivalence_comparisons=eq['comparisons'],
                        comparisons=sum(p['comparisons'] for p in parts)+eq['comparisons'],
                        declared_skips=[dict(suite="sort",mode="armed",atomic=a,seed=s,
                            reason="standard gate requires split 6:2 for this suite") for a in (0,1) for s in seeds]))
(DOC/"differ-summary.json").write_text(json.dumps(results,indent=2)+"\n")
print([(r['engine'],r['comparisons'],len(r['declared_skips'])) for r in results])
