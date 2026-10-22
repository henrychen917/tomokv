#!/usr/bin/env python3
"""Correctness-only lane driver. Every gate job uses gate.sh's own selector."""
import argparse, json, os, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/compat3"
BUILD=ROOT/"build/compat3"
ENV={**os.environ,"REDIS74_ROOT":"/home/user/Projects/redis",
     "GATE_DIFFER_ORACLE_BIN":"/home/user/Projects/redis74/src/redis-server",
     "GATE_DIFFER_REDIS_CLI":"/home/user/Projects/redis74/src/redis-cli",
     "GATE_DIFFER_ORACLE_CORES":"104", "GATE_GLOBCASE_ORACLE_CORES":"104",
     "GATE_TEST_PORT":"25899", "GATE_DIFFER_HISTORY":str(BUILD/"differ-history")}
RESULTS=[]

def execute(name,argv,extra=None):
    name=ARGS.prefix+name
    if extra and "GATE_LEDGER" in extra:
        extra={**extra,"GATE_LEDGER":str(DOC/(name+".ledger"))}
    with (DOC/(name+".log")).open("w") as log:
        rc=subprocess.run(["taskset","-c","96-111",*map(str,argv)],cwd=ROOT,
            env={**ENV,**(extra or {})},stdout=log,stderr=subprocess.STDOUT).returncode
    RESULTS.append(dict(name=name,argv=list(map(str,argv)),extra=extra,returncode=rc))
    (DOC/(name+".rc")).write_text(str(rc)+"\n")
    (DOC/(ARGS.prefix+ARGS.phase+"-results.json")).write_text(json.dumps(RESULTS,indent=2)+"\n")
    print(name,rc,flush=True)
    return rc

def gate(name,jobs,binary):
    return execute(name,["tests/gate.sh","iteration","--server-cores","96-104",
        "--load-cores","105-111","--load-smt","","--ports","25800-25821",
        "--candidate-binary",binary],dict(GATE_ONLY_JOBS=jobs,GATE_LEDGER=str(DOC/(name+".ledger"))))

p=argparse.ArgumentParser();p.add_argument("phase",choices=("units","post","pre","differ","selftest","flags"))
p.add_argument("--prefix",default="",help="Keep continuation receipts separate from earlier attempts")
p.add_argument("--engine",choices=("uring","epoll"),action="append",help="Differential engines; default both")
ARGS=p.parse_args()
if ARGS.phase=="units":
    body=(ROOT/"tests/gate.sh").read_text().split("job_production_units(){",1)[1].split("\n}",1)[0]
    targets=re.findall(r"build/[\w-]+",body.split('>"$TMPDIR/build.log"',1)[0])
    assert len(targets)==len(set(targets))
    (DOC/"unit-targets.json").write_text(json.dumps(targets,indent=2)+"\n")
    execute("production-build",["make","-k","-j16","all",*targets,"mdbqsbr-live-arms"])
    for target in ["all",*targets]:
        execute("fresh-"+target.replace("/","-"),["make","-q",target])
    execute("fresh-mdbqsbr-phony",["make","-q","mdbqsbr-live-arms"])
    for name,flags in [("park","-DTOMO_MDBQSBR_LIVE_PARK"),("no-wake","-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE")]:
        execute("fresh-mdbqsbr-"+name,["make","-q","BUILD_ROOT=build/mdbqsbr2-"+name,
            "CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread "+flags,"all"])
elif ARGS.phase=="pre":
    evict=" ".join(f"evict-{section}-{mode}-{atomic}" for section in ("lruclock", "lfu")
                   for mode in ("split", "armed") for atomic in (0, 1))
    gate("POST-eviction",evict,ROOT/"build/tomokv")
    gate("PRE-complete","compat3",BUILD/"PRE/tomokv")
elif ARGS.phase=="post":
    jobs="feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 auth notify notify_order notify_aof scriptfix script_bounds debug-0 debug-1 aclfix acl_recheck clientfix perfio_stream netio-1s netio-2s netcmd_units globcase aof-epoll aof-uring atomic_units atomic_batteries"
    # Include every multidb job using the grep-matched historical multidb battery.
    jobs += " "+" ".join(f"multidb-{m}-{r}-{a}" for m in ("1s","2s") for r in (0,1) for a in (0,1))
    gate("POST-complete",jobs,ROOT/"build/tomokv")
    wrapper=BUILD/"fused-auth-server"
    wrapper.write_text("#!/usr/bin/python3\nimport os,sys\na=sys.argv[1:]\nout=[]\nwhile a:\n v=a.pop(0)\n if v=='--ratio': a.pop(0)\n elif not v.startswith('--ratio='): out.append(v)\nos.execv("+repr(str(ROOT/"build/tomokv"))+",["+repr(str(ROOT/"build/tomokv"))+",'--thread-mode','1s','--read-local','0',*out])\n")
    wrapper.chmod(0o755)
    gate("POST-auth-fused","auth",wrapper)
elif ARGS.phase=="differ":
    for engine in ARGS.engine or ("uring","epoll"):
        wrapper=BUILD/(engine+"-server")
        wrapper.write_text('#!/bin/bash\nexec '+str(ROOT/"build/tomokv")+' --net-io '+engine+' "$@"\n')
        wrapper.chmod(0o755)
        gate("differ-"+engine,"differ-split differ-armed",wrapper)
elif ARGS.phase=="flags":
    execute("flags-audit",["python3",DOC/"flags_audit.py"])
    for name,binary in (("POST-final",ROOT/"build/tomokv"),
                        ("PRE-final-control",BUILD/"PRE/tomokv"),
                        ("PAD-A-final",BUILD/"PAD-A/tomokv")):
        gate(name,"compat3",binary)
else:
    tmp=BUILD/"selftest-tmp";tmp.mkdir(exist_ok=True)
    execute("gates-test-final",["python3","tests/gates_test.py"],dict(TMPDIR=str(tmp)))
