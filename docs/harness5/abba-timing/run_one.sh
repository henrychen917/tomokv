#!/bin/bash
# run_one.sh ARM GEOMETRY INDEX — one abba_selftest row through tests/gate.sh's job interface.
#   ARM: before = /home/user/Projects/cx-harness5/build/harness5-baseline (3700b51d7)
#        after  = /home/user/Projects/cx-harness5 (this branch)
#   GEOMETRY: L = landing-like: 14 server + 2 load cores; the slot uses 32-39 + 46-47 and the 6 unused
#             server cores 40-45 are burned (wave7b: neighbours busy, the slot's own cores free);
#             I = isolated: 8 server + 8 load cores, no contention.
# The per-test observer (docs/harness5/observe/sitecustomize.py) only times; it changes no assertion.
set -u
ARM=$1; GEO=$2; IDX=$3
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/timing
case "$ARM" in
  before) TREE=/home/user/Projects/cx-harness5/build/harness5-baseline;;
  after) TREE=/home/user/Projects/cx-harness5;;
  *) echo "bad arm" >&2; exit 2;;
esac
case "$GEO" in
  L) SERVER=32-45; LOAD=46-47; BURN=40-45;;  # slot = 32-39 + 46-47 (wave7b: neighbours busy, own slot free)
  I) SERVER=32-39; LOAD=40-47; BURN=;;
  *) echo "bad geometry" >&2; exit 2;;
esac
O=$S/$GEO-$ARM-$IDX; mkdir -p "$O"
git -C "$TREE" rev-parse HEAD > "$O/tree-head"; git -C "$TREE" status --short > "$O/tree-status"
STOP=$O/stop; rm -f "$STOP"; BPID=
if [ -n "$BURN" ]; then
  python3 $S/burn.py "$STOP" --cpus "$BURN" > "$O/burn.log" 2>&1 & BPID=$!
  sleep 1
fi
start=$(date +%s.%N)
( cd "$TREE" && GATE_ONLY_JOBS=abba_selftest GATE_TEST_PORT=45800 REDIS74_ROOT=/home/user/Projects/redis \
    PYTHONPATH=/home/user/Projects/cx-harness5/docs/harness5/observe HARNESS5_TIMINGS="$O/timings" \
    GATE_LEDGER="$O/ledger" bash tests/gate.sh quick --server-cores "$SERVER" --load-cores "$LOAD" \
    --server-smt "" --load-smt "" --ports 45800-45819 > "$O/gate.log" 2>&1 ); rc=$?
end=$(date +%s.%N)
touch "$STOP"; [ -z "$BPID" ] || wait "$BPID"
row=$(grep -h 'ABBA comparison + saturation negative controls' "$O/ledger.partial" 2>/dev/null | cut -f1,2 | tr '\t' ' ')
echo "$GEO $ARM $IDX gate_rc=$rc row=[$row] wall=$(awk -v a=$start -v b=$end 'BEGIN{printf "%.1f", b-a}')" | tee -a $S/summary.txt
