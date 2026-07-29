#!/bin/bash
# POSTMERGE — the three checks that run after EVERY merge, fix, or change.
#
#   usage:  postmerge.sh <binary> [acceptance-script [args...]]
#
# Owner protocol, 2026-07-29:
#   "just do quick benches after each merge or fix or change. one to check if the code actually
#    fixes things, one to check 4 4 at p32 and 7 1 at p1 for regression both d32"
#
#   1. ACCEPTANCE  — does this change actually fix the thing it was written for?
#   2. io4/ex4 p32 d32 — throughput-bound regression check (the canonical config)
#   3. io7/ex1 p1  d32 — latency-bound regression check (front-heavy, 1 worker)
#
# WHY THESE TWO CONFIGS AND NOT A SWEEP. They bracket the two regimes that behave OPPOSITELY here:
# p32/io4ex4 is throughput-bound with FLATSTORE live (shared_node_dbs true at ex>=2); p1/io7ex1 is
# latency-bound and DICT-backed (shared_node_dbs is FALSE at ex=1, so the keyspace is a different
# engine). A regression that hides in one is usually visible in the other — a real -5.5% once showed
# up ONLY at io7/ex1, and was then mis-attributed to the obvious suspect. Two cheap cells catch the
# class; a full sweep costs 90 minutes and is not the per-change tool.
#
# COST: ~4 minutes total. That is the point. Per-change checks are meant to be short and
# discriminating; the LONG suite runs after a BATCH of merges, because per-change tests validate
# changes in isolation and structurally cannot see interaction.
set -u
BIN=${1:?usage: postmerge.sh <binary> [acceptance-script [args...]]}
shift
ACC=${1:-}; [ $# -gt 0 ] && shift || true

J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
OUT=$J/postmerge.out
BASE=${POSTMERGE_BASE:-$J/postmerge_baseline.tsv}
TT=${TT:-20}
PORT=7997
TAG=redis-pm                      # PRIVATE name: never reap a shared one, never be reaped by one
SRV=$J/$TAG
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
KM="--key-maximum=2000000 -d 32"
: > "$OUT"
cp -f "$BIN" "$SRV" || { echo "postmerge: cannot stage $BIN" | tee -a "$OUT"; exit 2; }

say(){ echo "$*" | tee -a "$OUT"; }
reap(){ pkill -9 -x "$TAG" 2>/dev/null; }
trap 'reap' EXIT TERM INT HUP

# WAIT, NEVER KILL. A contended measurement is invalid anyway (+-2% only when exclusive), so waiting
# costs nothing that killing would have saved -- and killing to make room has repeatedly destroyed
# other sessions' work on this box.
solo(){ local w=0 n m
  while :; do
    n=$(ps -eo comm= 2>/dev/null | grep -cE '^redis-'); n=$((n - $(pgrep -x "$TAG" 2>/dev/null | wc -l)))
    m=$(pgrep -x memtier_benchma 2>/dev/null | wc -l)
    [ "$n" -le 0 ] && [ "$m" -eq 0 ] && break
    [ "$w" = 0 ] && say "waiting: $n foreign server(s), $m load gen(s) -- not killing them"
    w=$((w+15)); sleep 15
    [ "$w" -ge 1800 ] && { say "ABORT: box occupied 30min; refusing to measure against contention"; return 1; }
  done; return 0; }

cell(){ # io ex pipeline ratio label
  local io=$1 ex=$2 pl=$3 ratio=$4 lab=$5 o
  reap; sleep 1
  taskset -c 0-7 "$SRV" --port $PORT --tomokv-nodes 1 --tomokv-thread-io "$io" \
    --tomokv-thread-ex "$ex" --tomokv-thread-mode static --save '' --appendonly no \
    --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 3
  $MT --ratio=1:0 $KM --key-pattern=P:P -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  o=$($MT --test-time="$TT" --ratio="$ratio" $KM --key-pattern=R:R -t 8 -c 25 \
      --pipeline "$pl" --distinct-client-seed 2>/dev/null | awk '/^Totals/{print $2}')
  reap
  # A killed server does NOT print nothing -- memtier still emits a Totals line reading 0.00, which
  # would enter the table as a real measurement of zero throughput. Reject it as INVALID.
  case "${o:-}" in ''|0|0.0|0.00) o=INVALID ;; esac
  printf '%s\t%s\n' "$lab" "$o" | tee -a "$OUT"
}

rc=0
# ---- 1. ACCEPTANCE: does it fix what it was written to fix? -----------------------------------
if [ -n "$ACC" ] && [ -x "$ACC" ]; then
  say "=== 1/3 acceptance: $(basename "$ACC") ==="
  solo || exit 1
  TOMO_BIN="$SRV" "$ACC" "$SRV" "$@" 2>&1 | tail -20 | tee -a "$OUT"
  arc=${PIPESTATUS[0]}; say "acceptance exit=$arc"; [ "$arc" != 0 ] && rc=1
else
  say "=== 1/3 acceptance: NONE SUPPLIED ==="
  say "  A change with no acceptance test is UNVALIDATED, not passing. Name the test or say"
  say "  explicitly that the change is unverifiable and why."
  rc=1
fi

# ---- 2+3. REGRESSION: the two bracketing regimes -----------------------------------------------
say "=== 2/3 io4/ex4 p32 d32 (throughput-bound, FLATSTORE live) ==="
solo || exit 1
cell 4 4 32 0:1 p32GET_io4ex4
cell 4 4 32 1:0 p32SET_io4ex4
say "=== 3/3 io7/ex1 p1 d32 (latency-bound, DICT-backed) ==="
cell 7 1 1 0:1 p1GET_io7ex1
cell 7 1 1 1:0 p1SET_io7ex1

# ---- verdict ------------------------------------------------------------------------------------
if [ ! -f "$BASE" ]; then
  grep -E '^(p32|p1)' "$OUT" > "$BASE"
  say "postmerge: BASELINE WRITTEN ($BASE). No regression verdict on a first run."
  exit $rc
fi
python3 - "$BASE" "$OUT" <<'PY' | tee -a "$OUT"
import sys
b={}; n={}
for l in open(sys.argv[1]):
    f=l.split('\t');  b[f[0]]=f[1].strip() if len(f)>1 else ''
for l in open(sys.argv[2]):
    f=l.split('\t')
    if len(f)>1 and f[0].startswith(('p32','p1')): n[f[0]]=f[1].strip()
bad=inv=0
print(f"\n{'cell':20s}{'base':>13s}{'now':>13s}{'delta':>9s}")
for k in sorted(n):
    cur,old=n[k],b.get(k)
    if cur=='INVALID' or old in (None,'INVALID'):
        print(f"{k:20s}{str(old):>13s}{cur:>13s}{'INVALID':>9s}"); inv+=1; continue
    d=(float(cur)-float(old))/float(old)*100
    print(f"{k:20s}{float(old):13.0f}{float(cur):13.0f}{d:+8.1f}%")
    # Box noise is +-2% exclusive, so -4% is ~2 sigma: below that is unresolved, not a result.
    if d < -4: bad+=1
print()
if inv: print(f"postmerge: {inv} INVALID cell(s) -- verdict unreliable, re-run them")
print("postmerge: REGRESSION" if bad else "postmerge: no regression (nothing worse than -4%)")
sys.exit(1 if bad or inv else 0)
PY
[ ${PIPESTATUS[0]} != 0 ] && rc=1
say "postmerge: exit=$rc"
exit $rc
