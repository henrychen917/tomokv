#!/usr/bin/env python3
import importlib.util,json
from pathlib import Path
p=Path(__file__).with_name("runtime.py");sp=importlib.util.spec_from_file_location("r",p);r=importlib.util.module_from_spec(sp);sp.loader.exec_module(r)
rows=json.loads((r.ROOT/"docs/txnorder/owner-proof-plan.json").read_text())["rows"]
for mode,idx in [("2s",5),("1s",19)]:
 row=r.transform(rows[idx]);row["server"]=[("88-95" if x=="64-71" else "27890" if x=="27801" else x) for x in row["server"]]
 for case in ["watch","atomfix"]:
  test="tests/txniso.py" if case=="watch" else "tests/atomfix.py"
  row["command"]=["taskset","-c","85-95","python3",test,"127.0.0.1","27890"]+(["--mode",mode,"--only","W3"] if case=="watch" else [])
  row["name"]="witness-"+case+"-"+mode
  r.run(300+(mode=="1s")*2+(case=="atomfix"),row,"witnesses-final")
for index,mode in [(125,"2s"),(145,"1s")]:
 wrapper=r.DATA/("watchlive-recheck-"+mode)
 wrapper.write_text("#!/bin/bash\nexec taskset -c 88-95 "+str(r.POST)+" \"$@\" --thread-mode "+mode+" --databases 1 --shards 16 --key-lb 0 --client-lb 0 --flip-auto 0 --read-local "+("1" if mode=="1s" else "0")+(" --ratio 6:2" if mode=="2s" else "")+"\n")
 wrapper.chmod(0o755);row=r.transform(rows[index]);row["command"][4]="27890";row["command"][5]="88-95";row["command"][7]=str(wrapper)
 r.run(index,row,"fresh-watch-final")
