#!/usr/bin/env python3
"""Preserve completed gate job evidence; never launches a server or measurement."""
import gzip, hashlib, json, re, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/compat3"
OUT=DOC/"receipts"; OUT.mkdir(exist_ok=True)
index=[]
for log in sorted(DOC.glob("*.log")):
    found=re.search(r"artifacts: (.+/build/gate-run\.\w+)",log.read_text(errors="replace"))
    if not found: continue
    run=Path(found[1])
    if not (run/"phases.tsv").exists(): continue
    phases=(run/"phases.tsv").read_text()
    if not any(x.startswith("end\t") for x in phases.splitlines()):
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
            if p.stat().st_size>32*1024*1024: continue
            selected.append(str(p.relative_to(run)))
            archive.add(p,arcname=str(p.relative_to(run)),recursive=False)
    index.append(dict(log=str(log.relative_to(DOC)),run=str(run),archive=str(dest.relative_to(DOC)),
                      sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),files=len(selected),jobs=jobs))
    print(log.stem,len(jobs),len(selected),dest.stat().st_size)
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
        failures.append(dict(log=log.name,source=str(source),archive=str(dest.relative_to(DOC)),sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
(DOC/"scheduler-failure-receipts.json").write_text(json.dumps(failures,indent=2)+"\n")
