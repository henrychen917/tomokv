#!/usr/bin/env python3
"""Preserve completed gate job evidence; never launches a server or measurement."""
import argparse, gzip, hashlib, json, re, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/compat3"
OUT=DOC/"receipts"; OUT.mkdir(exist_ok=True)
p=argparse.ArgumentParser()
p.add_argument("--interrupted",action="append",default=[],help="Also retain an explicitly interrupted gate log")
args=p.parse_args()
large=[]

def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source,"sha256").hexdigest()

def size_guard(dest):
    if dest.stat().st_size<=1_000_000:return str(dest.relative_to(DOC))
    retained=ROOT/"build/compat3/large-receipts"/dest.name
    retained.parent.mkdir(parents=True,exist_ok=True)
    large.append(dict(source=str(dest.relative_to(ROOT)),retained=str(retained.relative_to(ROOT)),
                      bytes=dest.stat().st_size,sha256=digest(dest),reason="archive exceeds 1 MB"))
    dest.replace(retained)
    return None

index=[]
for log in sorted(DOC.glob("*.log")):
    found=re.search(r"artifacts: (.+/build/gate-run\.\w+)",log.read_text(errors="replace"))
    if not found: continue
    run=Path(found[1])
    if not (run/"phases.tsv").exists(): continue
    phases=(run/"phases.tsv").read_text()
    complete=any(x.startswith("end\t") for x in phases.splitlines())
    if not complete and log.name not in args.interrupted:
        print("INCOMPLETE",log.name,run); continue
    jobs=[]
    for job in sorted((run/"jobs").iterdir()):
        if not job.is_dir(): continue
        done=(job/"done").read_text().strip() if (job/"done").exists() else None
        ledger=(job/"ledger").read_text() if (job/"ledger").exists() else ""
        output=(job/"output.log").read_text(errors="replace") if (job/"output.log").exists() else ""
        jobs.append(dict(job=job.name,done=done,ledger=ledger,
                         failures=[x for x in output.splitlines() if " FAIL" in x]))
    dest=OUT/(log.stem+".tar.gz")
    selected=[]
    with tarfile.open(dest,"w:gz",compresslevel=9) as archive:
        for p in sorted(run.rglob("*")):
            if not p.is_file() or p.is_symlink(): continue
            keep=(p.suffix in (".txt",".log",".json",".tsv",".sh",".rc",".timings") or
                  p.name in ("done","ledger","plan.sh","fixture-affinity") or
                  p.name.startswith("gate-srv"))
            if not keep: continue
            # Snapshots, AOF payloads, private TLS keys and compiled executables are excluded.
            if p.stat().st_size>1_000_000:
                large.append(dict(source=str(p.relative_to(ROOT)),bytes=p.stat().st_size,
                                  sha256=digest(p),reason="individual receipt exceeds 1 MB"))
                continue
            with p.open("rb") as source:
                if source.read(4)==b"\x7fELF":continue
            selected.append(str(p.relative_to(run)))
            archive.add(p,arcname=str(p.relative_to(run)),recursive=False)
    sha=digest(dest);size=dest.stat().st_size
    archive=size_guard(dest)
    index.append(dict(log=str(log.relative_to(DOC)),run=str(run),archive=archive,
                      sha256=sha,bytes=size,complete=complete,files=len(selected),jobs=jobs))
    print(log.stem,len(jobs),len(selected),size,"complete" if complete else "INTERRUPTED")
(DOC/"gate-receipts.json").write_text(json.dumps(index,indent=2)+"\n")

# Keep the original self-test timeout artifacts as evidence too.
failures=[]
for log in sorted(DOC.glob("gates-test*.log")):
    for name in sorted(set(re.findall(r"Scheduler failure artifacts: (.+/build/scheduler-failure-[^\s]+)",log.read_text(errors="replace")))):
        source=Path(name)
        if not source.is_dir():continue
        dest=OUT/(source.name+".tar.gz")
        with tarfile.open(dest,"w:gz",compresslevel=9) as archive:
            archive.add(source,arcname=source.name)
        sha=digest(dest)
        failures.append(dict(log=log.name,source=str(source),archive=size_guard(dest),sha256=sha))
(DOC/"scheduler-failure-receipts.json").write_text(json.dumps(failures,indent=2)+"\n")
(DOC/"large-receipts.json").write_text(json.dumps(large,indent=2)+"\n")
