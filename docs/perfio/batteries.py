#!/usr/bin/env python3
"""Focused PROOF batteries, owned servers on the lane-reserved CPUs and ports."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests"))
from perfio import boot

out=ROOT/"docs/perfio/batteries"
out.mkdir(parents=True,exist_ok=True)
rows=[]
for engine in ("epoll","uring"):
    for mode in ("2s","1s"):
        args=SimpleNamespace(output=out,binary=ROOT/"build/tomokv",port=25133,cores="112-119",
            mode=mode,ratio="6:2",net_io=engine,oracle=False,read_local=0)
        jobs=[("netio",["tests/netio.py","127.0.0.1","25133",engine]),
              ("lb-stationary",["tests/lb_stationary.py","--port","25133",
                "--output",str(out/f"lb-{mode}-{engine}.json")])]
        if mode=="2s":
            jobs += [("flip",["tests/flip.py","127.0.0.1","25133"]),
                     ("flip-load",["tests/flip_under_load.py","127.0.0.1","25133","20"])]
        for name,argv in jobs:
            with boot(args,f"{name}-{mode}-{engine}",["--key-lb","1","--client-lb","1"]) as (c,p):
                path=out/f"{name}-{mode}-{engine}.log"
                with path.open("w") as log:
                    r=subprocess.run(["taskset","-c","121-127","python3",*argv],cwd=ROOT,
                        stdout=log,stderr=subprocess.STDOUT,timeout=180)
                row=dict(name=name,mode=mode,engine=engine,exit=r.returncode,log=str(path.relative_to(ROOT)))
                rows.append(row)
                print(json.dumps(row),flush=True)
                (out/"results.json").write_text(json.dumps(rows,indent=2)+"\n")

raise SystemExit(0 if all(row["exit"] == 0 for row in rows) else 1)
