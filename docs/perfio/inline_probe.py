#!/usr/bin/env python3
"""Compile-only check of the two unrelated hot-body drifts; no measurements."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,re,shlex,subprocess,sys
sys.path.insert(0,"tools")
import lbstall_artifacts as audit
root=Path("build/perfio/inline-probe")
root.mkdir(parents=True,exist_ok=True)

def check(item):
    obj,budget=item
    lines=Path("docs/perfio/post-build.log").read_text().splitlines()
    cmd=next(shlex.split(line) for line in lines if line.startswith("g++ ") and line.endswith(" -o build/"+obj))
    output=root/(obj.replace("/","_")+".o")
    cmd=["large-unit-insns="+str(budget) if x.startswith("large-unit-insns=") else x for x in cmd]
    cmd[cmd.index("-o")+1]=str(output)
    cmd += ["-fdump-ipa-inline", "-dumpbase", str(output.with_suffix(""))]
    subprocess.run(cmd,check=True)
    dump=next(root.glob(output.stem+"*.inline"))
    unit=next(int(m[1]) for line in dump.open() if (m:=re.search(r"Starting with size (\d+)",line)))
    dump.unlink()
    a,b=audit.Elf(Path("build/perfio/pre")/obj),audit.Elf(output)
    af,bf=a.functions(),b.functions()
    names=list(af)
    readable=subprocess.check_output(["c++filt"],input=("\n".join(names)+"\n").encode()).decode().splitlines()
    changes=[]
    for n,d in zip(names,readable):
        if audit.HOT.search(d) and (n not in bf or a.canonical(af[n])!=b.canonical(bf[n])):
            changes.append(d)
    result=dict(object=obj,budget=budget,unit=unit,hot_changes=changes,output=str(output))
    print(json.dumps(result),flush=True)
    return result
with ThreadPoolExecutor(2) as pool:
    rows=list(pool.map(check,[("db0/src/core/genthread.o",129652),("src/core/rl2s.o",162312)]))
Path("docs/perfio/inline-probe.json").write_text(json.dumps(rows,indent=2)+"\n")
