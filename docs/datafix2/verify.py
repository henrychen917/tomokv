#!/usr/bin/env python3
"""Correctness-only lane driver. Every gate job uses gate.sh's own selector."""
import argparse, json, os, re, shlex, subprocess, socket, time, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/"docs/datafix2"
BUILD=ROOT/"build/datafix2"
ENV={**os.environ,"REDIS74_ROOT":"/home/user/Projects/redis",
     "GATE_DIFFER_ORACLE_BIN":"/home/user/Projects/redis74/src/redis-server",
     "GATE_DIFFER_REDIS_CLI":"/home/user/Projects/redis74/src/redis-cli",
     "GATE_DIFFER_ORACLE_CORES":"104", "GATE_GLOBCASE_ORACLE_CORES":"104",
     "GATE_TEST_PORT":"33899", "GATE_DIFFER_HISTORY":str(BUILD/"differ-history"),
     "PYTHONPATH":str(DOC/"port_guard")+os.pathsep+os.environ.get("PYTHONPATH",""),
     "DATAFIX2_PORT_RECEIPT":str(DOC/"fixture-ports.jsonl")}
RESULTS=[]
BUILD.mkdir(exist_ok=True)
# Keep assigned listener ports out of Linux's ephemeral allocator. These sockets
# do not listen; SO_REUSEADDR allows the real gate-owned servers to bind them.
# No kernel settings or files outside this worktree are changed.
RESERVED=[]
def reserve_ports():
    low,high=map(int,ARGS.ports.split('-'))
    assert 33800<=low<high<=33889
    pending=set(range(low,high+1)); held=set();until=time.monotonic()+70
    while True:
        for port in sorted(pending):
            sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:sock.bind(('0.0.0.0',port))
            except OSError as error:
                sock.close()
                if error.errno != 98: raise
                continue
            RESERVED.append(sock);held.add(port);pending.remove(port)
        for base in range(low,high-1):
            if {base,base+1,base+2} <= held:
                ARGS.ports=f'{base}-{base+2}'
                print('reserved gate ports',ARGS.ports,flush=True)
                return
        if time.monotonic() >= until: raise RuntimeError(('no free three-port slot',sorted(pending)))
        time.sleep(.02)


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
    if argv and str(argv[0]).endswith('gate.sh'):
        output=(DOC/(name+'.log')).read_text()
        paths=re.findall(r'(?:/[^\s:]+/)?build/gate-run\.[A-Za-z0-9]+',output)
        if paths:
            run=Path(paths[0]);run=run if run.is_absolute() else ROOT/run
            if run.exists():
                with tarfile.open(DOC/(name+'-evidence.tar.gz'),'w:gz') as archive:
                    for f in run.rglob('*'):
                        if f.is_file() and f.suffix not in ('.rdb','.tomo','.aof') and f.stat().st_size<20_000_000:
                            archive.add(f,arcname=str(f.relative_to(run)))
    print(name,rc,flush=True)
    return rc

def gate(name,jobs,binary):
    return execute(name,["tests/gate.sh","iteration","--server-cores","96-104",
        "--load-cores","105-111","--load-smt","","--ports",ARGS.ports,
        "--candidate-binary",binary],dict(GATE_ONLY_JOBS=jobs,GATE_LEDGER=str(DOC/(name+".ledger"))))

p=argparse.ArgumentParser()
p.add_argument('phase',choices=('gate','differ','selftest'))
p.add_argument('--prefix',required=True)
p.add_argument('--ports',default='33800-33821')
p.add_argument('--binary',type=Path,default=ROOT/'build/tomokv')
p.add_argument('--jobs',default='')
p.add_argument('--source-root',type=Path,help='Historical sources with the current gate/tests; receipts stay in this worktree.')
p.add_argument('--engine',choices=('epoll','uring'),action='append')
ARGS=p.parse_args()
if ARGS.source_root: ROOT=ARGS.source_root.resolve()
reserve_ports()
if ARGS.phase=='gate':
    assert ARGS.jobs
    gate('gate',ARGS.jobs,ARGS.binary.resolve())
elif ARGS.phase=='differ':
    for engine in ARGS.engine or ('epoll','uring'):
        wrapper=BUILD/(ARGS.prefix+engine+'-server')
        wrapper.write_text('#!/bin/bash\nexec '+shlex.quote(str(ARGS.binary.resolve()))+' --net-io '+engine+' "$@"\n')
        wrapper.chmod(0o755)
        gate('differ-'+engine,'differ-split differ-armed',wrapper)
else:
    tmp=BUILD/'selftest-tmp';tmp.mkdir(exist_ok=True)
    execute('gates-test',["python3","tests/gates_test.py"],dict(TMPDIR=str(tmp)))
raise SystemExit(1 if any(result['returncode'] for result in RESULTS) else 0)
