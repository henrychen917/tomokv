#!/usr/bin/env python3
"""Compile-only inlining trials; no server or timing measurement."""
import concurrent.futures,hashlib,json,re,shlex,subprocess
from pathlib import Path
from lbstall_artifacts import Elf,HOT
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"docs/rlfix4/budgets";OUT.mkdir(parents=True,exist_ok=True)
BUILD=ROOT/"build/rlfix4/budgets";BUILD.mkdir(parents=True,exist_ok=True)
UNITS={"db0/src/core/genthread.o":132012,"db0/src/core/reorder.o":150092,"src/core/genthread.o":131218,"src/core/reorder.o":149103}
def one(case):
 obj,budget=case
 label=obj.replace("/","_")+"-"+str(budget)
 output=BUILD/(label+".o")
 recipe=subprocess.check_output(["make","-n","-B","build/"+obj],cwd=ROOT,text=True)
 cmd=shlex.split(next(x for x in recipe.splitlines() if x.startswith("g++ ") and " -c " in x))
 cmd=["large-unit-insns="+str(budget) if x.startswith("large-unit-insns=") else "-g0" if x=="-g" else x for x in cmd]
 cmd[cmd.index("-o")+1]=str(output)
 with (OUT/(label+".log")).open("w") as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=log,check=True)
 a,b=Elf(ROOT/"build"/obj),Elf(output);old,new=a.functions(),b.functions()
 symbols=list(old)
 names=subprocess.check_output(["c++filt"],input="\n".join(symbols),text=True).splitlines()
 changes=[];parsers=[]
 for sym,name in zip(symbols,names):
  if not HOT.search(name):continue
  before=a.canonical(old[sym]);after=b.canonical(new[sym]) if sym in new else None
  if before!=after:changes.append(dict(name=name,symbol=sym,pre_size=old[sym]["size"],post_size=new.get(sym,{}).get("size",0)))
  if "parse_and_dispatch<false, 32u, false>" in name and "lambda" not in name:
   targets=[] if not after else [str(x) for x in after[1]]
   parsers.append(dict(name=name,size=new.get(sym,{}).get("size",0),calls={key:sum(key in x for x in targets) for key in ("cmd_name","hash_key","local_read_lane_has_room")}))
 row=dict(object=obj,budget=budget,command=cmd,object_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),changes=changes,parsers=parsers)
 (OUT/(label+".json")).write_text(json.dumps(row,indent=2)+"\n")
 print(obj,budget,"changed",len(changes),"parsers",parsers,flush=True)
 return row
if __name__=="__main__":
 cases=[(obj,base+d) for obj,base in UNITS.items() for d in (0,16,32,64,128,256)]
 with concurrent.futures.ThreadPoolExecutor(16) as pool:rows=list(pool.map(one,cases))
 (OUT/"results.json").write_text(json.dumps(rows,indent=2)+"\n")
