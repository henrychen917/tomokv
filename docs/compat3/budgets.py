#!/usr/bin/env python3
"""Compile-only IPA re-derivation; exact canonical body scores, no rate claims."""
from concurrent.futures import ThreadPoolExecutor
import json, re, shlex, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import ccfix_audit
from lbstall_artifacts import Elf, HOT
OUT=ROOT/"build/compat3/budgets"; OUT.mkdir(parents=True,exist_ok=True)
DOC=ROOT/"docs/compat3/budgets"; DOC.mkdir(exist_ok=True)
UNITS=[prefix+unit for prefix in ("","db0/") for unit in ("src/main.o","src/core/genthread.o","src/core/rl2s.o","src/core/reorder.o","src/cmd/xshard.o")]
LOG={"pre":ROOT/"docs/compat3/build-pre.log", "post":ROOT/"docs/compat3/build-post-initial.log"}
SOURCES={"pre":ROOT/"build/compat3/PRE-source", "post":ROOT}


def command(arm,unit):
    for line in LOG[arm].read_text().splitlines():
        if line.startswith("g++ ") and " -c " in line:
            a=shlex.split(line)
            if a[a.index("-o")+1].endswith("/"+unit):return a
    raise ValueError((arm,unit))


def compile_one(job):
    arm,unit,budget=job
    a=command(arm,unit)
    old=next(int(x.split("=")[1]) for x in a if x.startswith("large-unit-insns="))
    budget=old if budget is None else budget
    label=f"{unit.replace(chr(47),chr(95))}-{arm}-{budget}"
    receipt=OUT/(label+".json")
    if receipt.exists():return json.loads(receipt.read_text())
    obj=OUT/(label+".o")
    a=["large-unit-insns="+str(budget) if x.startswith("large-unit-insns=") else x for x in a]
    a[a.index("-o")+1]=str(obj)
    a += ["-fdump-ipa-inline", "-dumpbase", str(OUT/label)]
    with (OUT/(label+".log")).open("w") as log:
        subprocess.run(a,cwd=SOURCES[arm],stdout=log,stderr=subprocess.STDOUT,check=True)
    dump,=OUT.glob(label+"*.inline")
    with dump.open() as f:
        size=next(int(m[1]) for line in f if (m:=re.search(r"Starting with size (\d+)",line)))
    dump.unlink()
    row=dict(arm=arm,unit=unit,budget=budget,start_size=size,object=str(obj),command=a)
    receipt.write_text(json.dumps(row,indent=2)+"\n")
    print("compiled",arm,unit,budget,size,flush=True)
    return row


def score(row):
    receipt=Path(row["object"]+".score.json")
    if receipt.exists():return json.loads(receipt.read_text())
    pre=Elf(ROOT/"build/compat3/PRE"/row["unit"]); post=Elf(row["object"])
    a,b=pre.functions(),post.functions(); names=sorted(a.keys()|b.keys())
    labels=subprocess.check_output(["c++filt"],input="\n".join(names)+"\n",text=True).splitlines()
    changed=[]
    for symbol,name in zip(names,labels):
        if symbol in a and symbol in b and pre.canonical(a[symbol])==post.canonical(b[symbol]):continue
        direct=any(s in name for s in ("PubSub","pubsub_","FunctionMemoryScope","execute_atomic_apply","xshard_execute("))
        hot=bool(HOT.search(name)) or bool(re.search(r"ExLoopT<.*>::run\(",name))
        changed.append(dict(symbol=symbol,name=name,direct=direct,hot=hot,pre=a.get(symbol,{}).get("size",0),post=b.get(symbol,{}).get("size",0)))
    result=dict(row,score=[sum(r["hot"] and not r["direct"] for r in changed),sum(not r["direct"] for r in changed),len(changed)],changed=changed)
    receipt.write_text(json.dumps(result,indent=2)+"\n")
    print("scored",row["unit"],row["budget"],result["score"],flush=True)
    return result


def main():
    with ThreadPoolExecutor(16) as pool:
        base=list(pool.map(compile_one,[(arm,u,None) for arm in ("pre","post") for u in UNITS]))
    (DOC/"initial.json").write_text(json.dumps(base,indent=2)+"\n")
    by={(r["arm"],r["unit"]):r for r in base}; jobs=[]
    for u in UNITS:
        pre,post=by["pre",u],by["post",u]
        center=post["budget"]+post["start_size"]-pre["start_size"]
        for b in sorted({post["budget"],center-4,center,center+4}):jobs.append(("post",u,b))
    with ThreadPoolExecutor(16) as pool: trials=list(pool.map(compile_one,jobs))
    with ThreadPoolExecutor(4) as pool: scores=list(pool.map(score,trials))
    (DOC/"trials.json").write_text(json.dumps(scores,indent=2)+"\n")
    selected=[]
    for u in UNITS:
        old=by["post",u]["budget"]
        opts=[r for r in scores if r["unit"]==u]
        best=min(opts,key=lambda r:(r["score"],r["budget"]!=old,abs(r["budget"]-old)))
        selected.append(dict(unit=u,old=old,budget=best["budget"],score=best["score"],object=best["object"]))
    (DOC/"selected.json").write_text(json.dumps(selected,indent=2)+"\n")
    print(json.dumps(selected,indent=2))


if __name__=="__main__":main()
