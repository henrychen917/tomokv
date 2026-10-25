import json, os, pathlib, subprocess, sys, tempfile, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))
from _lib import Conn, RespError, info
from compat3_lib import wire
root = pathlib.Path(__file__).resolve().parents[2]

def probe(c):
    rows = {}
    for cmd in [("APPEND","k",""),("APPEND","k","b"),("SETRANGE","k",0,"a"),
                ("SETRANGE","k",0,""),("SETBIT","k",0,0),("SETBIT","k",0,1),
                ("BITFIELD","k","GET","u8",0),("BITFIELD","k","SET","u8",0,97),
                ("BITFIELD","k","OVERFLOW","FAIL","INCRBY","u8",0,999)]:
        c.cmd("DEL", "k"); c.cmd("SET", "k", "a")
        rows[str(cmd)] = [c.cmd(*cmd), c.cmd("OBJECT", "ENCODING", "k")]
    c.cmd("FLUSHALL")
    for setup, cmd in [([], ("DEL","missing")), ([("SET","k","v")],("SET","k","w","NX")),
                       ([("SADD","k","a")],("SREM","k","none")),
                       ([("SET","k","a")],("SETBIT","k",0,0)),
                       ([("PFADD","k","a"),("PFCOUNT","k")],("PFCOUNT","k"))]:
        c.cmd("FLUSHALL")
        for s in setup: c.cmd(*s)
        w=Conn(c.host,c.port,buffering=0)
        w.cmd("WATCH", "k", "missing")
        reply=c.cmd(*cmd);w.cmd("MULTI");w.cmd("PING")
        rows["WATCH "+str(cmd)] = [reply,w.cmd("EXEC")];w.close()
    c.cmd("FLUSHALL");c.cmd("CONFIG","RESETSTAT");c.cmd("HSET","h","a","1","b","2")
    rows["immediate"] = c.cmd("HPEXPIREAT","h",1,"FIELDS",1,"a")
    rows["INFO"] = {k:v for k,v in info(c,"stats").items() if k in ("expired_subkeys","expired_hash_fields","hash_field_expires")}
    for policy in ("noeviction","allkeys-random","volatile-random","volatile-ttl","allkeys-lru","volatile-lru","allkeys-lfu","volatile-lfu"):
        c.cmd("CONFIG","SET","maxmemory",1<<30); c.cmd("CONFIG","SET","maxmemory-policy",policy)
        c.cmd("DEL","k");c.cmd("SET","k","value");time.sleep(1.1)
        rows["IDLETIME "+policy]=c.cmd("OBJECT","IDLETIME","k")
    return rows

for name, binary, mode in [("oracle", "/home/user/Projects/redis74/src/redis-server", None),
                           ("PRE-1s",str(root/"build/tomokv-pre"),"1s"),
                           ("PRE-2s",str(root/"build/tomokv-pre"),"2s")]:
    directory=tempfile.mkdtemp(dir=root/"build",prefix="datafix2-repro-")
    args=[binary,"--port","33890","--bind","127.0.0.1","--dir",directory,"--save","","--appendonly","no","--enable-debug-command","yes"]
    if mode: args += ["--thread-mode",mode,"--shards","16","--atomic","0","--read-local","0","--net-io","epoll"]
    if mode == "2s": args += ["--ratio", "6:2"]
    with open(directory+"/server.log","w") as log:
        proc=subprocess.Popen(["taskset","-c","96-103",*args],stdout=log,stderr=subprocess.STDOUT)
        try:
            for i in range(100):
                try: c=Conn("127.0.0.1",33890,buffering=0);break
                except OSError: time.sleep(.05)
            else: raise RuntimeError("boot failed")
            print(json.dumps({"arm":name,"argv":args,"cpus":"96-103","rows":wire(probe(c))}),flush=True);c.close()
        finally:
            proc.terminate();proc.wait(timeout=10)
