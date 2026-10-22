#!/usr/bin/env python3
"""Require every standard suite/seed leg and its recorded engine geometry."""
import argparse, json, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/compat3"
p=argparse.ArgumentParser()
p.add_argument('--uring-log',default='differ-uring.log')
p.add_argument('--epoll-log',default='resume-differ-epoll.log')
args=p.parse_args()
sys.path.insert(0,str(ROOT/'tests'))
from differ_fanout import expected_legs, check_equivalence
standard=subprocess.check_output(["python3","tests/differ.py","--list-generators"],cwd=ROOT,text=True).split()
results=[]
for engine,logname in (("uring",args.uring_log),("epoll",args.epoll_log)):
    log=(DOC/logname).read_text()
    run=Path(re.search(r"artifacts: (.+/build/gate-run\.\w+)",log)[1])
    assert any(x.startswith('end\t') for x in (run/'phases.tsv').read_text().splitlines()), 'interrupted gate'
    plan=json.loads((run/"differ-plan.json").read_text())
    assert plan['suites']==standard
    seeds=plan['manifest']['seeds']
    assert {7,19,20,23}<=set(seeds) and plan['manifest']['rotating'] in seeds
    parts=[]
    for mode in ("split","armed"):
        for atomic in (0,1):
            part=f"{mode}-{atomic}";directory=run/"jobs"/("differ-"+part)/"differ"
            completion=directory/"complete.json"
            complete=json.loads(completion.read_text()) if completion.exists() else None
            expected=expected_legs(plan,part)
            rows=[x.split("\t") for x in (directory/"legs.tsv").read_text().splitlines()]
            actual=[(r[0],int(r[1]),int(r[2]),int(r[3])) for r in rows]
            assert len(rows)==len(set(actual)) and actual==expected
            failures=[dict(suite=r[0],atomic=int(r[1]),seed=int(r[2]),repeat=int(r[3]),
                           returncode=int(r[4]),log=str((directory/r[5]).relative_to(ROOT)))
                      for r in rows if int(r[4])!=0]
            assert all((directory/(r[5]+".coverage.json")).is_file() for r in rows)
            for r in rows:
                coverage=json.loads((directory/(r[5]+".coverage.json")).read_text())
                assert coverage['schema']==1 and coverage['commands']
            if not failures:
                assert complete and complete['complete'] and complete['seeds']==seeds
                assert len(rows)==complete['comparisons']
                assert (directory.parent/'done').read_text().strip()=='0\t1\t0'
            else:
                assert complete is None, 'failed matrix incorrectly published success'
                assert (directory.parent/'done').read_text().split()[-1]=='1'
            banner=(directory/f"target-atomic-{atomic}.log").read_text()
            marker=", io_uring," if engine=="uring" else ", epoll,"
            assert marker in banner and "8 threads" in banner and "16 shard(s)" in banner
            assert "8 cpus [96,97,98,99,100,101,102,103]" in banner
            assert ("thread-mode=2s" if mode=="split" else "thread-mode=1s") in banner
            if mode=="split":assert "6 io + 2 ex" in banner
            else:assert "read-local=1" in banner
            output=(directory.parent/'output.log').read_text()
            if mode=='armed':assert re.search(r'read-local lane fired.*ok \(hits=[1-9]',output)
            assert re.search(r'target atomic=\d stop\s+ok',output)
            assert re.search(r'oracle stop\s+ok',output)
            parts.append(dict(part=part,comparisons=len(rows),complete=complete is not None,
                              failed_legs=failures,passed_legs=len(rows)-len(failures)))
    eq=json.loads((run/"jobs/differ-equivalence/differ/complete.json").read_text())
    assert eq['complete'] and eq['comparisons']==check_equivalence(plan,run/'jobs/differ-equivalence/differ')
    eqout=(run/"jobs/differ-equivalence/output.log").read_text()
    assert re.search(r"all 32 execution/knob combinations\s+ok", eqout)
    results.append(dict(engine=engine,log=logname,run=str(run),manifest=plan,parts=parts,
                        complete=all(p['complete'] for p in parts),
                        equivalence_comparisons=eq['comparisons'],
                        comparisons=sum(p['comparisons'] for p in parts)+eq['comparisons'],
                        declared_skips=[dict(suite="sort",mode="armed",atomic=a,seed=s,
                            reason="standard gate requires split 6:2 for this suite") for a in (0,1) for s in seeds]))
(DOC/"differ-summary.json").write_text(json.dumps(results,indent=2)+"\n")
print([(r['engine'],r['comparisons'],len(r['declared_skips'])) for r in results])
sys.exit(int(any(not r['complete'] for r in results)))
