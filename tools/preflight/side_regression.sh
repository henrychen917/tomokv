#!/bin/bash
# SIDE-ATTRIBUTED REGRESSION GATE — does a regression live on the IO side or the EX side?
#
# WHY THIS EXISTS. On 2026-07-28 a 5.5% regression was invisible at the balanced io4/ex4 config and
# only appeared at io7/ex1. Worse, it was MIS-ATTRIBUTED: the obvious suspect (a newly added
# per-command clock read) fit the story, and the real cause was a deleted dict-prefetch stage that
# is live only when ex=1 leaves the keyspace dict-backed. A balanced-only gate would have shipped
# it; a gate that reports WHICH SIDE moved would have pointed at the EX side immediately.
#
# THE IDEA. Run the same workload at two deliberately lopsided thread splits and compare each
# against its own baseline. The PAIR of deltas localises the fault:
#
#   io-heavy regressed (io7/ex1), ex-heavy flat   -> the fault is on the EX/worker side.
#        io7/ex1 has ONE worker, so per-command worker cost is fully exposed and cannot be
#        absorbed by spare worker capacity. Suspects: dispatch, command exec, kvstore, per-command
#        bookkeeping, anything gated on shared_node_dbs (which is FALSE at ex=1 -- the keyspace is
#        DICT-backed there, so dict-path code is live in this config and dead in the others).
#
#   ex-heavy regressed (io1/ex7), io-heavy flat   -> the fault is on the IO/front side.
#        io1/ex7 has ONE io thread. Suspects: parsing, reply assembly, the event loop, the
#        wake/drain path, per-connection work, anything in networking.c.
#
#   BOTH regressed                                -> shared or global: allocator, a lock, a
#        cross-thread cache line, or something on every path regardless of side.
#
#   NEITHER regressed but balanced did            -> an interaction that only appears when both
#        sides are loaded; look at handoff (queues, reply buses, cs_barrier).
#
# METRIC IS ops/s. instr/op is NOT usable here: the workers busy-spin (exPauseCpu), so a
# process-wide instruction count partly tracks idle time rather than work.
#
# Usage: side_regression.sh <binary> [baseline.tsv]
#   Writes a baseline if none exists (first run establishes it, reports NO VERDICT).
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
# ee451 2026-07-29: accept the binary from EITHER a positional arg OR $TOMO_BIN.
# preflight.sh run_suite (preflight.sh:85) invokes suites as `TOMO_BIN="$BIN" ... "$1"` with NO
# positional argument, but this line was `BIN=${1:?...}` -- so the script died on line 1 with a
# usage error, never wrote its .out file, and preflight graded it "produced no result file".
# This suite has therefore NEVER EXECUTED under preflight. Fixing the flip_updown exit code was
# necessary but not sufficient: the verdict logic was never even reached.
BIN=${1:-${TOMO_BIN:?usage: side_regression.sh <redis-server binary> [baseline.tsv]  (or TOMO_BIN=...)}}
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BASE=${2:-$J/side_regression_baseline.tsv}
OUT=$J/side_regression.out
TT=${TT:-30}
PORT=7875
TOL=${TOL:-4}      # percent; box noise is ~+-2% exclusive, so 4% is ~2 sigma
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
KM="--key-maximum=2000000 -d 32"
: > "$OUT"

cell(){ # io ex pipeline ratio label
  local io=$1 ex=$2 pl=$3 ratio=$4 lab=$5
  pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; sleep 1
  taskset -c 0-7 "$BIN" --port $PORT --tomokv-nodes 1 --tomokv-thread-io "$io" \
    --tomokv-thread-ex "$ex" --tomokv-thread-mode static --save '' --appendonly no \
    --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 3
  $MT --ratio=1:0 $KM --key-pattern=P:P -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  local o
  o=$($MT --test-time="$TT" --ratio="$ratio" $KM --key-pattern=R:R -t 8 -c 25 \
      --pipeline "$pl" --distinct-client-seed 2>/dev/null | awk '/^Totals/{print $2}')
  pkill -9 -x "$(basename "${BIN}")" 2>/dev/null
  # A dead or wedged server must not silently score 0 and read as a huge regression -- or worse,
  # be averaged in. Report it as DEAD so the verdict says "invalid cell", not "-100%".
  [ -z "$o" ] && o=DEAD
  printf '%s\t%s\t%s\n' "io${io}ex${ex}" "$lab" "$o"
}

run_all(){
  for cfg in "7 1:IO-HEAVY" "1 7:EX-HEAVY"; do
    local spec=${cfg%%:*}; set -- $spec; local io=$1 ex=$2
    cell "$io" "$ex" 32 0:1 p32GET
    cell "$io" "$ex" 32 1:0 p32SET
    cell "$io" "$ex" 1  0:1 p1GET
    cell "$io" "$ex" 1  1:0 p1SET
  done
}

NOW=$(run_all)
echo "$NOW" | tee -a "$OUT" >/dev/null

if [ ! -f "$BASE" ]; then
  echo "$NOW" > "$BASE"
  { echo "side_regression: BASELINE WRITTEN to $BASE ($(echo "$NOW" | wc -l) cells)"
    echo "side_regression: NO VERDICT on a first run -- re-run against this baseline to gate."; } | tee -a "$OUT"
  exit 0
fi

python3 - "$BASE" "$OUT" "$TOL" <<'PY' | tee -a "$OUT"
import sys
base, out, tol = sys.argv[1], sys.argv[2], float(sys.argv[3])
def load(p):
    d = {}
    for l in open(p):
        f = l.rstrip('\n').split('\t')
        if len(f) == 3 and f[2] not in ('', 'ops'):
            d[(f[0], f[1])] = f[2]
    return d
b, n = load(base), load(out)
sides = {'io7ex1': 'IO-HEAVY (1 worker: EX-side cost exposed)',
         'io1ex7': 'EX-HEAVY (1 io thread: IO-side cost exposed)'}
regressed, dead = {}, []
print(f"\n{'config':9s} {'op':8s} {'baseline':>12s} {'now':>12s} {'delta':>8s}")
for k in sorted(n):
    cur, old = n[k], b.get(k)
    if cur == 'DEAD' or old in (None, 'DEAD'):
        dead.append(k); print(f"{k[0]:9s} {k[1]:8s} {str(old):>12s} {cur:>12s} {'INVALID':>8s}")
        continue
    d = (float(cur) - float(old)) / float(old) * 100
    print(f"{k[0]:9s} {k[1]:8s} {float(old):12.0f} {float(cur):12.0f} {d:+7.1f}%")
    if d < -tol: regressed.setdefault(k[0], []).append((k[1], d))
print()
if dead:
    print(f"side_regression: {len(dead)} INVALID cell(s) (dead/wedged server) -- verdict is unreliable")
if not regressed:
    print(f"side_regression: PASS (no cell worse than -{tol}%)"); sys.exit(0 if not dead else 2)
hit = set(regressed)
print("side_regression: FAIL")
for c, items in regressed.items():
    print(f"  {sides.get(c, c)}")
    for op, d in items: print(f"    {op} {d:+.1f}%")
if hit == {'io7ex1'}:
    print("\n  ATTRIBUTION: EX/WORKER side. io7ex1 runs ONE worker, so per-command worker cost is")
    print("  fully exposed. Look at dispatch, command exec, kvstore, per-command bookkeeping --")
    print("  and note shared_node_dbs is FALSE at ex=1, so DICT-path code is live in this config")
    print("  and dead in the others (that asymmetry caused a real mis-attribution on 2026-07-28).")
elif hit == {'io1ex7'}:
    print("\n  ATTRIBUTION: IO/FRONT side. io1ex7 runs ONE io thread. Look at parsing, reply")
    print("  assembly, the event loop, the wake/drain path, per-connection work, networking.c.")
else:
    print("\n  ATTRIBUTION: SHARED/GLOBAL -- both sides moved. Look at the allocator, a lock, a")
    print("  cross-thread cache line, or work done on every path regardless of side.")
sys.exit(1)
PY
