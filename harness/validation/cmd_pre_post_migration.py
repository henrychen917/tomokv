#!/usr/bin/env python3
"""Validate ALL command families return identical results PRE and POST an online migration that
moves the keys to a different worker. Keys are placed with the verified xxh64 replica so the test
keys land in the migrated bucket range [LO,HI) on worker SRC. Also checks cross-shard commands and
that a TTL key expiring across the migration is NOT resurrected on the new owner."""
import socket,sys,time
import os,sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import keys as K

PORT=7800; LO,HI=1280,1536; SRC,DST=2,3     # upper half of worker 2 -> worker 3 (suffix move)
s=socket.create_connection(("127.0.0.1",PORT)); f=s.makefile("rwb")
def send(*a):
    f.write(("*%d\r\n"%len(a)).encode())
    for x in a:
        x=str(x).encode(); f.write(b"$%d\r\n"%len(x)); f.write(x); f.write(b"\r\n")
    f.flush()
def rd():
    l=f.readline(); t=l[:1]; b=l[1:].strip()
    if t==b'+': return b.decode()
    if t==b'-': return "ERR:"+b.decode()
    if t==b':': return int(b)
    if t==b'$':
        n=int(b);
        if n<0: return None
        d=f.read(n); f.read(2); return d.decode()
    if t==b'*':
        n=int(b)
        if n<0: return None
        return [rd() for _ in range(n)]
    return l
import os
TRACE=os.environ.get("TRACE")
def cmd(*a):
    if TRACE: print("  >>",*a[:4]); sys.stdout.flush()
    send(*a); return rd()

# pick keys whose bucket is in [LO,HI) (will move) + control keys outside
def keys_in_range(n,prefix):
    out=[]; i=0
    while len(out)<n:
        k="%s%d"%(prefix,i); i+=1
        if LO<=K.bucket(k)<HI: out.append(k)
    return out
def keys_out_range(n,prefix):
    out=[]; i=0
    while len(out)<n:
        k="%s%d"%(prefix,i); i+=1
        if not(LO<=K.bucket(k)<HI): out.append(k)
    return out

ik=keys_in_range(40,"in"); ok=keys_out_range(10,"out")
# ---- build workload: each entry = (label, setup_fn, verify_cmd, expected) ----
checks=[]   # (label, [verify cmd args], expected)
def setup():
    i=iter(ik)
    def nk(): return next(i)
    # strings
    k=nk(); cmd("SET",k,"hello"); cmd("APPEND",k," world")
    checks.append(("string GET+APPEND",["GET",k],"hello world"))
    checks.append(("STRLEN",["STRLEN",k],11)); checks.append(("GETRANGE",["GETRANGE",k,0,4],"hello"))
    k=nk(); cmd("SET",k,"100"); cmd("INCR",k); cmd("INCRBY",k,5); cmd("DECRBY",k,6)
    checks.append(("INCR/INCRBY/DECRBY",["GET",k],"100"))
    k=nk(); cmd("SETBIT",k,7,1); checks.append(("GETBIT",["GETBIT",k,7],1)); checks.append(("BITCOUNT",["BITCOUNT",k],1))
    # hash
    k=nk(); cmd("HSET",k,"f1","v1","f2","2"); checks.append(("HGET",["HGET",k,"f1"],"v1"))
    checks.append(("HLEN",["HLEN",k],2)); cmd("HINCRBY",k,"f2",3); checks.append(("HINCRBY",["HGET",k,"f2"],"5"))
    checks.append(("HMGET",["HMGET",k,"f1","f2"],["v1","5"]))
    # list (final state after one LPOP = [b,c,d])
    k=nk(); cmd("RPUSH",k,"a","b","c","d"); cmd("LPOP",k)
    checks.append(("LRANGE",["LRANGE",k,0,-1],["b","c","d"]))
    checks.append(("LLEN",["LLEN",k],3)); checks.append(("LINDEX",["LINDEX",k,2],"d"))
    # set (final {y,z} after SREM x)
    k=nk(); cmd("SADD",k,"x","y","z"); cmd("SREM",k,"x")
    checks.append(("SCARD",["SCARD",k],2)); checks.append(("SISMEMBER",["SISMEMBER",k,"y"],1))
    checks.append(("SISMEMBER-removed",["SISMEMBER",k,"x"],0))
    # zset (final scores a=11,b=2,c=3 after ZINCRBY)
    k=nk(); cmd("ZADD",k,1,"a",2,"b",3,"c"); cmd("ZINCRBY",k,10,"a")
    checks.append(("ZRANGE",["ZRANGE",k,0,-1],["b","c","a"]))
    checks.append(("ZSCORE",["ZSCORE",k,"b"],"2")); checks.append(("ZCARD",["ZCARD",k],3))
    checks.append(("ZRANK",["ZRANK",k,"c"],1)); checks.append(("ZSCORE-a",["ZSCORE",k,"a"],"11"))
    # type + expire (persistent)
    k=nk(); cmd("SET",k,"v"); cmd("EXPIRE",k,10000);
    checks.append(("TTL>0",["TTL",k],"POSITIVE")); checks.append(("TYPE",["TYPE",k],"string"))
    k=nk(); cmd("RPUSH",k,"1"); checks.append(("TYPE list",["TYPE",k],"list"))
    # GETDEL leaves a known-absent key
    k=nk(); cmd("SET",k,"gone"); checks.append(("EXISTS before",["EXISTS",k],1))
    setup.getdel_key=k
setup()

def run_checks(tag):
    fails=0
    for label,c,exp in checks:
        got=cmd(*c)
        if exp=="POSITIVE": good=isinstance(got,int) and got>0
        else: good=(got==exp)
        if not good:
            fails+=1; print("  [%s] FAIL %-22s cmd=%s got=%r exp=%r"%(tag,label," ".join(map(str,c)),got,exp))
    print("  [%s] %d/%d command checks passed"%(tag,len(checks)-fails,len(checks)))
    return fails

# cross-shard checks spanning in-range + out-range keys (DEDICATED keys, no collision with type tests)
csk = keys_in_range(3,"csin")+keys_out_range(3,"csout")
def cs_setup():
    args=["MSET"]
    for j,k in enumerate(csk): args+= [k,"cs%d"%j]
    cmd(*args)
def cs_check(tag):
    fails=0
    got=cmd("MGET",*csk); exp=["cs%d"%j for j in range(len(csk))]
    if got!=exp: fails+=1; print("  [%s] FAIL cross-shard MGET got=%r exp=%r"%(tag,got,exp))
    e=cmd("EXISTS",*csk)
    if e!=len(csk): fails+=1; print("  [%s] FAIL cross-shard EXISTS got=%r exp=%d"%(tag,e,len(csk)))
    print("  [%s] cross-shard MGET/EXISTS %s"%(tag,"OK" if fails==0 else "FAIL"))
    return fails
cs_setup()

# TTL-across-migration: key in range with a short TTL that expires during/after the migration window
ttlk=keys_in_range(1,"ttl")[0]; cmd("SET",ttlk,"willexpire"); cmd("PEXPIRE",ttlk,2500)

print("=== PRE-migration verification ===")
pf = run_checks("PRE") + cs_check("PRE")

print("=== migrating [%d,%d) worker %d -> %d ==="%(LO,HI,SRC,DST))
print("  ARM:",cmd("DEBUG","RESHARD","START",LO,HI,SRC,DST))
for _ in range(8):
    send("DEBUG","RESHARD","STATUS"); st=rd()
    if "scan_done=1" in st: break
    time.sleep(1)
# (There used to be a `converged=1` readout here. STATUS computed it by walking BOTH shards on the
# calling IO thread -- O(keyspace) on the thread that advances the cutover coordinator -- and with
# >1 worker per node both shards are the SAME physical db, so it printed True unconditionally. The
# content check is now `DEBUG RESHARD VERIFY`, refused while a migration is active.)
print("  CUTOVER:",cmd("DEBUG","RESHARD","CUTOVER"))
for _ in range(8):
    send("DEBUG","RESHARD","STATUS"); st=rd()
    if "active=0" in st: break
    time.sleep(1)
time.sleep(1)

print("=== POST-migration verification (keys now on worker %d) ==="%DST)
qf = run_checks("POST") + cs_check("POST")
# GETDEL still works post-migration
gd=cmd("GETDEL",setup.getdel_key); print("  GETDEL post:", "OK" if gd=="gone" else "FAIL got=%r"%gd)
# TTL key must be GONE (expired), not resurrected on the new owner
time.sleep(1)
tv=cmd("GET",ttlk); print("  TTL-key resurrection check: GET=%r -> %s"%(tv,"OK (expired, not resurrected)" if tv is None else "FAIL RESURRECTED"))

print("\n==== RESULT: pre_fails=%d post_fails=%d  %s ===="%(pf,qf,"ALL PASS" if (pf==0 and qf==0 and tv is None and gd=='gone') else "FAILURES"))
