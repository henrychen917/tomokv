#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
sys.path.insert(0, "tests")
from _gate_process import server
os.sched_setaffinity(0,set(range(89,96)))
rows=[]
binary=Path("build/moverfix/pad-a/tomokv")
sha=hashlib.sha256(binary.read_bytes()).hexdigest()
assert sha == json.loads(Path("docs/moverfix/pad-a.json").read_text())["pad_sha256"]
for mode in ("2s","1s"):
    for dbs in (1,16):
        d=Path("docs/moverfix/pad-controls")/f"{mode}-db{dbs}"
        args=["--thread-mode",mode,"--atomic",0,"--shards",16,"--databases",dbs,"--key-lb",0,"--client-lb",0,"--flip-auto",0]
        if mode=="2s":args += ["--ratio","6:2"]
        with server(binary,"80-87",23810,d/"server",args) as (_,process):
            # Bind the receipt to the actual executable mapped by this child.
            assert hashlib.sha256(Path(f"/proc/{process.pid}/exe").read_bytes()).hexdigest() == sha
            for test in ("T05","G5"):
                with (d/(test+".log")).open("w") as log:
                    rc=subprocess.run(["python3","tests/moverfix.py","127.0.0.1","23810","--only",test],stdout=log,stderr=subprocess.STDOUT,timeout=120).returncode
                rows.append(dict(mode=mode,databases=dbs,test=test,rc=rc,sha256=sha))
                print(rows[-1],flush=True)
assert hashlib.sha256(binary.read_bytes()).hexdigest() == sha
Path("docs/moverfix/pad-controls/runs.json").write_text(json.dumps(rows,indent=2)+"\n")
