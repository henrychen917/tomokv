#!/usr/bin/env python3
"""All requested gate families, then explicit epoll coverage for default-engine jobs."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
assert os.sched_getaffinity(0)<=set(range(64,112))
cohorts=[
 ("final-all", "differ-split differ-armed flip_unit flipfix_units climonfix persistfix_units wb_rule_units wbland_units wb_policy splitlocal_units netcmd_units iofix-hz iofix-sleep iofix-signal netio-1s netio-2s netfix_query_stats netfix_unix netfix_config netfix_tls netfix_idle_buffers snapshot-epoll snapshot-uring aof-epoll aof-uring notify_aof flip fliplisten flip_saturated flipctl aof_frame aoforder tls release_batteries asan_batteries replyoff zc", []),
 ("final-epoll", "climonfix flip flipctl flip_saturated notify_aof aof_frame aoforder tls replyoff netio-1s netio-2s differ-split differ-armed", ["--engine", "epoll"]),
]
results=[]
for name,jobs,extra in cohorts:
 command=["python3",str(ROOT/"docs/wave5c/verify.py"),name,jobs,"--server-cores","64-95","--load-cores","96-111","--ports","26800-26889","--asan",str(ROOT/"build/wave5c/arms/fixed-asan"),*extra]
 with (ROOT/"build/wave5c"/(name+".log")).open("w") as log:
  rc=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
 results.append(dict(name=name,returncode=rc,command=command))
 (ROOT/"docs/wave5c/final-cohorts.json").write_text(json.dumps(results,indent=2)+"\n")
 print(name,rc,flush=True)
raise SystemExit(any(r["returncode"] for r in results))
