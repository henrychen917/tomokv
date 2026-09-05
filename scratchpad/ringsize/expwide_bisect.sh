#!/bin/bash
# REPRODUCE THE expwide S1 MGET FAILURE, AND SAY WHICH BRANCH OWNS IT.
#
# Rule: fix => reproduce FIRST. Three arms, one tree, identical boot flags, same box, same minute:
#
#   m14   every src file that differs from t-merge14, taken from t-merge14   -> expected PASS
#   pre   the base lane t-rlbatch (479922c0a)                                -> expected FAIL
#   post  this lane                                                          -> expected FAIL
#
# A three-arm run is what separates "t-rlbatch broke it" from "it was already broken and the gate
# on t-merge14 runs a different geometry". Each arm gets both instruments: the whole expwide
# battery (the gate's own verdict) and s1_mget_repro.py, which samples the read-local MGET
# counters either side of the command and can therefore say WHY the elapsed time is zero.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/scratchpad/ringsize"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
mkdir -p "$OUT"
cd "$ROOT"
source "$HERE/lib.sh"
SHARDS=16
BASE_M14="${BASE_M14:-t-merge14}"
JOBS="${JOBS:-12}"
CORES="${CORES:-58-63,186-191}"

LANE_SRC=$(git diff --name-only "$BASE_M14" HEAD -- src/)
[ -n "$LANE_SRC" ] || { echo "REFUSING: nothing differs from $BASE_M14"; exit 1; }
echo "files taken from $BASE_M14 for the m14 arm: $(echo $LANE_SRC | tr '\n' ' ')"

KEEP=$(mktemp -d /tmp/ringsize-m14-src.XXXXXX)
for f in $LANE_SRC; do mkdir -p "$KEEP/$(dirname "$f")"; cp "$f" "$KEEP/$f"; done
restore(){ local f; for f in $LANE_SRC; do cp "$KEEP/$f" "$f"; done; }
trap 'restore; rm -rf "$KEEP"' EXIT INT TERM

if [ ! -x build/tomokv-m14 ]; then
  echo "== building m14 =="
  for f in $LANE_SRC; do git show "$BASE_M14:$f" > "$f"; done
  taskset -c "$CORES" make -j"$JOBS" > "$OUT/build-m14.log" 2>&1 || { echo "m14 BUILD FAILED, see $OUT/build-m14.log"; tail -5 "$OUT/build-m14.log"; exit 1; }
  cp build/tomokv build/tomokv-m14
  restore
  echo "m14: md5=$(md5sum build/tomokv-m14 | cut -d' ' -f1)"
fi
# and put the lane's own binary back under build/tomokv
[ -x build/tomokv-post ] && cp build/tomokv-post build/tomokv

run_arm(){ # run_arm <label> <binary>
  local label="$1" bin="$2"
  [ -x "$bin" ] || { echo "$label: MISSING BINARY $bin"; return 1; }
  echo "=============== $label ($(md5sum "$bin" | cut -d' ' -f1)) ==============="
  boot_srv "$bin" "$OUT/expw-$label-srv.log" \
      --atomic 0 --enable-debug-command yes || return 1
  echo "--- directed reproduction ---"
  python3 "$HERE/s1_mget_repro.py" 127.0.0.1 "$PORT" 2>&1 | tee "$OUT/s1repro-$label.txt"
  echo "--- expwide battery, S1 rows ---"
  timeout 900 python3 tests/expwide.py 127.0.0.1 "$PORT" > "$OUT/expwide-$label.txt" 2>&1
  grep -E "^  (ok|FAIL) +S1|^expwide:" "$OUT/expwide-$label.txt" | sed 's/^/    /'
  stop_srv
  sleep 2
}

for spec in "m14:build/tomokv-m14" "pre:build/tomokv-pre" "post:build/tomokv-post"; do
  run_arm "${spec%%:*}" "${spec#*:}"
done
echo "=== done; full outputs in $OUT/expwide-{m14,pre,post}.txt ==="
