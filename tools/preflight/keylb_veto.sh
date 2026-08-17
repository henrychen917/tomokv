#!/bin/bash
# KEY-LB HOT-KEY VETO — does the balancer's strict-improvement precondition actually ENGAGE?
#
# WHY THIS EXISTS. reshardAutoTune refuses to migrate when no bucket range improves the predicted
# maximum; that refusal is the hot-KEY case (a bucket flip relocates load, it never divides it).
# Fed only per-64-bucket-GROUP counters the refusal is UNREACHABLE — the planner spreads each
# group's rate over its buckets, so the accumulator is piecewise-linear and a split point on the
# target always exists. Measured runs showed exactly that: unbal=0 while the balancer chased a
# single hot key, and what finally stopped it was the no-progress guard, one wasted migration later.
#
# The automatic per-bucket window is the fix. This script is the discriminating test for
# it, and it is deliberately built to fail the two vacuous shapes this project has shipped before:
#   * "unbal=0 and no migration happened" proves nothing — a detector that never armed produces the
#     same output. So arm=1 (fire/band/sustain counters moving) is asserted separately.
#   * "unbal>0" alone proves nothing either — the group-resolution planner might have refused too.
#     So the server computes a SHADOW plan at group resolution on every refusal and reports
#     unbal_fine = "refused on per-bucket data AND group data would have moved". That is the counter
#     this test requires to be non-zero.
set -u
# PORT-SAFETY: SO_REUSEPORT lets a leaked/foreign server on $PORT silently share this
# suite's accept group, blending two binaries into one measurement (the split is invisible
# — a bind never fails). Gate on the PORT before boot and verify pid identity after.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
BIN=${TOMO_BIN:?TOMO_BIN required}
OUT=$J/keylb_veto.out; : > $OUT
PORT=${KEYLB_PORT:-5897}
SECS=${KEYLB_SECS:-30}
CLI="$(dirname $BIN)/redis-cli"
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}

# LEAK GUARD: this is a MULTI-BOOT suite (arms A/B each boot on $PORT). Without a trap,
# any early exit — a failed arm, an interrupt, an unset var under `set -u` — leaves the
# current arm's server alive on $PORT, and the NEXT thing to boot there is silently split
# with it. Kill our recorded pid on every exit path AND sweep the private name at end-of-run.
VETO_PID=""
cleanup_veto(){
  if [ -n "${VETO_PID:-}" ]; then
    kill -TERM "$VETO_PID" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$VETO_PID" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$VETO_PID" 2>/dev/null; wait "$VETO_PID" 2>/dev/null
    VETO_PID=""
  fi
  pkill -9 -x redis-veto 2>/dev/null   # end-of-run sweep of the private name
  return 0
}
trap cleanup_veto EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

run_arm() {   # $1 = arm name, $2 = workload (hotkey|spread)
  local arm=$1 wl=$2
  pkill -9 -x redis-veto 2>/dev/null; sleep 1
  cp "$BIN" $J/redis-veto; rm -rf $J/vetodata; mkdir -p $J/vetodata; : > $J/veto_$arm.log
  # PORT-SAFETY: refuse to boot while any listener still holds $PORT — otherwise it joins
  # this arm's SO_REUSEPORT accept group and the load generator's connections split.
  wait_port_free "$PORT" || { echo "$arm-port-busy	FAIL	:$PORT still has a listener before boot (SO_REUSEPORT split risk)" >> $OUT; return 1; }
  taskset -c "$SERVER_CORES" $J/redis-veto --port $PORT --dir $J/vetodata --tomokv-nodes 2 \
    --tomokv-pin-mode ccd --tomokv-thread-io 8 --tomokv-thread-ex 8 --save '' --appendonly no --protected-mode no \
    --enable-debug-command yes --logfile $J/veto_$arm.log >/dev/null 2>&1 &
  VETO_PID=$!
  sleep 3
  # IDENTITY: N fresh INFO conns must all land on OUR pid. A second listener on $PORT would
  # answer a share of them and silently blend its binary into this arm's counters.
  server_identity_ok "$CLI" "$PORT" "$VETO_PID" || { echo "$arm-port-identity	FAIL	SO_REUSEPORT split on :$PORT" >> $OUT; $CLI -p $PORT shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-veto 2>/dev/null; VETO_PID=""; return 1; }
  preflight_assert_standard_boot "$J/veto_$arm.log" "$VETO_PID" 8 8 || { echo "$arm-pin-geometry	FAIL	standard 2x16c pin assertion failed" >> "$OUT"; return 1; }
  taskset -c "$LOAD_CORES" python3 - "$PORT" "$wl" "$SECS" "$arm" "$OUT" <<'PY'
import socket, sys, time, threading, random
port, wl, secs, arm, out = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]

def conn():
    s = socket.create_connection(("127.0.0.1", port)); s.settimeout(60); return s
def enc(*a):
    o = f"*{len(a)}\r\n".encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o
# Drain a pipelined batch by appending PING and reading until +PONG. Counting replies instead
# (e.g. occurrences of b"\r\n$") UNDERCOUNTS across recv boundaries -- the first reply in a chunk
# has no preceding CRLF in that chunk -- and the driver then blocks forever on a batch it has in
# fact fully received. That silently killed the load generator on the first attempt at this test,
# leaving every counter at zero and looking exactly like "the feature does nothing".
def drain(s):
    d = b""
    while not d.endswith(b"+PONG\r\n"): d += s.recv(1 << 20)
def one(s, *a):        # single-line reply (+status / :int / -err)
    s.sendall(enc(*a)); d = b""
    while not d.endswith(b"\r\n"): d += s.recv(1 << 20)
    return d
def bulk(s, *a):       # length-prefixed reply ($N / =N) -- DEBUG RESHARD LBFINE is multi-line, so
    s.sendall(enc(*a)) # reading "until CRLF" stops at the LENGTH HEADER and desyncs the socket
    d = b""
    while b"\r\n" not in d: d += s.recv(1 << 20)
    hdr, _, rest = d.partition(b"\r\n")
    if hdr[:1] not in (b"$", b"="): return hdr
    n = int(hdr[1:])
    if n < 0: return b""
    while len(rest) < n + 2: rest += s.recv(1 << 20)
    return rest[:n]

c = conn()
NBG = 20000                       # uniform background keyspace
HOT = "hotkey:veto:0"
# Seed: the background keys plus the hot key. GETs on missing keys still route and still count on
# the exec path, but seeding keeps the two arms' per-op costs identical to a real workload.
for lo in range(0, NBG, 2000):
    c.sendall(b"".join(enc("SET", f"bg:{i}", "x"*32) for i in range(lo, lo+2000)) + enc("PING"))
    drain(c)
one(c, "SET", HOT, "x"*32)

# Which shard owns the hot key, and (for the spread arm) a pool of keys owned by ONE shard.
def find(k):
    r = one(c, "DEBUG", "RESHARD", "FIND", k).decode()
    b = int(r.split("bucket=")[1].split()[0]); w = int(r.split("routed_ex=")[1].split()[0])
    return b, w
hot_bkt, hot_w = find(HOT)
pool = {}
for i in range(0, 4000):
    b, w = find(f"bg:{i}")
    pool.setdefault(w, []).append(f"bg:{i}")
target = max(pool, key=lambda w: len(pool[w]))
spread_keys = pool[target]

def trig():
    r = one(c, "DEBUG", "RESHARD", "TRIGGER").decode().strip().lstrip("+")
    d = {}
    for tok in r.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            try: d[k] = float(v) if "." in v else int(v)
            except ValueError: d[k] = v
    return d

stop = False
def driver(mode):
    s = conn(); B = 200
    while not stop:
        if mode == "hot":
            # 97% one key / 3% uniform. The hot key alone must exceed a fair share (total/W) or the
            # hotspot is genuinely balanceable and refusing would be the WRONG answer -- see
            # docs/lb-imbalance-model.md 4. 97% also puts the gain from moving the shard's entire
            # remaining background below the planner's worth-it margin, so the ONLY reason to fire
            # would be believing the hot bucket is divisible, which is the belief under test.
            batch = b"".join(enc("GET", HOT if random.random() < 0.97 else f"bg:{random.randrange(20000)}")
                             for _ in range(B))
        else:
            # Genuine MULTI-BUCKET skew: 90% of traffic to keys spread across ONE shard's whole
            # 4096-bucket range. Nothing is concentrated in a single bucket, so this must still
            # migrate -- the control that shows the veto is selective and not just "never move".
            batch = b"".join(enc("GET", random.choice(spread_keys) if random.random() < 0.90
                                 else f"bg:{random.randrange(20000)}")
                             for _ in range(B))
        s.sendall(batch + enc("PING"))
        drain(s)
    s.close()

t0 = trig()
ths = [threading.Thread(target=driver, args=("hot" if wl == "hotkey" else "spread",), daemon=True)
       for _ in range(12)]
for t in ths: t.start()
time.sleep(secs)
stop = True
for t in ths: t.join(timeout=10)
t1 = trig()
lbf = bulk(c, "DEBUG", "RESHARD", "LBFINE", hot_w).decode(errors="replace")

d = {k: t1.get(k, 0) - t0.get(k, 0) for k in ("ticks","quiet","balanced","band","settle","noprog",
     "fastcold","sustain","noneigh","unbal","fire","unbal_fine","unbal_grp","fine_used","fine_arm",
     "fine_ticks")}
sig = {k: t1.get(k, 0) for k in ("hot","hotv","mean","hot_bar","fine_grp","fine_top","fine_peak",
                                 "K")}
with open(out, "a") as f:
    f.write(f"# ARM {arm} ({wl}) hot_key_bucket={hot_bkt} owner_w={hot_w} spread_target_w={target}\n")
    f.write("# delta " + " ".join(f"{k}={v}" for k, v in d.items()) + "\n")
    f.write("# signal " + " ".join(f"{k}={v}" for k, v in sig.items()) + "\n")
    f.write("# lbfine " + lbf.replace("\r\n", " | ")[:400] + "\n")
    armed = d["ticks"] > 0 and (d["fire"] + d["unbal"] + d["sustain"] + d["band"]) > 0
    f.write(f"{arm}-detector-armed\t{'PASS' if armed else 'FAIL'}\t"
            f"ticks={d['ticks']} sustain={d['sustain']} band={d['band']}\n")
    if arm == "A":
        # The veto must engage, AND it must be the per-bucket resolution that produced the refusal.
        f.write(f"A-hotkey-veto-engaged\t{'PASS' if d['unbal_fine'] > 0 else 'FAIL'}\t"
                f"unbal_fine={d['unbal_fine']} unbal={d['unbal']} unbal_grp={d['unbal_grp']} "
                f"fire={d['fire']}\n")
        f.write(f"A-window-armed\t{'PASS' if d['fine_used'] > 0 and sig['fine_grp'] >= 0 else 'FAIL'}\t"
                f"fine_used={d['fine_used']} fine_arm={d['fine_arm']} fine_grp={sig['fine_grp']}\n")
    if arm == "B":
        f.write(f"B-multibucket-still-migrates\t{'PASS' if d['fire'] > 0 else 'FAIL'}\t"
                f"fire={d['fire']} unbal={d['unbal']} unbal_fine={d['unbal_fine']}\n")
PY
  $CLI -p $PORT shutdown nosave >/dev/null 2>&1; sleep 1
  pkill -9 -x redis-veto 2>/dev/null
  wait "$VETO_PID" 2>/dev/null; VETO_PID=""   # reap + clear so the trap can't touch a recycled pid
  local cm; cm=$(grep -cE 'Guru|crashed by signal|ASSERTION' $J/veto_$arm.log 2>/dev/null); cm=${cm:-0}
  [ "$cm" = 0 ] && echo "$arm-crash-markers	PASS	0" >> $OUT || echo "$arm-crash-markers	FAIL	$cm" >> $OUT
}

run_arm A hotkey
run_arm B spread

echo "RESULT: $(grep -cw PASS $OUT) passed, $(grep -cw FAIL $OUT) failed" >> $OUT
cat $OUT
grep -qw FAIL $OUT && exit 1 || exit 0
