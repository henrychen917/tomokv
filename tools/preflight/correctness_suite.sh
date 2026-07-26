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
  --tomokv-ex-threads 4 --thredis-flat-store 1 --save '' --appendonly no --protected-mode no \
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

open(out,"w").write("".join(f"{n}\t{v}\t{d}\n" for n,v,d in res))
print("".join(f"{n}\t{v}\t{d}\n" for n,v,d in res), end="")
PY
grep -cE 'Guru|crashed by signal|ASSERTION' $J/cs.log | awk '{if($1>0) print "crash-markers\tFAIL\t"$1; else print "crash-markers\tPASS\t0"}' >> $OUT
pkill -9 -x redis-corr 2>/dev/null
echo "RESULT: $(grep -c 'PASS' $OUT) passed, $(grep -c 'FAIL' $OUT) failed" >> $OUT
