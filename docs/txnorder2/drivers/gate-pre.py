#!/usr/bin/env python3
"""Build positive-expectation gate fixtures against the pre-amendment merge.

These use the observed-stamp instrumentation disclosed in controls/. The server
is the unmodified 73e35f754 binary. No PRE outcome is substituted into a PASS.
"""
import json,shutil,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[3];base=R/"build/txnorder2/episode-pre-source"
source=R/"build/txnorder2/control-pre";out=R/"build/txnorder2/gate-pre";out.mkdir(exist_ok=True)
docs=R/"docs/txnorder2/gate-pre-build";docs.mkdir(exist_ok=True)
shutil.copy2(base/"build/tomokv",out/"tomokv")
shutil.copy2(R/"src/cmd/txnorder_debug.h",source/"src/cmd/txnorder_debug.h")
recipe=json.loads((R/"docs/txnorder2/episodes-build-command.json").read_text());rows=[]
for name,fixture,db0,debug in [("txnorder-episodes","txnorder_episodes.cc",False,False),
 ("txnorder-episodes-debug","txnorder_episodes.cc",False,True),
 ("txnorder-watch-unit","txnorder_watch_unit.cc",False,False),
 ("txnorder-watch-db0-unit","txnorder_watch_unit.cc",True,False)]:
 cmd=["taskset","-c","64-95"]
 for a in recipe:
  if a=="tests/txnorder_episodes.cc":a=str(source/"tests"/fixture)
  elif a=="build/txnorder2/episodes":a=str(out/name)
  elif a=="-I.":a="-I"+str(source)
  elif a.startswith("build/src/") and a.endswith(".o"):
   a=str(base/(a.replace("build/src/","build/db0/src/") if db0 else a))
  cmd.append(a)
 if db0:
  cmd += ["-DTOMO_SINGLE_DATABASE=1","-Dtomo=tomo_db0"]
  cmd += [str(p) for p in (base/"build/src").rglob("*.o") if p.name not in ("main.o","version.o")]
 if debug:cmd += ["-DTOMO_TXNORDER_DEBUG","-include",str(source/"src/cmd/txnorder_debug.h")]
 with (docs/(name+".log")).open("w") as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 rows.append(dict(name=name,command=cmd,exit_code=rc))
 (docs/"build.json").write_text(json.dumps(rows,indent=2)+"\n")
 print(name,rc,flush=True)
