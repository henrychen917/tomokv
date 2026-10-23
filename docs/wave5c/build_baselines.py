#!/usr/bin/env python3
"""Build source-matched historical ASAN arms in one disposable source/object tree."""
import hashlib,json,os,shutil,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/"build/wave5c/arms"; DOC=ROOT/"docs/wave5c"
assert os.sched_getaffinity(0)<=set(range(64,112))
refs={"headline":"a7dfb9d23","iofix":"fcb52cd49","fliplisten":"4661b0c46","netfix":"c98b92959"}
records=[]
for name,ref in refs.items():
    src=ROOT/"build/wave5c/asan-source"
    if src.exists():shutil.rmtree(src)
    src.mkdir()
    archive=ROOT/"build/wave5c/source.tar"
    with archive.open("wb") as f:subprocess.run(["git","archive",ref,"src","tests","third_party"],cwd=ROOT,stdout=f,check=True)
    with tarfile.open(archive) as t:t.extractall(src,filter="data")
    archive.unlink()
    out=OUT/(name+"-asan")
    sources=[src/"src/main.cc",src/"src/net/tls.cc"]
    for d in ["core","cmd","snapshot","persist"]:sources+=sorted((src/"src"/d).glob("*.cc"))
    cmd=[str(ROOT/"tests/parbuild.sh"),str(out),str(src/"objects"),"-std=c++20 -O1 -g -fsanitize=address -march=native -pthread -I.","-luring -pthread -lssl -lcrypto",*[str(p.relative_to(src)) for p in sources]]
    start=time.time()
    with (DOC/(name+"-asan-build.log")).open("w") as f:r=subprocess.run(cmd,cwd=src,env=dict(os.environ,PARBUILD_JOBS="32"),stdout=f,stderr=subprocess.STDOUT)
    row=dict(name=name,ref=ref,command=cmd,returncode=r.returncode,seconds=time.time()-start)
    if not r.returncode:row["sha256"]=hashlib.sha256(out.read_bytes()).hexdigest()
    records.append(row);(DOC/"baseline-builds.json").write_text(json.dumps(records,indent=2)+"\n")
    print(json.dumps(row),flush=True)
    if r.returncode:raise SystemExit(r.returncode)
shutil.rmtree(src)
