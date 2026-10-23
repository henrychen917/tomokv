#!/usr/bin/env python3
"""Inventory no-writes/allow-stale command distinctions; verify admitted growth."""
import json, subprocess, sys
from pathlib import Path
from run_grammar import server, ROOT
sys.path.insert(0,str(ROOT/"tests"))
from _lib import Conn, RespError
from compat3_lib import wire
DOC=ROOT/"docs/compat3"
COMMANDS=[("GET","k"),("SET","k","after"),("DEL","k"),("PUBLISH","k","message"),
          ("SPUBLISH","k","message"),("PFCOUNT","k"),("PING",)]
FLAGS=[[],["no-writes"],["allow-stale"],["no-writes","allow-stale"],["no-writes","allow-oom"]]

def probe(port):
    c=Conn("127.0.0.1",port,timeout=15,buffering=0);out=[]
    try:
        assert c.cmd("CONFIG","SET","maxmemory",0)==b"OK"
        assert c.cmd("FUNCTION","FLUSH")==b"OK"
        for flags in FLAGS:
            source=("#!lua name=flag_audit\nredis.register_function{function_name='flag_probe',flags={"+
                    ",".join(repr(f) for f in flags)+"},callback=function(keys,args) local r=redis.pcall(unpack(args)); "+
                    "if type(r)=='table' and r.err then return r.err else return r end end}\n")
            assert c.cmd("FUNCTION","LOAD","REPLACE",source)==b"flag_audit"
            for cmd in COMMANDS:
                assert c.cmd("FLUSHALL")==b"OK"
                if cmd[0]=="PFCOUNT": assert c.cmd("PFADD","k","element")==1
                else: assert c.cmd("SET","k","before")==b"OK"
                out.append(dict(flags=flags,command=cmd,reply=wire(c.cmd("FCALL","flag_probe",1,"k",*cmd))))
        assert c.cmd("FLUSHALL")==b"OK"
        source="#!lua name=growth\nredis.register_function('grow', function(keys,args) return redis.call('SET',keys[1],string.rep('x',33554432)) end)\n"
        assert c.cmd("FUNCTION","LOAD",source)==b"growth"
        assert c.cmd("SET","k","before")==b"OK"
        assert c.cmd("CONFIG","SET","maxmemory-policy","noeviction")==b"OK"
        assert c.cmd("CONFIG","SET","maxmemory",16777216)==b"OK"
        growth=c.cmd("FCALL","grow",1,"k")
        length=c.cmd("STRLEN","k")
        capped=c.cmd("SET","k","ordinary")
        assert growth==b"OK" and length==33554432 and isinstance(capped,RespError), (growth,length,capped)
        out.append(dict(admitted_growth=dict(reply=wire(growth),length=length,cap_restored=wire(capped))))
        return out
    finally:
        c.cmd("CONFIG","SET","maxmemory",0)
        c.cmd("FLUSHALL")
        c.close()

if __name__=="__main__":
    if len(sys.argv)>1:
        Path(sys.argv[2]).write_text(json.dumps(probe(int(sys.argv[1])),indent=2)+"\n")
    else:
        oracle=DOC/"flags-audit-oracle.json"
        with server(Path("/home/user/Projects/redis74/src/redis-server"),25891,"104",[],"flags-audit-oracle"):
            subprocess.run(["taskset","-c","105-111",sys.executable,__file__,"25891",str(oracle)],check=True)
        base=json.loads(oracle.read_text())
        differences=[]
        for mode in ("1s","2s"):
            extra=["--shards","16","--thread-mode",mode,"--atomic","0","--net-io","uring","--databases","1"]
            if mode=="2s":extra += ["--ratio","6:2"]
            path=DOC/("flags-audit-"+mode+".json")
            with server(ROOT/"build/tomokv",25890,"96-103",extra,"flags-audit-"+mode):
                subprocess.run(["taskset","-c","105-111",sys.executable,__file__,"25890",str(path)],check=True)
            target=json.loads(path.read_text());assert len(base)==len(target)
            for a,b in zip(base,target):
                if a!=b:differences.append(dict(mode=mode,oracle=a,target=b))
        (DOC/"flags-audit-differences.json").write_text(json.dumps(differences,indent=2)+"\n")
        print("differences",len(differences),"across both modes; growth/cap restoration assertions passed")
