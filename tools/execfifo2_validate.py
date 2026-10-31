#!/usr/bin/env python3
"""Selected correctness jobs only; never the iteration or performance tiers."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"build/execfifo2/validation"
DOCS=ROOT/"docs/execfifo2/validation"
DIRECTED="txnorder_fifo txnorder_chain txnorder_index txnorder_wound txnorder2 txnorder_wake exec1s at412-owner"
TXN="txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1"
BATTERIES="debug-0 debug-1 release_batteries atomic_batteries script_bounds"
BROAD="feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1 txn_group_fused txn_group_split notify notifycompat notify_order notify_aof tracking_redirect trackfix_accounting trackfix_order datafix2_watch atomfix5_watch blockfix2 blockfix_structure blockfix_registry blockfix_mkstream rlfix3_zc rlfix3_info readonly"
CORE="core_units flip_unit flipfix_units flipfix5_units splitlocal_units wait_units atomic_units"
FEATURES=" ".join("feature-cell-"+"-".join(map(str,cell)) for cell in itertools.product(("1s","2s"),(0,1),(0,1),(0,1),(0,1)))
GROUPS={"directed":("quick",DIRECTED,{}),
        "fairness":("quick","execfair txnorder_fifo_live",{}),
        "at412":("quick"," ".join("at412-"+s for s in "T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16".split()),{}),
        "scripts":("quick","scriptfix scriptfix2 lualibs",{}),
        "core":("quick",CORE,{}),
        "headline":("quick"," ".join(prefix+"-"+mode+"-"+engine for prefix in ("multifix","climonfix4") for mode in ("1s","2s") for engine in ("uring","epoll"))+" pubtrackfix climonfix atomfix5_accounting moverfix exbatch_units exbatch_live wb_rule_units wbland_units",{}),
        "readlocal":("full","rlcache splitlocal_units",{}),
        "features":("quick",FEATURES+" feature-cell-split-home-min feature-cell-fused-home-max-nopin feature-cell-split-shards-auto",{}),
        "flip":("quick","flipctl flip fliplisten flipfix5",{})}
for engine in ("uring","epoll"):
    env=dict(GATE_NET_IO=engine,GATE_PROOF_NET_IO=engine,GATE_DIFFER_NET_IO=engine)
    GROUPS["txn-"+engine]=("quick",TXN,env)
    GROUPS["broad-"+engine]=("quick",BROAD,env)
    GROUPS["differ-"+engine]=("full","differ-split differ-armed",env)
    for fused in (0,1):
        GROUPS[f"asan-{engine}-{fused}"]=("full","asan_batteries",env|dict(GATE_TXN_FUSED=str(fused)))
        GROUPS[f"batteries-{engine}-{fused}"]=("quick",BATTERIES,env|dict(GATE_TXN_FUSED=str(fused)))
        GROUPS[f"scriptbounds-{engine}-{fused}-a0"]=("quick","script_bounds",env|dict(GATE_TXN_FUSED=str(fused),GATE_TXN_ATOMIC="0"))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("groups",nargs="+",choices=sorted(GROUPS));args=p.parse_args()
    assert os.sched_getaffinity(0)<=set(range(32))
    OUT.mkdir(parents=True,exist_ok=True);DOCS.mkdir(parents=True,exist_ok=True)
    manifest=DOCS/"runs.json"
    rows=json.loads(manifest.read_text()) if manifest.exists() else []
    for name in args.groups:
        tier,jobs,extra=GROUPS[name]
        env=dict(os.environ,LC_ALL="C",GATE_PROOF_NO_RATES="1",GATE_ONLY_JOBS=jobs,
                 REDIS74_ROOT="/home/user/Projects/redis",
                 GATE_DIFFER_ORACLE_BIN="/home/user/Projects/redis/src/redis-server",
                 GATE_DIFFER_REDIS_CLI="/home/user/Projects/redis/src/redis-cli",**extra)
        log=OUT/(name+"-"+str(time.time_ns())+".log")
        cmd=["tests/gate.sh",tier,"--server-cores","0-15","--server-smt","",
             "--load-cores","16-31","--load-smt","","--ports","20100-20199"]
        row=dict(group=name,command=cmd,environment={k:env[k] for k in env if k in extra or k.startswith("GATE_") or k in ("LC_ALL","REDIS74_ROOT")},
                 binary_sha256=hashlib.sha256((ROOT/"build/tomokv").read_bytes()).hexdigest(),log=str(log))
        print("START",name,flush=True)
        with log.open("w") as stream: result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        text=log.read_text();match=re.search(r"  artifacts: (.*)",text)
        row.update(exit_code=result.returncode,run_directory=match[1] if match else None)
        rows.append(row);manifest.write_text(json.dumps(rows,indent=2)+"\n")
        print("DONE",name,result.returncode,text.splitlines()[-1] if text else "empty log",flush=True)
        # Preserve all failed rows and continue independent required groups.

if __name__=="__main__":main()
