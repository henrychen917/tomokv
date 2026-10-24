#!/usr/bin/env python3
"""CD4.9: table of every registered Redis write, with per-key WATCH outcomes."""
import json
import time
from compat3_lib import equal, run, wire
from _lib import Conn, RespError, cross_owner_pair

K, D = "k", "dst"
DATABASES = 1
TARGET = None
REGISTERED = set()

def prepare(args):
    global K, D, DATABASES, TARGET, REGISTERED
    TARGET = (args.host, args.port)
    c = Conn(args.host, args.port, buffering=0)
    K, D, a, b = cross_owner_pair(c, "datafix2:watch")
    assert a != b
    REGISTERED = {row[0].decode().upper() for row in c.cmd("COMMAND") if b"write" in row[2]} | {"PFCOUNT", "PFDEBUG"}
    DATABASES = int(c.cmd("CONFIG", "GET", "databases")[1])
    print("CROSS", K, D, a, b, flush=True)
    c.close()


def table(c):
    rows = []
    def add(label, cmd, seed=(), watch=(K,), db=0):
        rows.append((label, cmd, seed, watch, db))
    string = [("SET", K, "a")]
    number = [("SET", K, "1")]
    seq = [("RPUSH", K, "1", "2")]
    aset = [("SADD", K, "a")]
    zset = [("ZADD", K, 1, "a")]
    ahash = [("HSET", K, "a", "1")]
    stream = [("XADD", K, "1-0", "f", "v")]
    for cmd in [("SET", K, "a"), ("SET", K, "b", "NX"), ("SET", K, "b", "XX"),
                ("SETNX", K, "a"), ("SETEX", K, 60, "a"), ("PSETEX", K, 60000, "a"),
                ("APPEND", K, ""), ("SETRANGE", K, 0, ""), ("SETRANGE", K, 0, "a"),
                ("SETBIT", K, 0, 0), ("SETBIT", K, 0, 1),
                ("BITFIELD", K, "GET", "u8", 0), ("BITFIELD", K, "SET", "u8", 0, 97),
                ("BITFIELD", K, "SET", "u8", 0, 98),
                ("BITFIELD", K, "OVERFLOW", "FAIL", "INCRBY", "u8", 0, 999),
                ("GETSET", K, "a"), ("GETEX", K), ("GETEX", K, "PERSIST"),
                ("GETEX", K, "EX", 60), ("GETDEL", K), ("PERSIST", K)]:
        for present in (False, True): add(str((cmd, present)), cmd, string if present else ())
    for name in ("INCR", "DECR", "INCRBY", "DECRBY", "INCRBYFLOAT"):
        cmd = (name, K) + ((0,) if name not in ("INCR", "DECR") else ())
        add(name, cmd, number);add(name+"-error",cmd,string)
    for name in ("EXPIRE", "PEXPIRE", "EXPIREAT", "PEXPIREAT"):
        value = 60 if name == "EXPIRE" else 60000 if name == "PEXPIRE" else 2000000000 if name == "EXPIREAT" else 2000000000000
        for condition in ((), ("XX",), ("NX",)):
            for present in (False, True): add(str((name,condition,present)), (name,K,value,*condition), string if present else ())
    for cmd in [("PERSIST",K),("GETEX",K,"PERSIST"),("PEXPIRE",K,60000,"NX"),
                ("PEXPIRE",K,60000,"XX"),("PEXPIRE",K,1),("PEXPIREAT",K,1)]:
        add("ttl-"+str(cmd),cmd,[("SET",K,"a","PX",120000)])
    for name in ("DEL", "UNLINK"):
        add(name, (name,K,D), string, (K,D));add(name+"-missing",(name,K,D),(),(K,D))
    for name in ("MSET", "MSETNX"):
        for present in (False, True): add(str((name,present)),(name,K,"a",D,"b"),string if present else (),(K,D))
    for name in ("RENAME", "RENAMENX", "COPY"):
        for present in (False,True):
            add(str((name,present)),(name,K,D),string+([( "SET",D,"a")] if present else []),(K,D))
        add(name+"-missing",(name,K,D),(),(K,D));add(name+"-same",(name,K,K),string)
    for name in ("LPUSH","RPUSH","LPUSHX","RPUSHX"):
        for present in (False,True): add(str((name,present)),(name,K,"a"),seq if present else ())
    for name in ("LPOP","RPOP"):
        for count in (0,1):
            for present in (False,True): add(str((name,count,present)),(name,K,count),seq if present else ())
    for cmd in [("LSET",K,0,"1"),("LINSERT",K,"BEFORE","none","v"),("LINSERT",K,"AFTER","1","v"),
                ("LREM",K,0,"none"),("LREM",K,0,"1"),("LTRIM",K,0,-1), ("LTRIM",K,1,-1)]:
        for present in (False,True): add(str((cmd,present)),cmd,seq if present else ())
    for name,tail in [("BLPOP",(K,.001)),("BRPOP",(K,.001)),("BLMPOP",(.001,1,K,"LEFT")),
                      ("LMPOP",(1,K,"LEFT")),("LMOVE",(K,D,"LEFT","RIGHT")),
                      ("BLMOVE",(K,D,"LEFT","RIGHT",.001)),("RPOPLPUSH",(K,D)),("BRPOPLPUSH",(K,D,.001))]:
        for present in (False,True): add(str((name,present)),(name,*tail),seq if present else (),(K,D))
    for name,arg in [("SADD","a"),("SADD","b"),("SREM","none"),("SREM","a")]:
        for present in (False,True): add(str((name,arg,present)),(name,K,arg),aset if present else ())
    for present in (False,True):
        add(str(("SPOP",present)),("SPOP",K,1),aset if present else ())
        add(str(("SMOVE",present)),("SMOVE",K,D,"a"),aset+([("SADD",D,"a")] if present else []),(K,D))
    for name in ("SINTERSTORE","SUNIONSTORE","SDIFFSTORE"):
        for present in (False,True): add(str((name,present)),(name,D,K),aset if present else (),(K,D))
    for cmd in [("ZADD",K,1,"a"),("ZADD",K,2,"a"),("ZADD",K,"NX",2,"a"),
                ("ZINCRBY",K,0,"a"),("ZREM",K,"none"),("ZREM",K,"a"),
                ("ZREMRANGEBYRANK",K,3,4),("ZREMRANGEBYRANK",K,0,-1),
                ("ZREMRANGEBYSCORE",K,3,4),("ZREMRANGEBYSCORE",K,0,2),
                ("ZREMRANGEBYLEX",K,"[x","[z"),("ZREMRANGEBYLEX",K,"-","+")]:
        for present in (False,True): add(str((cmd,present)),cmd,zset if present else ())
    for name,tail in [("ZPOPMIN",(K,1)),("ZPOPMAX",(K,1)),("BZPOPMIN",(K,.001)),("BZPOPMAX",(K,.001)),
                      ("ZMPOP",(1,K,"MIN")),("BZMPOP",(.001,1,K,"MIN"))]:
        for present in (False,True): add(str((name,present)),(name,*tail),zset if present else ())
    for name in ("ZUNIONSTORE","ZINTERSTORE","ZDIFFSTORE"):
        for present in (False,True): add(str((name,present)),(name,D,1,K),zset if present else (),(K,D))
    for present in (False,True): add(str(("ZRANGESTORE",present)),("ZRANGESTORE",D,K,0,-1),zset if present else (),(K,D))
    for cmd in [("HSET",K,"a","1"),("HMSET",K,"a","1"),("HSETNX",K,"a","2"),
                ("HDEL",K,"none"),("HDEL",K,"a"),("HINCRBY",K,"a",0),("HINCRBYFLOAT",K,"a",0)]:
        for present in (False,True): add(str((cmd,present)),cmd,ahash if present else ())
    for name in ("HEXPIRE","HPEXPIRE","HEXPIREAT","HPEXPIREAT"):
        value = 60 if name == "HEXPIRE" else 60000 if name == "HPEXPIRE" else 2000000000 if name == "HEXPIREAT" else 2000000000000
        for field in ("a","none"):
            for condition in ((),("XX",)):
                add(str((name,field,condition)),(name,K,value,*condition,"FIELDS",1,field),ahash)
    add("HPERSIST-plain",("HPERSIST",K,"FIELDS",1,"a"),ahash)
    add("HPERSIST-ttl",("HPERSIST",K,"FIELDS",1,"a"),ahash+[("HEXPIRE",K,60,"FIELDS",1,"a")])
    for name,tail in [("PFADD",(K,"a")),("PFCOUNT",(K,)),("PFMERGE",(D,K)),("PFDEBUG",("TODENSE",K))]:
        for seedname,seed in [("absent",[]),("uncached",[("PFADD",K,"a")]),("cached",[("PFADD",K,"a"),("PFCOUNT",K)])]:
            add(name+seedname,(name,*tail),seed,(K,D))
    for present in (False,True):
        add(str(("BITOP",present)),("BITOP","OR",D,K),string if present else (),(K,D))
        add(str(("SORT",present)),("SORT",K,"STORE",D),seq if present else (),(K,D))
    for name,cmd in [("BITOP",("BITOP","OR",D,K)),("SORT",("SORT",K,"STORE",D))] + [
            (name,(name,D,K)) for name in ("SINTERSTORE","SUNIONSTORE","SDIFFSTORE")] + [
            (name,(name,D,1,K)) for name in ("ZINTERSTORE","ZUNIONSTORE","ZDIFFSTORE")] + [
            ("ZRANGESTORE",("ZRANGESTORE",D,K,0,-1))]:
        add(name+"-clear-dest",cmd,[("SET",D,"old")],(K,D))
    geo=[("GEOADD",K,0,0,"a")]
    for cmd in [("GEOADD",K,0,0,"a"),("GEOADD",K,1,1,"a"),
                ("GEOSEARCHSTORE",D,K,"FROMMEMBER","a","BYRADIUS",1,"km"),
                ("GEORADIUS",K,0,0,1,"km","STORE",D),("GEORADIUSBYMEMBER",K,"a",1,"km","STORE",D)]:
        add(str(cmd),cmd,geo,(K,D))
    for cmd in [("XADD",K,"2-0","f","v"),("XDEL",K,"1-0"),("XDEL",K,"2-0"),
                ("XTRIM",K,"MAXLEN",0),("XTRIM",K,"MAXLEN",10),("XSETID",K,"2-0"),
                ("XGROUP","CREATE",K,"g","0"),("XGROUP","CREATE",K,"g","0","MKSTREAM")]: add(str(cmd),cmd,stream)
    add("XGROUP-mkstream",("XGROUP","CREATE",K,"g","0","MKSTREAM"))
    grouped=stream+[("XGROUP","CREATE",K,"g","0")]
    pending=grouped+[("XREADGROUP","GROUP","g","c","STREAMS",K,">")]
    for cmd in [("XGROUP","DESTROY",K,"g"),("XGROUP","DESTROY",K,"none"),
                ("XGROUP","CREATECONSUMER",K,"g","c"),("XGROUP","DELCONSUMER",K,"g","c"),
                ("XGROUP","DELCONSUMER",K,"g","none"),("XGROUP","SETID",K,"g","0"),
                ("XACK",K,"g","1-0"),("XACK",K,"g","9-0"),
                ("XCLAIM",K,"g","d",0,"1-0"),("XAUTOCLAIM",K,"g","d",0,"0-0"),
                ("XREADGROUP","GROUP","g","d","STREAMS",K,">")]: add(str(cmd),cmd,pending)
    for name in ("FLUSHDB","FLUSHALL"):
        for present in (False,True): add(str((name,present)),(name,),string if present else ())
    if DATABASES > 1:
        for present in (False,True):
            add(str(("MOVE",present)),("MOVE",K,1),string if present else ())
            add(str(("SWAPDB",present)),("SWAPDB",0,1),string if present else ())
    c.cmd("SET", "dump-source", "v"); payload=c.cmd("DUMP","dump-source");c.cmd("DEL","dump-source")
    add("RESTORE-ASKING",("RESTORE-ASKING",K,0,payload))
    add("RESTORE-new",("RESTORE",K,0,payload));add("RESTORE-busy",("RESTORE",K,0,payload),string)
    add("RESTORE-replace",("RESTORE",K,0,payload,"REPLACE"),string)
    for body in ['return redis.call("SET",KEYS[1],"a")','return redis.call("SETNX",KEYS[1],"b")','return 1']:
        sha=c.cmd("SCRIPT","LOAD",body)
        for name,script in (("EVAL",body),("EVALSHA",sha)):
            add(str((name,body)),(name,script,1,K),string)
    for body in ['return redis.call("SETNX",KEYS[1],"b")',
                 'redis.call("SET",KEYS[1],"a"); return redis.call("SETNX",KEYS[2],"b")',
                 'return redis.call("GET",KEYS[1])',
                 'redis.call("SET",KEYS[1],"b"); error("after write")']:
        sha=c.cmd("SCRIPT","LOAD",body)
        for name,script in (("EVAL",body),("EVALSHA",sha)):
            add("cross-"+str((name,body)),(name,script,2,K,D),string+[("SET",D,"a")],(K,D))
    c.cmd("FUNCTION","FLUSH")
    c.cmd("FUNCTION","LOAD",'#!lua name=watching\nredis.register_function("wset",function(keys) return redis.call("SET",keys[1],"a") end)\nredis.register_function("wnx",function(keys) return redis.call("SETNX",keys[1],"a") end)')
    for name in ("wset","wnx"): add("FCALL-"+name,("FCALL",name,1,K),string)
    # Match live registry coverage. FLIP is TomoKV's administrative extension.
    registered=REGISTERED
    covered={row[1][0] for row in rows}
    excluded={"FLIP"} | ({"MOVE","SWAPDB"} if DATABASES == 1 else set())
    missing=registered-covered-excluded
    assert not missing, ("write command table incomplete",sorted(missing))
    print("COVERAGE",json.dumps(sorted(covered)),flush=True)
    return rows


def probe(c, _case):
    outcomes={}
    rows=table(c)
    for label,command,seed,keys,db in rows:
        # FLUSH inside EXEC is an existing unsupported transaction surface;
        # the requested writer-command/WATCH/EXEC case still runs for both.
        transactions=(False,) if command[0] in ("FLUSHDB","FLUSHALL") or label.startswith("cross-") else (False,True)
        for transaction in transactions:
            for watched in keys:
                c.cmd("SELECT",0);equal(c.cmd("FLUSHALL"),b"OK","fresh state")
                for setup in seed:
                    reply=c.cmd(*setup)
                    assert not isinstance(reply,RespError),("bad setup",setup,reply)
                w=Conn(c.host,c.port,buffering=0)
                try:
                    equal(w.cmd("WATCH",watched),b"OK","WATCH")
                    if transaction: c.cmd("MULTI")
                    reply=c.cmd(*command)
                    if transaction: reply=c.cmd("EXEC")
                    equal(w.cmd("MULTI"),b"OK","MULTI");equal(w.cmd("PING"),b"QUEUED","queued")
                    executed=w.cmd("EXEC")
                    assert executed in (None,[b"PONG"]),executed
                    keylabel="source" if watched == K else "destination"
                    identity=str((label,transaction,keylabel))
                    outcomes[identity]=executed is None
                    print("CASE",json.dumps({"case":identity,"write_reply":wire(reply),"dirty":executed is None}),flush=True)
                finally: w.close()
    # Physical expiry is independent of command success. A WATCH armed on an
    # already-expired key is Redis's expired registration, not a live deadline.
    equal(c.cmd("DEBUG","SET-ACTIVE-EXPIRE",0),b"OK","freeze active expiry")
    for before_watch in (False,True):
        c.cmd("CONFIG","SET","maxmemory",0);c.cmd("FLUSHALL")
        w=Conn(c.host,c.port,buffering=0)
        try:
            for attempt in range(3):
                w.cmd("UNWATCH");c.cmd("DEL",K)
                c.cmd("SET",K,"v","PX",150)
                if before_watch:
                    if c.cmd("PTTL",K)<=0: continue
                    time.sleep(.2)
                    equal(w.cmd("WATCH",K),b"OK","expired WATCH")
                    break
                equal(w.cmd("WATCH",K),b"OK","live expiry WATCH")
                if c.cmd("PTTL",K)>0: break
            else: raise AssertionError("fresh expiry WATCH window never armed")
            if not before_watch: time.sleep(.2)
            equal(c.cmd("GET",K),None,"physical expiry")
            w.cmd("MULTI");w.cmd("PING");result=w.cmd("EXEC")
            equal(result,[b"PONG"] if before_watch else None,"expiry invalidation")
            outcomes["expired-before-watch="+str(before_watch)]=result is None
        finally:w.close()
    c.cmd("DEBUG","SET-ACTIVE-EXPIRE",1)
    for attempt in range(3):
        c.cmd("CONFIG","SET","maxmemory",0);c.cmd("FLUSHALL")
        keys=["datafix2:evicted:"+str(attempt)+":"+str(i) for i in range(128)]
        for key in keys:c.cmd("SET",key,"v"*1000)
        w=Conn(c.host,c.port,buffering=0)
        try:
            w.cmd("WATCH",*keys)
            c.cmd("CONFIG","SET","maxmemory-policy","allkeys-lru")
            c.cmd("CONFIG","SET","maxmemory",8192)
            c.cmd("SET",K,"pressure")
            remaining=c.cmd("EXISTS",*keys)
            if remaining == len(keys): continue
            w.cmd("MULTI");w.cmd("PING")
            equal(w.cmd("EXEC"),None,"physical eviction invalidates WATCH")
            outcomes["physical-eviction"]=True
            break
        finally:
            w.close();c.cmd("CONFIG","SET","maxmemory",0)
    else: raise AssertionError("eviction window never opened on three fresh cohorts")
    return outcomes

if __name__ == "__main__":
    run(probe,["watch"],prepare)
