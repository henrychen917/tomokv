#!/bin/bash
# CORRECTNESS SUITE — every ordering/boundary invariant this fork has actually broken at least once.
# Runs inside preflight, BEFORE any comparison benchmark. Each check exists because a real bug got
# past a weaker check; the comment on each says which.
set -u
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}; P=/shared/Projects
PORT=7994; OUT=$J/correctness_suite.out; : > $OUT
cp "$BIN" $J/redis-corr 2>/dev/null; CB=$J/redis-corr
pkill -9 -x redis-corr 2>/dev/null; sleep 1; rm -rf $J/cs; mkdir -p $J/cs; : > $J/cs.log
taskset -c 0-7 $CB --port $PORT --dir $J/cs --tomokv-numa-nodes 1 --tomokv-io-threads 4 \
  --tomokv-ex-threads 4 --thredis-flat-store 1 ${TOMO_XTRA:-} --save '' --appendonly no --protected-mode no \
  --logfile $J/cs.log >/dev/null 2>&1 &
sleep 3
python3 - "$OUT" "$PORT" "${SMOKE:-0}" <<'PY'
import socket, sys, random
out, port, smoke = sys.argv[1], int(sys.argv[2]), sys.argv[3]=="1"
R = (lambda n: max(1, n//5)) if smoke else (lambda n: n)
res=[]
def rec(name, ok, detail=""): res.append((name, "PASS" if ok else "FAIL", detail))
try: s=socket.create_connection(("127.0.0.1",port)); s.settimeout(30)
except Exception as e:
    open(out,"w").write(f"boot\tFAIL\t{e}\n"); raise SystemExit
def cmd(*a):
    o=f"*{len(a)}\r\n".encode()
    for x in a:
        b=x if isinstance(x,bytes) else str(x).encode()
        o+=b"$%d\r\n%s\r\n"%(len(b),b)
    return o
def rd(pred):
    d=b""
    while not pred(d):
        c=s.recv(1<<20)
        if not c: break
        d+=c
    return d

# 1. PIPELINE ORDERING, non-first key (TASK#43: single-executor M-reads missed a same-client SET —
#    1936-2335/6000 stale; element-1-only tests could NOT see it).
N=R(6000)
s.sendall(b"".join(cmd("SET",f"ak:{i}","A")+cmd("SET",f"bk:{i}","OLD") for i in range(N)))
rd(lambda d: d.count(b"+OK")>=2*N)
s.sendall(b"".join(cmd("SET",f"bk:{i}","NEW")+cmd("MGET",f"ak:{i}",f"bk:{i}") for i in range(N)))
d=rd(lambda d: d.count(b"*2\r\n")>=N)
import re
stale=sum(1 for p in d.split(b"+OK\r\n")[1:]
          if (m:=re.match(rb"\*2\r\n\$1\r\nA\r\n\$\d+\r\n([A-Z]+)\r\n",p)) and m.group(1)!=b"NEW")
rec("pipeline-ordering-nonfirst-key", stale==0, f"stale={stale}/{N}")

# 2. M-COMMAND ARITY ACROSS SUB-WAVE BOUNDARIES (sub-wave staging advanced base by the full wave
#    while capping nw at the sub-wave => MGET(10) emitted an 8-element body under a 10-element
#    header; individual GETs looked fine).
bad=[]
for n in [1,2,7,8,9,15,16,17,31,32,33,64,100]:
    ks=[f"bw{n}:{i}" for i in range(n)]
    s.sendall(cmd("MSET",*[x for k,v in zip(ks,[f"x{i}" for i in range(n)]) for x in (k,v)]))
    rd(lambda d: b"+OK" in d)
    s.sendall(cmd("MGET",*ks))
    d=rd(lambda d: d.count(b"\r\n")>=2*n+1)
    got=d.count(b"$")
    if got!=n: bad.append(f"N={n}:got{got}")
rec("mget-arity-across-subwaves", not bad, ",".join(bad[:5]))

# 3. SAME-KEY WRITE CHAIN then read (retire-aware reordering could invert same-client same-key
#    writes if its partition were unstable).
bad=0
for r in range(R(400)):
    k=f"chain:{r}"
    s.sendall(b"".join(cmd("SET",k,f"v{i}") for i in range(20))+cmd("GET",k))
    d=rd(lambda d: d.count(b"+OK")>=20 and b"v19" in d)
    if b"v19" not in d: bad+=1
rec("same-key-write-chain", bad==0, f"bad={bad}")

# 4. SET/DEL/GET ordering
bad=0
for r in range(R(300)):
    k=f"dl:{r}"
    s.sendall(cmd("SET",k,"X")+cmd("DEL",k)+cmd("GET",k))
    d=rd(lambda d: b"$-1" in d or b":0" in d)
    if b"$-1" not in d: bad+=1
rec("set-del-get", bad==0, f"bad={bad}")

# 5. VALUE-SIZE BOUNDARIES (embed thresholds 44/192/255 + the SDS_TYPE_8 wall; RAW-embed and
#    embed192 both changed object layout here).
bad=[]
for L in [0,1,43,44,45,100,169,170,171,191,192,254,255,256,300,4096,65536]:
    v=b"z"*L
    s.sendall(cmd("SET",f"len:{L}",v)); rd(lambda d: b"+OK" in d)
    s.sendall(cmd("STRLEN",f"len:{L}")); d=rd(lambda d: b"\r\n" in d)
    if f":{L}\r\n".encode() not in d: bad.append(str(L))
    s.sendall(cmd("GET",f"len:{L}")); d=rd(lambda d: d.endswith(b"\r\n") and len(d)>=L)
    if L and v not in d: bad.append(f"{L}v")
rec("value-size-boundaries", not bad, ",".join(bad[:8]))

# 6. IN-PLACE MUTATORS on embedded values (APPEND/SETRANGE must de-embed correctly — the
#    dbUnshareStringValue invariant the RAW-embed patch pins).
s.sendall(cmd("SET","ap","a"*50)); rd(lambda d:b"+OK" in d)
s.sendall(cmd("APPEND","ap","b"*200)); rd(lambda d:b":" in d)
s.sendall(cmd("STRLEN","ap")); d=rd(lambda d:b"\r\n" in d)
ok1=b":250\r\n" in d
s.sendall(cmd("SETRANGE","ap",0,"zzz")); rd(lambda d:b":" in d)
s.sendall(cmd("GETRANGE","ap",0,2)); d=rd(lambda d:b"zzz" in d or b"\r\n" in d)
rec("inplace-mutators-on-embedded", ok1 and b"zzz" in d)

# 7. MSET/MGET round-trip with binary-safe values incl. embedded CRLF
vals={f"bin:{i}": bytes([i%256])*7 + b"\r\n" + b"tail" for i in range(50)}
s.sendall(cmd("MSET",*[x for k,v in vals.items() for x in (k,v)])); rd(lambda d:b"+OK" in d)
s.sendall(cmd("MGET",*vals.keys())); d=rd(lambda d: d.count(b"$")>=50)
rec("binary-safe-mset-mget", all(v in d for v in list(vals.values())[:10]))

# 8. EXPIRE first-TTL realloc + concurrent read (the kvobj-realloc TOCTOU the wave RAW emit
#    re-probe protocol exists for).
bad=0
for r in range(R(200)):
    k=f"ex:{r}"
    s.sendall(cmd("SET",k,"q"*80)+cmd("EXPIRE",k,100)+cmd("APPEND",k,"x")+cmd("MGET",k,"ak:0"))
    d=rd(lambda d: d.count(b"*2\r\n")>=1)
    if b"q"*80 not in d: bad+=1
rec("expire-realloc-then-read", bad==0, f"bad={bad}")

# 8b. EXPIRE first-TTL realloc on a NON-STRING value (Guru Meditation "Not implemented"
#     #object.c: the FLATSTORE lifetime pin in setExpireByLink made refcount != 1, and
#     kvobjSetEx() had no re-homing branch for a collection => serverPanic. `SADD s m;
#     EXPIRE s 100` killed the server. Check 8 above could NEVER see it: it only ever
#     stores string values, and strings have the INT/RAW copy branches. Every type gets
#     its first TTL here, then is MUTATED and read back, so a mis-moved value shows up
#     as lost/short content rather than only as a crash.
seed=[("SET",  "nx:set",  ("SADD","nx:set","m1","m2","m3"),      ("SADD","nx:set","m4"),   ("SMEMBERS","nx:set"), [b"m1",b"m4"]),
      ("LIST", "nx:list", ("RPUSH","nx:list","v1","v2","v3"),    ("RPUSH","nx:list","v4"), ("LRANGE","nx:list",0,-1), [b"v1",b"v4"]),
      ("HASH", "nx:hash", ("HSET","nx:hash","f1","a","f2","b"),  ("HSET","nx:hash","f3","c"), ("HGETALL","nx:hash"), [b"f1",b"f3"]),
      ("ZSET", "nx:zset", ("ZADD","nx:zset",1,"z1",2,"z2"),      ("ZADD","nx:zset",3,"z3"), ("ZRANGE","nx:zset",0,-1), [b"z1",b"z3"]),
      ("BIG",  "nx:big",  ("SADD","nx:big",*[f"e{i}" for i in range(600)]), ("SADD","nx:big","tail"), ("SMEMBERS","nx:big"), [b"e599",b"tail"])]
#     NB: the panic kills the server mid-check, and this file is only written at the end —
#     so the failure is caught here explicitly, otherwise the evidence is lost and only
#     crash-markers reports.
nsbad=[]; alive=False
try:
    for tag,k,create,mutate,readback,want in seed:
        s.sendall(cmd("DEL",k)); rd(lambda d:b":" in d)
        s.sendall(cmd(*create)); rd(lambda d:b":" in d)
        s.sendall(cmd("EXPIRE",k,4242)); d=rd(lambda d:b"\r\n" in d)      # <- the realloc
        if b":1" not in d: nsbad.append(tag+"-expire")
        s.sendall(cmd("TTL",k)); d=rd(lambda d:b"\r\n" in d)
        if b":42" not in d: nsbad.append(tag+"-ttl")
        s.sendall(cmd(*mutate)); rd(lambda d:b"\r\n" in d)                # mutate the MOVED value
        s.sendall(cmd(*readback)); d=rd(lambda d: d.count(b"\r\n")>=2)
        if not all(w in d for w in want): nsbad.append(tag+"-content")
        s.sendall(cmd("PERSIST",k)+cmd("EXPIRE",k,4343)+cmd("TTL",k))     # 2nd TTL: no realloc
        d=rd(lambda d: d.count(b"\r\n")>=3)
        if b":43" not in d: nsbad.append(tag+"-retll")
        s.sendall(cmd("DEL",k)); rd(lambda d:b":" in d)
    s.sendall(cmd("PING")); alive=b"PONG" in rd(lambda d:b"\r\n" in d)    # survived at all?
except Exception as e:
    nsbad.append(f"server-died({type(e).__name__})")
rec("expire-realloc-nonstring", alive and not nsbad, f"alive={int(alive)},bad={','.join(nsbad) or '-'}")

# ---------------------------------------------------------------------------
# ORDER-2 regression block (checks 9-11). Same-client pipelined ordering under
# sharding rests on "same key => same owner queue => FIFO", which holds only while
# every sub is pushed from the dispatch loop in client order. Three paths broke it:
#   - multi-hop cross-shard groups (HOP2 plan/scatter) push their 2nd hop from the
#     DRAIN thread, after the following commands were already queued;
#   - the merge-execution stage chain (SINTER/SINTERCARD) does the same per stage;
#   - the node-local BORROW runs one executor over keys it does not own, skipping
#     those owners' queues entirely.
# All three answered from pre-HOP2 / pre-write state. Checks 1-8 could NEVER see it:
# they only pipeline single-key strings, which are 1-hop and owner-routed.
# These need a STRICT RESP reader (checks above use substring predicates, which
# cannot tell "reply 3 is wrong" from "reply 3 is late") and a fresh connection, so
# leftover unconsumed bytes from the loose readers above cannot desync the parser.
# Keys are indexed pairs: with W workers a random pair is cross-shard with p=(W-1)/W,
# so a few dozen pairs guarantee cross-shard coverage without mirroring the hash here.
class RR:
    def __init__(self, port):
        self.s=socket.create_connection(("127.0.0.1",port)); self.s.settimeout(30)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f=self.s.makefile("rb")
    def read(self):
        ln=self.f.readline()
        if not ln: raise IOError("connection closed")
        t,b=ln[0:1],ln[1:-2]
        if t==b"+": return b
        if t==b"-": return ("err", b.decode("utf-8","replace"))
        if t==b":": return int(b)
        if t==b"$":
            n=int(b)
            return None if n==-1 else self.f.read(n+2)[:-2]
        if t==b"*":
            n=int(b)
            return None if n==-1 else [self.read() for _ in range(n)]
        raise IOError("bad resp %r"%ln)
    def pipe(self, ops):
        self.s.sendall(b"".join(cmd(*o) for o in ops))
        return [self.read() for _ in ops]
def S(x): return sorted(x) if isinstance(x,list) else x

try: rr=RR(port)
except Exception as e:
    rr=None
    for n in ("xshard-2hop-pipeline-order","msetnx-allornothing-pipelined","xshard-read-pipeline-order"):
        rec(n, False, f"connect={e}")

# 9. MULTI-HOP CROSS-SHARD command followed, in the SAME pipeline, by a read of the
#    keys it touched. Pre-fix the follower observed the state BEFORE hop 2: SMOVE's
#    member still in src, RENAME's dst still absent, SINTERSTORE's dst still empty.
if rr:
    bad=[]
    for i in range(R(60)):
        a,b=f"o2sm:a{i}",f"o2sm:b{i}"
        rr.pipe([("DEL",a,b),("SADD",a,"m1","m2"),("SADD",b,"z")])
        r=rr.pipe([("SMOVE",a,b,"m1"),("SMEMBERS",a),("SMEMBERS",b)])
        if [r[0],S(r[1]),S(r[2])]!=[1,[b"m2"],[b"m1",b"z"]]: bad.append(f"smove{i}")
        x,y=f"o2rn:a{i}",f"o2rn:b{i}"
        rr.pipe([("DEL",x,y),("SET",x,"V1")])
        r=rr.pipe([("RENAME",x,y),("GET",y),("EXISTS",x)])
        if [r[0],r[1],r[2]]!=[b"OK",b"V1",0]: bad.append(f"rename{i}")
        p,q,dst=f"o2ss:a{i}",f"o2ss:b{i}",f"o2ss:d{i}"
        rr.pipe([("DEL",p,q,dst),("SADD",p,"a","b","c"),("SADD",q,"b","c","d")])
        r=rr.pipe([("SINTERSTORE",dst,p,q),("SMEMBERS",dst)])
        if [r[0],S(r[1])]!=[2,[b"b",b"c"]]: bad.append(f"sstore{i}")
    rec("xshard-2hop-pipeline-order", not bad, f"bad={len(bad)}:{','.join(bad[:5]) or '-'}")

# 10. MSETNX is all-or-nothing. Two IDENTICAL MSETNX in one pipeline must answer 1
#     then 0, and the keys must exist afterwards. Pre-fix both existence-probe waves
#     ran before either write wave, so both answered 1 — and the trailing EXISTS,
#     dispatched ahead of the HOP2 scatter, saw none of the keys written.
if rr:
    bad=[]
    for i in range(R(40)):
        ks=[f"o2mn:{i}:{j}" for j in range(6)]
        rr.pipe([tuple(["DEL"]+ks)])
        mn=tuple(["MSETNX"]+[x for k in ks for x in (k,"v")])
        r=rr.pipe([mn,mn,tuple(["EXISTS"]+ks)])
        if r!=[1,0,6]: bad.append(f"{i}:{r}")
    rec("msetnx-allornothing-pipelined", not bad, f"bad={len(bad)}:{','.join(bad[:3]) or '-'}")

# 11. CROSS-SHARD READ vs this client's own EARLIER pipelined write. The node-local
#     borrow (one executor, non-owner reads) and the merge-execution stage chain both
#     let the read skip a write still queued on another owner's queue, so SINTERCARD /
#     SINTER answered the pre-SREM value. Both keys are read, so a stale answer on
#     either side shows up.
if rr:
    bad=[]
    for i in range(R(60)):
        a,b=f"o2si:a{i}",f"o2si:b{i}"
        rr.pipe([("DEL",a,b),("SADD",a,"a","b","c"),("SADD",b,"a","b","c")])
        r=rr.pipe([("SINTERCARD",2,a,b),("SREM",b,"a"),("SINTERCARD",2,a,b),
                   ("SINTER",a,b),("SREM",a,"b"),("SINTER",a,b)])
        if [r[0],r[1],r[2],S(r[3]),r[4],S(r[5])]!=[3,1,2,[b"b",b"c"],1,[b"c"]]:
            bad.append(f"{i}:{r}")
    rec("xshard-read-pipeline-order", not bad, f"bad={len(bad)}:{','.join(str(x) for x in bad[:3]) or '-'}")

open(out,"w").write("".join(f"{n}\t{v}\t{d}\n" for n,v,d in res))
print("".join(f"{n}\t{v}\t{d}\n" for n,v,d in res), end="")
PY
# STRESS-ORDERING: re-run the ordering check WHILE the server is under churn — the P0 stale-read
# bug was load-dependent, so a quiescent check alone is not sufficient evidence.
taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram --test-time=25 --ratio=1:1 \
  -d 64 --key-pattern=R:R --key-maximum=200000 -t 4 -c 10 --pipeline 16 --distinct-client-seed >/dev/null 2>&1 &
MTPID=$!
TOMO_BIN="$BIN" LBL="under-load" EXTRA="${TOMO_XTRA:-}" PORT_OVERRIDE=$PORT "$(dirname "${BASH_SOURCE[0]}")"/ord_test.sh 2>/dev/null \
  | grep -q 'stale=0' && echo "ordering-under-load	PASS	" >> $OUT || echo "ordering-under-load	FAIL	stale reads under churn" >> $OUT
wait $MTPID 2>/dev/null
grep -cE 'Guru|crashed by signal|ASSERTION' $J/cs.log | awk '{if($1>0) print "crash-markers\tFAIL\t"$1; else print "crash-markers\tPASS\t0"}' >> $OUT
pkill -9 -x redis-corr 2>/dev/null
echo "RESULT: $(grep -c 'PASS' $OUT) passed, $(grep -c 'FAIL' $OUT) failed" >> $OUT
