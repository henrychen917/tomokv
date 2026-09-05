#!/bin/bash
# Instructions and cycles per REJECTED read probe, by ring shape and by how many writes are live.
#
# Three arms, all compiled from this worktree at the server's own flags:
#   base16    the base branch's sixteen-slot ring and inline tag mirror
#   flat64    this lane's ring with the sweep written as one flat sixty-four-lane loop -- the shape
#             GCC leaves as a scalar 64-trip loop, and the shape a first draft of this lane shipped
#   grouped64 what this lane ships: four sixteen-lane blocks with an empty-block skip
#
# Read the base16 rows against the grouped64 rows at the SAME live count: that difference is what a
# disjoint read pays for the bigger ring, and it is the cost this lane has to justify. Read the
# base16 row at live=19 for the other half of the story -- sixteen slots cannot hold nineteen live
# writes, so it is not paying less, it is in a conservative generation walking everything.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/scratchpad/ringsize"
BASE="${BASE:-479922c0a}"
CORE="${CORE:-58}"
ITERS="${ITERS:-20000000}"
CXXF="-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -I."
cd "$ROOT"
# EVERY LANE FILE IS SWAPPED FOR THE BASE ARM, NOT JUST rob.h -- the same lesson build_arms.sh
# already carries, and this script did not. This lane moved kRobWindow out of src/net/conn.h into
# src/net/rob.h, so a base rob.h beside this tree's conn.h defines that constant nowhere: the
# base16 arm stopped compiling the moment the constant moved, and printed a compiler error where a
# table row belonged. The list is COMPUTED from the diff for the same reason it is there -- a
# hand-written one goes stale exactly when the tree changes shape.
LANE_SRC=$(git diff --name-only "$BASE" -- src/)
[ -n "$LANE_SRC" ] || { echo "REFUSING: no src/ file differs from $BASE"; exit 1; }
KEEP=$(mktemp -d /tmp/ringsize-pc-src.XXXXXX)
for f in $LANE_SRC; do mkdir -p "$KEEP/$(dirname "$f")"; cp "$f" "$KEEP/$f"; done
restore_src(){ local f; for f in $LANE_SRC; do cp "$KEEP/$f" "$f"; done; }
trap 'restore_src; rm -rf "$KEEP"' EXIT INT TERM

# A FAILED BUILD IS A FAILED PHASE, not a row of compiler output where a measurement belonged. The
# base16 arm printed sixty lines of errors into the results file and the script carried on to the
# next arm, so the table read as two arms out of three with no line saying the third had died.
build(){ g++ $CXXF "$HERE/probe_cost.cc" -o "/tmp/ringsize-pc-$1" || {
    echo "BUILD FAILED for arm '$1' -- this phase produces no table"; exit 1; }; }

measure(){ # measure <arm> <live>
  local arm="$1" live="$2" pf out ins cyc
  pf=$(mktemp /tmp/ringsize-pc-perf.XXXXXX)
  out=$(perf stat -e instructions:u,cycles:u -x, -o "$pf" -- \
        taskset -c "$CORE" "/tmp/ringsize-pc-$arm" "$live" "$ITERS" 2>/dev/null)
  ins=$(grep -m1 ',instructions:u,' "$pf" | cut -d, -f1)
  cyc=$(grep -m1 ',cycles:u,' "$pf" | cut -d, -f1)
  rm -f "$pf"
  # The loop is the overwhelming majority of the program; the fixed setup is under a microsecond
  # against twenty million iterations, so no slope is needed to read this to a tenth.
  python3 -c "
print(f'  {\"$arm\":<10} live={$live:<3} {$ins/$ITERS:7.2f} instr/probe  {$cyc/$ITERS:7.2f} cyc/probe  {$ins/max(1,$cyc):5.2f} IPC   $out')"
}

echo "== base16 (the base branch's sixteen-slot ring) =="
for f in $LANE_SRC; do git show "$BASE:$f" > "$f"; done
build base16
restore_src
for n in 1 4 9 15 19; do measure base16 "$n"; done

echo "== flat64 (this lane's ring, flat sixty-four-lane sweep -- REJECTED) =="
python3 - <<'PY'
s = open('src/net/rob.h').read()
start = s.index('        uint64_t rest = live;')
end = s.index('        return false;\n    }', start)
naive = '''        uint64_t hits = 0;
        for (uint32_t i = 0; i < ReadLocalRobState::kWriteRingCapacity; i++)
            hits |= static_cast<uint64_t>(tags[i] == tag) << i;
        if (hits & live) return true;
'''
open('src/net/rob.h', 'w').write(s[:start] + naive + s[end:])
PY
build flat64
restore_src
for n in 1 4 9 15 19 40 63; do measure flat64 "$n"; done

echo "== grouped64 (SHIPPED) =="
build grouped64
for n in 1 4 9 15 19 40 63; do measure grouped64 "$n"; done
