#!/bin/bash
# CORRECTNESS SUITE — every ordering/boundary invariant this fork has actually broken at least once.
# Runs inside preflight, BEFORE any comparison benchmark. Each check exists because a real bug got
# past a weaker check; the comment on each says which.
#
# CASE exact-2m-seed
#   OUT OF SPEC: bounded boot/seed/DBSIZE proof times out or exits nonzero, memtier Totals is
#   missing/non-numeric/zero, or DBSIZE is not exactly 2,000,000 after seeding keys 1..2,000,000.
# CASE ordering-under-load
#   OUT OF SPEC: its canonical background generator does not materialize, the exact ordering probe
#   times out/exits nonzero/checks zero replies, or any checked reply is stale.
set -u
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${TOMO_BIN:?TOMO_BIN required}; P=/home/user/Projects
PORT=5994
KEY_MIN=1
KEY_MAX=2000000
VALUE_BYTES=32
SEED_TIMEOUT=${TOMO_SEED_TIMEOUT:-300}
BOOT_TIMEOUT=${TOMO_BOOT_TIMEOUT:-20}
CLIENT_TIMEOUT=${TOMO_CLIENT_TIMEOUT:-15}
DRIVER_TIMEOUT=${TOMO_DRIVER_TIMEOUT:-600}
ORDER_TIMEOUT=${TOMO_ORDER_TIMEOUT:-120}
LOAD_TIMEOUT=${TOMO_LOAD_TIMEOUT:-60}
EXPECT_NODES=2
EXPECT_IO=${TOMO_EXPECT_IO:-8}
EXPECT_EX=${TOMO_EXPECT_EX:-8}
EXPECT_MODE=${TOMO_EXPECT_MODE:-static}
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
if [ -n "${TOMO_RESULT_FILE:-}" ]; then
  OUT=$TOMO_RESULT_FILE
  if ! (set -o noclobber; : > "$OUT") 2>/dev/null; then
    echo "correctness-harness	FAIL	refusing to overwrite result file $OUT"
    exit 2
  fi
else
  OUT=$(mktemp "$J/correctness_suite.XXXXXX.out") || exit 2
fi
WORK=$(mktemp -d "$J/correctness_suite.XXXXXX.work") || {
  echo "correctness-harness	FAIL	could not create per-run work directory" | tee -a "$OUT"
  exit 2
}
CB=$WORK/redis-corr-$BASHPID
DATA=$WORK/data
LOG=$WORK/cs.log
mkdir -p "$DATA"
: > "$LOG"

CORR_PID=""
MTPID=""
CLIENT_PID=""
reap_owned_group(){
  local pid=${1:-} n=0
  [ -n "$pid" ] || return 0
  # Every group passed here was launched with setsid and its leader PID was captured at launch.
  # Kill that owned group only; never select processes by command name or command line.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM -- "$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 30 ]; do
    sleep 0.1
    n=$((n+1))
  done
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL -- "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
wait_owned_group(){
  local pid=$1 rc
  wait "$pid"
  rc=$?
  # timeout(1) can exit after killing its direct child while a descendant is still winding down.
  # Sweep only the captured, private process group before forgetting its PID.
  reap_owned_group "$pid"
  return "$rc"
}
cleanup_correctness(){
  if [ -n "${MTPID:-}" ]; then
    reap_owned_group "$MTPID"
    MTPID=""
  fi
  if [ -n "${CLIENT_PID:-}" ]; then
    reap_owned_group "$CLIENT_PID"
    CLIENT_PID=""
  fi
  if [ -n "${CORR_PID:-}" ]; then
    reap_owned_group "$CORR_PID"
    CORR_PID=""
  fi
  # The per-run work dir is the price of not sharing a name with another session's run; the staged
  # binary is the only large thing in it, so drop it once the server is down. The (small) log and
  # memtier output stay for postmortem, and the path is echoed at the end of the run.
  rm -f "$CB" 2>/dev/null
}
trap cleanup_correctness EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
emit(){ printf '%s\n' "$1" | tee -a "$OUT"; }
valid_total(){
  [[ "${1:-}" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
    awk -v v="$1" 'BEGIN { exit !(v + 0 > 0) }'
}

if ! cp "$BIN" "$CB" 2>/dev/null || ! chmod +x "$CB" 2>/dev/null; then
  emit "correctness-harness	FAIL	could not stage binary under test"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi
if [ $((EXPECT_IO + EXPECT_EX)) -ne 16 ]; then
  emit "correctness-harness\tFAIL\trequested io=$EXPECT_IO ex=$EXPECT_EX; require 16 threads per node"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi
setsid taskset -c "$SERVER_CORES" "$CB" --port $PORT --dir "$DATA" --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-io "$EXPECT_IO" \
  --tomokv-thread-ex "$EXPECT_EX" --tomokv-thread-mode "$EXPECT_MODE" --enable-debug-command local \
  ${TOMO_XTRA:-} --save '' --appendonly no --protected-mode no \
  --logfile "$LOG" >"$WORK/server.launch.log" 2>&1 &
CORR_PID=$!

# Bounded boot with process identity: a pre-existing listener on the fixed suite port must not be
# mistaken for the staged candidate. A timeout or mismatched INFO process_id is a hard failure.
BOOT_PROBE=$WORK/boot.probe
setsid timeout --foreground --signal=TERM --kill-after=2 "${BOOT_TIMEOUT}s" \
  python3 - "$PORT" "$CORR_PID" "$BOOT_TIMEOUT" >"$BOOT_PROBE" 2>&1 <<'PY' &
import os, re, socket, sys, time
port, wanted, limit = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
deadline = time.monotonic() + max(1.0, limit - 1.0)
req = b"*2\r\n$4\r\nINFO\r\n$6\r\nserver\r\n"
last = "not listening"
while time.monotonic() < deadline:
    try:
        os.kill(wanted, 0)
    except OSError:
        print("captured server PID exited before readiness")
        raise SystemExit(1)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.75) as s:
            s.settimeout(.75)
            s.sendall(req)
            data = b""
            while b"\r\nprocess_id:" not in data and len(data) < (1 << 20):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
            m = re.search(rb"(?:^|\r\n)process_id:(\d+)\r\n", data)
            if m:
                actual = int(m.group(1))
                if actual != wanted:
                    print(f"port owned by pid={actual}, captured pid={wanted}")
                    raise SystemExit(1)
                print(f"READY process_id={actual}")
                raise SystemExit(0)
            last = "INFO server omitted process_id"
    except (ConnectionError, OSError, socket.timeout) as e:
        last = f"{type(e).__name__}: {e}"
    time.sleep(.1)
print(f"readiness deadline expired: {last}")
raise SystemExit(1)
PY
CLIENT_PID=$!
wait_owned_group "$CLIENT_PID"
BOOT_RC=$?
CLIENT_PID=""
if [ "$BOOT_RC" -ne 0 ]; then
  emit "boot	FAIL	bounded readiness failed rc=$BOOT_RC: $(tr '\n' ' ' <"$BOOT_PROBE")"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi
if ! preflight_assert_standard_boot "$LOG" "$CORR_PID" "$EXPECT_IO" "$EXPECT_EX"; then
  emit "boot-pinning\tFAIL\t2x16c composed-L3/core-range assertion failed; log=$LOG"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi

# Prove the labeled matrix row, rather than merely proving that some server
# answered. CONFIG establishes the immutable requested shape and DEBUG proves
# every live role slot exactly once at the initial split.
TOPOLOGY_OUT=$WORK/topology.proof
setsid timeout --foreground --signal=TERM --kill-after=2 "${CLIENT_TIMEOUT}s" \
  python3 - "$PORT" "$EXPECT_NODES" "$EXPECT_IO" "$EXPECT_EX" "$EXPECT_MODE" \
  >"$TOPOLOGY_OUT" 2>&1 <<'PY' &
import re, socket, sys
port, nodes, io, ex = map(int, sys.argv[1:5])
mode = sys.argv[5]

def request(*args):
    out = f"*{len(args)}\r\n".encode()
    for arg in args:
        value = str(arg).encode()
        out += b"$%d\r\n%s\r\n" % (len(value), value)
    return out

def read_resp(stream):
    kind = stream.read(1)
    if not kind:
        raise RuntimeError("EOF")
    line = stream.readline()
    if not line.endswith(b"\r\n"):
        raise RuntimeError("truncated RESP line")
    body = line[:-2]
    if kind == b"+":
        return body
    if kind == b"-":
        raise RuntimeError(f"server error: {body!r}")
    if kind == b":":
        return int(body)
    if kind == b"$":
        length = int(body)
        if length < 0:
            return None
        value = stream.read(length)
        if len(value) != length or stream.read(2) != b"\r\n":
            raise RuntimeError("truncated bulk")
        return value
    if kind == b"*":
        return [read_resp(stream) for _ in range(int(body))]
    raise RuntimeError(f"unsupported RESP type {kind!r}")

with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
    sock.settimeout(5)
    stream = sock.makefile("rb")
    def command(*args):
        sock.sendall(request(*args))
        return read_resp(stream)
    values = {}
    for key in (
        "tomokv-nodes", "tomokv-thread-io", "tomokv-thread-ex",
        "tomokv-thread-mode",
    ):
        reply = command("CONFIG", "GET", key)
        if not isinstance(reply, list) or len(reply) != 2:
            raise RuntimeError(f"CONFIG GET {key} malformed: {reply!r}")
        values[key] = reply[1].decode()
    roles_reply = command("DEBUG", "TOMO-IOLOAD")

expected = {
    "tomokv-nodes": str(nodes),
    # AUTO exposes its provisioned symmetric pool through CONFIG: one immutable
    # base IO plus the other 15 convertible workers in each node. DEBUG below
    # separately proves that the requested 8/8 (or 15/1) live split was applied.
    "tomokv-thread-io": str(1 if mode == "auto" else io),
    "tomokv-thread-ex": str(io + ex - 1 if mode == "auto" else ex),
    "tomokv-thread-mode": mode,
}
if values != expected:
    raise RuntimeError(f"CONFIG shape {values!r}, expected {expected!r}")
if not isinstance(roles_reply, bytes):
    raise RuntimeError(f"DEBUG TOMO-IOLOAD malformed: {roles_reply!r}")
seen = {}
for line in roles_reply.decode().splitlines():
    match = re.fullmatch(
        r"io_slot ([0-9]+) mode=(IO|EX) conns=[0-9]+ busy=.*", line
    )
    if not match:
        continue
    slot = int(match.group(1))
    if slot in seen:
        raise RuntimeError(f"duplicate role slot {slot}")
    seen[slot] = match.group(2)
expected_io, expected_ex = nodes * io, nodes * ex
expected_slots = set(range(expected_io + expected_ex))
if set(seen) != expected_slots:
    raise RuntimeError(
        f"role slots {sorted(seen)}, expected {sorted(expected_slots)}"
    )
actual_io = sum(value == "IO" for value in seen.values())
actual_ex = sum(value == "EX" for value in seen.values())
if (actual_io, actual_ex) != (expected_io, expected_ex):
    raise RuntimeError(
        f"roles={actual_io}/{actual_ex}, expected={expected_io}/{expected_ex}"
    )
print(
    f"nodes={nodes} per-node={io}/{ex} mode={mode} "
    f"roles={actual_io}/{actual_ex} unique-slots={len(seen)}"
)
PY
CLIENT_PID=$!
wait_owned_group "$CLIENT_PID"
TOPOLOGY_RC=$?
CLIENT_PID=""
if [ "$TOPOLOGY_RC" -ne 0 ]; then
  emit "topology-proof	FAIL	rc=$TOPOLOGY_RC $(tr '\n' ' ' <"$TOPOLOGY_OUT")"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi
emit "topology-proof	PASS	$(tr '\n' ' ' <"$TOPOLOGY_OUT")"

# Acceptance prerequisite: materialize exactly the canonical 1..2,000,000 key range before any
# functional checks. A successful memtier exit without a positive Totals rate is still a non-run.
SEEDLOG=$WORK/exact-2m-seed.memtier
setsid timeout --foreground --signal=TERM --kill-after=5 "${SEED_TIMEOUT}s" \
  taskset -c "$LOAD_CORES" memtier_benchmark -s 127.0.0.1 -p "$PORT" --hide-histogram \
  --ratio=1:0 --key-pattern=P:P --key-minimum="$KEY_MIN" --key-maximum="$KEY_MAX" \
  -n allkeys -d "$VALUE_BYTES" -t 8 -c 25 --pipeline 32 --distinct-client-seed \
  --connection-timeout=5 --connection-stage-timeout=15 >"$SEEDLOG" 2>&1 &
MTPID=$!
wait_owned_group "$MTPID"
SEED_RC=$?
MTPID=""
SEED_OPS=$(awk '$1=="Totals"{v=$2} END{print v}' "$SEEDLOG" 2>/dev/null)
if [ "$SEED_RC" -ne 0 ] || ! valid_total "${SEED_OPS:-}"; then
  emit "exact-2m-seed	FAIL	generator rc=$SEED_RC Totals=${SEED_OPS:-empty} (timeout rc=124)"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi

# DBSIZE is read through a separately bounded exact RESP parser. This proves the parallel pattern
# did not silently omit or duplicate part of the requested numeric range.
DBSIZE_OUT=$WORK/exact-2m-seed.dbsize
DBSIZE_ERR=$WORK/exact-2m-seed.dbsize.err
setsid timeout --foreground --signal=TERM --kill-after=2 "${CLIENT_TIMEOUT}s" \
  python3 - "$PORT" >"$DBSIZE_OUT" 2>"$DBSIZE_ERR" <<'PY' &
import socket, sys
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5) as s:
    s.settimeout(5)
    s.sendall(b"*1\r\n$6\r\nDBSIZE\r\n")
    data = b""
    while not data.endswith(b"\r\n") and len(data) < 128:
        chunk = s.recv(128)
        if not chunk:
            break
        data += chunk
if not data.startswith(b":") or not data.endswith(b"\r\n"):
    raise SystemExit(f"invalid DBSIZE reply: {data!r}")
print(int(data[1:-2]))
PY
CLIENT_PID=$!
wait_owned_group "$CLIENT_PID"
DBSIZE_RC=$?
CLIENT_PID=""
DBSIZE=$(tr -d '\r\n' <"$DBSIZE_OUT")
if [ "$DBSIZE_RC" -ne 0 ] || [ "$DBSIZE" != "$KEY_MAX" ]; then
  emit "exact-2m-seed	FAIL	DBSIZE=${DBSIZE:-empty} expected=$KEY_MAX rc=$DBSIZE_RC $(tr '\n' ' ' <"$DBSIZE_ERR")"
  emit "RESULT: 0 passed, 1 failed"
  exit 1
fi
emit "exact-2m-seed	PASS	keys=$KEY_MIN..$KEY_MAX dbsize=$DBSIZE value_bytes=$VALUE_BYTES load_ops=$SEED_OPS"

PY_RC=0
setsid timeout --foreground --signal=TERM --kill-after=5 "${DRIVER_TIMEOUT}s" \
taskset -c "$LOAD_CORES" python3 - "$OUT" "$PORT" "${SMOKE:-0}" <<'PY' &
import socket, sys, random, struct
out, port, smoke = sys.argv[1], int(sys.argv[2]), sys.argv[3]=="1"
R = (lambda n: max(1, n//5)) if smoke else (lambda n: n)
res=[]
def rec(name, ok, detail=""): res.append((name, "PASS" if ok else "FAIL", detail))
try: s=socket.create_connection(("127.0.0.1",port)); s.settimeout(30)
except Exception as e:
    row=f"boot\tFAIL\t{e}\n"
    open(out,"a").write(row)
    print(row, end="")
    raise SystemExit(2)
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
matched=stale=0
for p in d.split(b"+OK\r\n")[1:]:
    m=re.match(rb"\*2\r\n\$1\r\nA\r\n\$\d+\r\n([A-Z]+)\r\n",p)
    if m:
        matched += 1
        if m.group(1) != b"NEW":
            stale += 1
rec(
    "pipeline-ordering-nonfirst-key",
    matched == N and stale == 0,
    f"matched={matched}/{N},stale={stale}",
)

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

# 12. SAME-SHARD RENAME of a NON-STRING value (Guru Meditation "Not implemented" #object.c:
#     under FLATSTORE dbDelete does NOT drop the db's reference synchronously — the node is
#     QSBR-retired — so renameGenericCommand's `incrRefCount(o); dbDelete(src); dbAddInternal(dst)`
#     reaches kvobjSetEx() with refcount==2, and a collection had no re-homing branch there =>
#     serverPanic, process dead. `SADD s m1; RENAME s d` killed the server. Same class as the
#     setExpireByLink fix (check 8b); the fix passes KVOBJ_SET_MOVE_VALUE.
#     The same-shard case is FORCED, not hoped for: the keys of each case share one 14-bit tomo
#     BUCKET (xxh64(key) & 16383), and worker == ex_bucket_table[bucket], so an equal bucket means
#     the same owning worker for ANY worker count and any table state (incl. after a rebalance or
#     reshard). A random pair is same-shard only 1/W of the time, and a CROSS-shard rename takes
#     the 2-hop coordinator path, which never reaches this code — that is exactly how a
#     "RENAME works fine" test can certify a binary that dies on the third command.
#     Check 9's rename case could NEVER see it: it renames a STRING (which has the INT/RAW copy
#     branches above the panic) between indexed keys that are usually cross-shard.
_P1=0x9E3779B185EBCA87; _P2=0xC2B2AE3D27D4EB4F; _P3=0x165667B19E3779F9
_P4=0x85EBCA77C2B2AE63; _P5=0x27D4EB2F165667C5; _M=(1<<64)-1
def _rl(x,r): return ((x<<r)|(x>>(64-r)))&_M
def _rn(a,i): a=(a+i*_P2)&_M; a=_rl(a,31); return (a*_P1)&_M
def _mg(a,v): v=_rn(0,v); a^=v; return ((a*_P1)+_P4)&_M
def _xxh64(b):   # seed 0; byte-identical to src/server.c xxh64() (validated vs the C code)
    n=len(b); i=0
    if n>=32:
        v1=(_P1+_P2)&_M; v2=_P2; v3=0; v4=(0-_P1)&_M
        while n-i>=32:
            for j in range(4):
                w=struct.unpack_from("<Q",b,i)[0]; i+=8
                if j==0: v1=_rn(v1,w)
                elif j==1: v2=_rn(v2,w)
                elif j==2: v3=_rn(v3,w)
                else: v4=_rn(v4,w)
        h=(_rl(v1,1)+_rl(v2,7)+_rl(v3,12)+_rl(v4,18))&_M
        h=_mg(h,v1); h=_mg(h,v2); h=_mg(h,v3); h=_mg(h,v4)
    else: h=_P5
    h=(h+n)&_M
    while n-i>=8:
        h^=_rn(0,struct.unpack_from("<Q",b,i)[0]); h=((_rl(h,27)*_P1)+_P4)&_M; i+=8
    if n-i>=4:
        h^=(struct.unpack_from("<I",b,i)[0]*_P1)&_M; h=((_rl(h,23)*_P2)+_P3)&_M; i+=4
    while i<n:
        h^=(b[i]*_P5)&_M; h=(_rl(h,11)*_P1)&_M; i+=1
    h^=h>>33; h=(h*_P2)&_M; h^=h>>29; h=(h*_P3)&_M; h^=h>>32
    return h
def _sameshard(prefix, want):
    """`want` keys that share ONE bucket => one owning worker, by construction."""
    seen={}
    for i in range(400000):
        k=f"{prefix}:{i}"; b=_xxh64(k.encode())&16383
        seen.setdefault(b,[]).append(k)
        if len(seen[b])==want: return seen[b]
    raise RuntimeError("no same-bucket group for "+prefix)

rnbad=[]; rnalive=False; rnforced=0
try:
    rn=RR(port)
    #  tag,        create,                                   readback,                    expect,          mutate,                      expect2
    T=[("set-lp",  lambda k:("SADD",k,"a","b","c"),          lambda k:("SMEMBERS",k),     [b"a",b"b",b"c"],lambda k:("SADD",k,"zz"),    [b"a",b"b",b"c",b"zz"]),
       ("set-int", lambda k:("SADD",k,1,2,3),                lambda k:("SMEMBERS",k),     [b"1",b"2",b"3"],lambda k:("SADD",k,9),       [b"1",b"2",b"3",b"9"]),
       ("set-ht",  lambda k:tuple(["SADD",k]+[f"m{i}" for i in range(300)]), lambda k:("SCARD",k), 300,   lambda k:("SADD",k,"tail"),  301),
       ("list",    lambda k:("RPUSH",k,"v1","v2","v3"),      lambda k:("LRANGE",k,0,-1),  [b"v1",b"v2",b"v3"], lambda k:("RPUSH",k,"v4"), [b"v1",b"v2",b"v3",b"v4"]),
       ("hash",    lambda k:("HSET",k,"f1","a","f2","b"),    lambda k:("HGETALL",k),      [b"a",b"b",b"f1",b"f2"], lambda k:("HSET",k,"f3","c"), [b"a",b"b",b"c",b"f1",b"f2",b"f3"]),
       ("zset",    lambda k:("ZADD",k,1,"z1",2,"z2"),        lambda k:("ZRANGE",k,0,-1),  [b"z1",b"z2"],   lambda k:("ZADD",k,3,"z3"),  [b"z1",b"z2",b"z3"]),
       ("stream",  lambda k:("XADD",k,"1-1","f","v"),        lambda k:("XLEN",k),         1,               lambda k:("XADD",k,"2-2","f","v"), 2)]
    for tag,create,readb,want,mutate,want2 in T:
        a,b,d = _sameshard("rnss"+tag, 3)
        rnforced += 1
        rn.pipe([("DEL",a,b,d)])
        # (i) plain same-shard rename, then MUTATE the moved value and read it back
        r=rn.pipe([create(a),("RENAME",a,b),("EXISTS",a),readb(b),mutate(b),readb(b)])
        if r[1]!=b"OK" or r[2]!=0 or S(r[3])!=S(want) or S(r[5])!=S(want2):
            rnbad.append(tag+"-rename")
        # (ii) rename onto an EXISTING destination (overwrite), dest is a string
        r=rn.pipe([("DEL",a),create(a),("SET",d,"old"),("RENAME",a,d),("TYPE",d),readb(d)])
        if r[3]!=b"OK" or r[4]==b"string" or S(r[5])!=S(want): rnbad.append(tag+"-overwrite")
        # (iii) RENAMENX: taken dest => 0 and NO move; free dest => 1
        r=rn.pipe([("DEL",a,b),create(a),("RENAMENX",a,d),("EXISTS",a),
                   ("DEL",d),("RENAMENX",a,b),("EXISTS",a),readb(b)])
        if r[2]!=0 or r[3]!=1 or r[5]!=1 or r[6]!=0 or S(r[7])!=S(want): rnbad.append(tag+"-renamenx")
        # (iv) rename a key WITH a TTL: combines this move with the setExpireByLink move
        r=rn.pipe([("DEL",a,d),create(a),("EXPIRE",a,4242),("RENAME",a,d),("TTL",d),readb(d),
                   ("PERSIST",d),("EXPIRE",d,4343),("TTL",d)])
        if r[2]!=1 or not (4000 < r[4] <= 4242) or S(r[5])!=S(want) or not (4000 < r[8] <= 4343):
            rnbad.append(tag+"-ttl")
        # (v) chain a->b->d: the 2nd hop re-moves an already-moved value
        r=rn.pipe([("DEL",a,b,d),create(a),("RENAME",a,b),("RENAME",b,d),("EXISTS",b),readb(d)])
        if r[4]!=0 or S(r[5])!=S(want): rnbad.append(tag+"-chain")
        rn.pipe([("DEL",a,b,d)])
    rnalive = rn.pipe([("PING",)])[0]==b"PONG"
except Exception as e:
    rnbad.append(f"server-died({type(e).__name__})")
rec("rename-nonstring-sameshard", rnalive and not rnbad,
    f"forced={rnforced},alive={int(rnalive)},bad={','.join(rnbad) or '-'}")

rows="".join(f"{n}\t{v}\t{d}\n" for n,v,d in res)
open(out,"a").write(rows)
print(rows, end="")
PY
CLIENT_PID=$!
wait_owned_group "$CLIENT_PID"
PY_RC=$?
CLIENT_PID=""
# STRESS-ORDERING: re-run the ordering check WHILE the server is under churn — the P0 stale-read
# bug was load-dependent, so a quiescent check alone is not sufficient evidence.
if [ "$PY_RC" -ne 0 ]; then
  emit "correctness-driver	FAIL	exited $PY_RC before all checks completed"
  emit "ordering-under-load	FAIL	main correctness run did not complete"
else
  MTLOG=$WORK/ordering-load.memtier
  setsid timeout --foreground --signal=TERM --kill-after=5 "${LOAD_TIMEOUT}s" \
    taskset -c "$LOAD_CORES" memtier_benchmark -s 127.0.0.1 -p "$PORT" --hide-histogram \
    --test-time=25 --ratio=1:1 -d "$VALUE_BYTES" --key-pattern=R:R \
    --key-minimum="$KEY_MIN" --key-maximum="$KEY_MAX" -t 8 -c 25 --pipeline 16 \
    --distinct-client-seed --connection-timeout=5 --connection-stage-timeout=15 \
    >"$MTLOG" 2>&1 &
  MTPID=$!
  LOAD_OVERLAP=0
  MT_STATE=
  ORD_FILE=$WORK/ordering-under-load.out
  LOAD_READY_FILE=$WORK/ordering-load.ready
  setsid timeout --foreground --signal=TERM --kill-after=2 15s \
    taskset -c "$LOAD_CORES" python3 - "$PORT" >"$LOAD_READY_FILE" 2>&1 <<'PY' &
import socket, sys, time
port = int(sys.argv[1])

def info_sample():
    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.settimeout(2)
        sock.sendall(b"*1\r\n$4\r\nINFO\r\n")
        stream = sock.makefile("rb")
        if stream.read(1) != b"$":
            raise RuntimeError("INFO did not return bulk")
        length = int(stream.readline()[:-2])
        payload = stream.read(length)
        if len(payload) != length or stream.read(2) != b"\r\n":
            raise RuntimeError("truncated INFO")
    fields = {}
    for line in payload.splitlines():
        if b":" in line and not line.startswith(b"#"):
            key, value = line.split(b":", 1)
            fields[key] = value
    # In custom-IO mode `connected_clients` is the list local to whichever IO thread accepted
    # this INFO connection, not a process total. At 2x8 IO, requiring that one list to contain 20
    # of memtier's 25 clients can never arm. Sum the authoritative per-IO rows emitted by INFO;
    # retain the upstream field only as a fallback for a non-custom fixture.
    io_clients = []
    for key, value in fields.items():
        if not key.startswith(b"tomo_io_thread_"):
            continue
        client_field = value.split(b",", 1)[0]
        if client_field.startswith(b"clients="):
            io_clients.append(int(client_field.split(b"=", 1)[1]))
    connected = sum(io_clients) if io_clients else int(fields[b"connected_clients"])
    return connected, int(
        fields[b"total_commands_processed"]
    )

deadline = time.monotonic() + 12
previous = None
while time.monotonic() < deadline:
    connected, commands = info_sample()
    if previous is not None and connected >= 20 and commands - previous >= 100:
        print(
            f"aggregate_clients={connected} "
            f"commands_delta={commands - previous}"
        )
        raise SystemExit(0)
    previous = commands
    time.sleep(.2)
raise SystemExit("memtier did not establish active concurrent command flow")
PY
  CLIENT_PID=$!
  wait_owned_group "$CLIENT_PID"
  LOAD_READY_RC=$?
  CLIENT_PID=""
  if [ "$LOAD_READY_RC" -eq 0 ] && ! kill -0 "$MTPID" 2>/dev/null; then
    LOAD_READY_RC=1
    printf '%s\n' "generator exited before ordering probe launch" >>"$LOAD_READY_FILE"
  fi
  if [ "$LOAD_READY_RC" -eq 0 ]; then
    setsid timeout --foreground --signal=TERM --kill-after=5 "${ORDER_TIMEOUT}s" \
      taskset -c "$LOAD_CORES" env TOMO_BIN="$BIN" LBL="under-load" \
      EXTRA="${TOMO_XTRA:-}" PORT_OVERRIDE="$PORT" \
      "$(dirname "${BASH_SOURCE[0]}")"/ord_test.sh >"$ORD_FILE" 2>&1 &
    CLIENT_PID=$!
    wait_owned_group "$CLIENT_PID"
    ORD_RC=$?
    CLIENT_PID=""
    ORD_OUT=$(tr '\n' ' ' <"$ORD_FILE")
    MT_STATE=$(ps -o stat= -p "$MTPID" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$MT_STATE" ] && [[ "$MT_STATE" != *Z* ]]; then
      LOAD_OVERLAP=1
    else
      printf '%s\n' \
        "generator was not live when ordering probe completed (state=${MT_STATE:-missing})" \
        >>"$LOAD_READY_FILE"
    fi
  else
    ORD_RC=125
    ORD_OUT="load readiness failed: $(tr '\n' ' ' <"$LOAD_READY_FILE")"
  fi
  wait_owned_group "$MTPID"
  MT_RC=$?
  MTPID=""
  MT_OPS=$(awk '$1=="Totals"{v=$2} END{print v}' "$MTLOG" 2>/dev/null)
  if [ "$LOAD_READY_RC" -ne 0 ]; then
      emit "ordering-under-load	FAIL	$ORD_OUT"
  elif [ "$LOAD_OVERLAP" -ne 1 ]; then
      emit "ordering-under-load	FAIL	ordering probe outlived concurrent generator: $(tr '\n' ' ' <"$LOAD_READY_FILE")"
  elif [ "$MT_RC" -ne 0 ] || ! valid_total "${MT_OPS:-}"; then
      emit "ordering-under-load	FAIL	load did not materialize (memtier exit=$MT_RC, Totals=${MT_OPS:-empty}; timeout rc=124)"
  else
      if [ "$ORD_RC" -eq 0 ] &&
         printf '%s\n' "$ORD_OUT" | grep -qE 'checked=6000 stale=0 => PASS'; then
        emit "ordering-under-load	PASS	$ORD_OUT load_ops=$MT_OPS"
      elif [ "$ORD_RC" -ne 0 ]; then
        emit "ordering-under-load	FAIL	probe exited $ORD_RC: $ORD_OUT"
      else
        emit "ordering-under-load	FAIL	stale or zero checked replies: $ORD_OUT"
      fi
  fi
fi

CRASHES=$(grep -Eic \
  'serverAssert|ASSERTION FAILED|(^|[^[:alpha:]])assert(ion|ed)?([^[:alpha:]]|$)|(^|[^[:alpha:]])panic([^[:alpha:]]|$)|(^|[^[:alpha:]])fatal([^[:alpha:]]|$)|[[:alpha:]]+Sanitizer|Sanitizer:|runtime error:|Guru Meditation|REDIS BUG REPORT|crashed by signal|segmentation fault|Aborted \(core dumped\)|core dumped|SIG(SEGV|ABRT|BUS|ILL)' \
  "$LOG" 2>/dev/null) || true
CRASHES=${CRASHES:-0}
if [ "$CRASHES" -gt 0 ]; then
  emit "crash-markers	FAIL	$CRASHES"
elif [ "$PY_RC" -eq 0 ]; then
  emit "crash-markers	PASS	0"
else
  emit "crash-markers	FAIL	main correctness run did not complete"
fi

cleanup_correctness
PASS_COUNT=$(grep -c $'\tPASS\t' "$OUT" 2>/dev/null) || true
FAIL_COUNT=$(grep -c $'\tFAIL\t' "$OUT" 2>/dev/null) || true
SKIP_COUNT=$(grep -c $'\tSKIP\t' "$OUT" 2>/dev/null) || true
PASS_COUNT=${PASS_COUNT:-0}
FAIL_COUNT=${FAIL_COUNT:-0}
SKIP_COUNT=${SKIP_COUNT:-0}
emit "RESULT: $PASS_COUNT passed, $FAIL_COUNT failed"
# stdout only (never $OUT): a per-run work dir nobody can name is a postmortem dead end.
echo "correctness-workdir: $WORK  (server log: $LOG, result file: $OUT)"
if [ "$FAIL_COUNT" -gt 0 ] || [ "$PY_RC" -ne 0 ]; then
  exit 1
elif [ "$SKIP_COUNT" -gt 0 ]; then
  exit 2
else
  exit 0
fi
