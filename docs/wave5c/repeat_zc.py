#!/usr/bin/env python3
"""Repeat the unchanged gate zc job, binding release and matching ASAN arms."""
import argparse,concurrent.futures,hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; DOC=ROOT/"docs/wave5c"; BUILD=ROOT/"build/wave5c"
p=argparse.ArgumentParser();p.add_argument("phase",choices=["baseline","fixed"]);p.add_argument("--count",type=int);a=p.parse_args()
assert os.sched_getaffinity(0)<=set(range(64,112))
bins=Path("/home/user/Projects/bins")
arms={"wave5b":bins/"wave5b-2028fd77","headline":Path("/home/user/Projects/bench-bins/tomokv-headline-a7dfb9d23"),"iofix":bins/"iofix-post-a7a3d72a","fliplisten":bins/"fliplisten-post-191a4d96","netfix":bins/"netfix-post-9cfcbcb1"} if a.phase=="baseline" else {"fixed":ROOT/"build/tomokv"}
engines=["uring"] if a.phase=="baseline" else ["uring","epoll"]
count=a.count or (30 if a.phase=="baseline" else 50)
records=[]
# Three independent 6:2 servers; eight disjoint load cores apiece.
def slot_work(slot):
    result=[]
    seq=0
    for arm,binary in arms.items():
        asan=BUILD/"arms"/(arm+"-asan")
        assert asan.is_file(),asan
        for engine in engines:
            for iteration in range(slot,count,3):
                name=f"{a.phase}-{arm}-{engine}-{iteration+1:02d}"
                cmd=["python3",str(DOC/"verify.py"),name,"zc","--binary",str(binary),"--asan",str(asan),"--zc-engine",engine,"--single-slot","--server-cores",f"{64+slot*16}-{71+slot*16}","--load-cores",f"{72+slot*16}-{79+slot*16}","--ports",f"{27000+slot*10}-{27009+slot*10}"]
                receipt=DOC/"gate"/name/"result.json"
                completed=False
                if receipt.exists():
                    previous=json.loads(receipt.read_text())
                    paths=previous["run_paths"]
                    completed=len(paths)==1 and (Path(paths[0])/"jobs/zc/ledger").exists()
                    if not completed:
                        receipt.parent.rename(receipt.parent.with_name("launch-invalid-"+name))
                if not completed:
                    with (BUILD/(name+".log")).open("w") as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                r=json.loads(receipt.read_text())
                paths=r["run_paths"];assert len(paths)==1
                directory=Path(paths[0]);ledger=(directory/"jobs/zc/ledger").read_text()
                logs=list((directory/"jobs/zc").glob("gate-srv-zc.*"))
                leaks=[str(f) for f in logs if "LeakSanitizer:" in f.read_text()]
                row=dict(arm=arm,engine=engine,iteration=iteration+1,returncode=r["returncode"],sha256=r["binary_sha256"],asan_sha256=hashlib.sha256(asan.read_bytes()).hexdigest(),run=str(directory),ledger=ledger,leak_logs=leaks)
                result.append(row)
                print(json.dumps(dict(arm=arm,engine=engine,iteration=iteration+1,rc=r["returncode"],leaks=len(leaks))),flush=True)
    return result
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    for result in pool.map(slot_work,range(3)):
        records+=result
        (DOC/(a.phase+"-zc.json")).write_text(json.dumps(records,indent=2)+"\n")
summary=[]
for arm in arms:
 for engine in engines:
    rows=[r for r in records if r["arm"]==arm and r["engine"]==engine]
    summary.append(dict(arm=arm,engine=engine,runs=len(rows),failures=sum(r["returncode"]!=0 for r in rows),lsan_failures=sum(bool(r["leak_logs"]) for r in rows)))
(DOC/(a.phase+"-zc-summary.json")).write_text(json.dumps(summary,indent=2)+"\n")
print(json.dumps(summary),flush=True)
