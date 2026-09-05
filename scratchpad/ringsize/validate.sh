#!/bin/bash
# EVERYTHING THAT NEEDS THE BOX, IN ONE SEQUENCE SO NOTHING OVERLAPS. One server, one bench: two of
# these phases running at once would corrupt both verdicts, so they are steps of a single script
# rather than jobs anyone could start in parallel.
#
# Phases, in the order their evidence is needed:
#   build   both arms from one tree, warnings captured per arm
#   unit    the four unit binaries, including this lane's extended write-ring cases
#   sizes   the per-connection cost, printed
#   mutate  the falsification table: the control passes, every mutation fails
#   codegen is the tag sweep still vectorised, and what does the rejected shape compile to
#   probe   instructions and cycles per REJECTED read probe, by ring shape and live-write count
#   null    the same-binary null: what this rate instrument calls zero, measured first
#   rate    the saturated ABBA A/B: rate + instr/op + cycles/op + IPC + both counters
#   slope   the single-connection slope triad, the instrument that survives a co-tenanted box
#   mem     RSS with 2000 armed connections, both arms
#   batt    the 1s armed and 2s batteries
#   differ  both differ matrices against pinned Redis 7.4
#
#   validate.sh [phase ...]      (default: all of them, in this order)
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/scratchpad/ringsize"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
mkdir -p "$OUT"
cd "$ROOT"
stamp(){ echo "### $* @ $(date +%T)"; }
# Three phases below patch src/net/rob.h in place and restore it. The guard is a digest taken here,
# not "git diff --quiet": the tree legitimately carries this lane's uncommitted work, and a guard
# that cannot tell that apart from a leaked mutation is a guard nobody can leave switched on.
# No phase that needs the box starts while a neighbouring lane's server or load generator can run
# on this lane's cpus. A two-lane measurement nobody noticed is worse than no measurement.
guard(){ "$HERE/laneguard.sh" || { echo "phase '$1' NOT STARTED: lane cores are shared"; exit 1; }; }
# The correctness phases still WANT the box to themselves -- a shared core can time a battery out --
# but sharing cannot make a wrong reply look right, so they report the co-tenancy and continue
# instead of refusing. Only the phases that produce numbers refuse.
guard_soft(){ "$HERE/laneguard.sh" || echo "phase '$1' running anyway: correctness, not timing"; }
ROBSUM=$(md5sum src/net/rob.h | cut -d" " -f1)
check_restored(){
  [ "$(md5sum src/net/rob.h | cut -d" " -f1)" = "$ROBSUM" ] \
    && echo "tree restored: src/net/rob.h digest unchanged" \
    || { echo "REFUSING TO CONTINUE: $1 left src/net/rob.h modified"; exit 1; }
}
PHASES="${*:-build unit sizes mutate codegen probe null slope rate mem batt differ}"

for phase in $PHASES; do
case "$phase" in
build)
  stamp "build both arms"
  OUT="$OUT" "$HERE/build_arms.sh" 2>&1 | tee "$OUT/build_arms.txt"
  ;;
unit)
  stamp "make unit"
  taskset -c 48-55 make unit 2>&1 | tee "$OUT/unit.txt"
  ;;
sizes)
  stamp "layout / per-connection cost"
  g++ -std=c++20 -O2 -Wall -Wextra -march=native -I. "$HERE/sizes.cc" -o /tmp/ringsize-sizes \
      2>&1 | tee "$OUT/sizes-build.txt"
  /tmp/ringsize-sizes | tee "$OUT/sizes.txt"
  ;;
mutate)
  stamp "mutation table"
  "$HERE/mutate.sh" 2>&1 | tee "$OUT/mutate.txt"
  check_restored mutate.sh
  ;;
codegen)
  stamp "tag sweep codegen"
  "$HERE/codegen_ab.sh" 2>&1 | tee "$OUT/codegen.txt"
  check_restored codegen_ab.sh
  ;;
probe)
  stamp "instructions per rejected read probe"
  "$HERE/probe_cost.sh" 2>&1 | tee "$OUT/probe_cost.txt"
  check_restored probe_cost.sh
  ;;
null)
  # SAME-BINARY NULL, RUN FIRST. Both arms are the PRE binary, so every delta this instrument
  # reports here is its own noise -- and a rate delta smaller than that is not a result no matter
  # how it is averaged. It is cheap (one round) and it is the only honest floor for section 4.
  guard null
  stamp "same-binary null (PRE vs PRE)"
  rm -f "$OUT/ab_null.csv"
  "$HERE/ab_triad.sh" ./build/tomokv-pre ./build/tomokv-pre "$OUT/ab_null.csv" \
      "${NULL_ROUNDS:-1}" 2>&1 | tail -3
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_null.csv" | tee "$OUT/ab_null.txt"
  ;;
rate)
  guard rate
  stamp "saturated ABBA rate + triad + counters"
  rm -f "$OUT/ab_triad.csv"
  "$HERE/ab_triad.sh" ./build/tomokv-pre ./build/tomokv-post "$OUT/ab_triad.csv" \
      "${ROUNDS:-3}" 2>&1 | tail -6
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_triad.csv" | tee "$OUT/ab_triad.txt"
  ;;
slope)
  guard slope
  stamp "single-connection slope triad (ABBA)"
  rm -f "$OUT/triad.csv"
  for r in $(seq 1 "${SLOPE_ROUNDS:-3}"); do
    "$HERE/measure_triad.sh" ./build/tomokv-pre  PRE  "$OUT/triad.csv" 1 >/dev/null || exit 1
    "$HERE/measure_triad.sh" ./build/tomokv-post POST "$OUT/triad.csv" 1 >/dev/null || exit 1
    "$HERE/measure_triad.sh" ./build/tomokv-post POST "$OUT/triad.csv" 1 >/dev/null || exit 1
    "$HERE/measure_triad.sh" ./build/tomokv-pre  PRE  "$OUT/triad.csv" 1 >/dev/null || exit 1
    echo "slope round $r done @ $(date +%T)"
  done
  python3 "$HERE/triad_report.py" "$OUT/triad.csv" all | tee "$OUT/triad.txt"
  python3 "$HERE/triad_report.py" "$OUT/triad.csv" u   | tee "$OUT/triad-user.txt"
  ;;
mem)
  guard mem
  stamp "RSS with 2000 armed connections"
  { "$HERE/mem.sh" ./build/tomokv-pre  PRE  2000
    "$HERE/mem.sh" ./build/tomokv-post POST 2000; } 2>&1 | tee "$OUT/mem.txt"
  ;;
batt)
  guard_soft batt
  stamp "batteries 1s"
  "$HERE/batteries.sh" ./build/tomokv 1s "$OUT/batteries_1s.txt" 2>&1 | tail -14
  stamp "batteries 2s"
  "$HERE/batteries.sh" ./build/tomokv 2s "$OUT/batteries_2s.txt" 2>&1 | tail -14
  # The 1s battery has one red row. Alternate the two arms through the same script on the same box
  # to say whose it is: a row that fails for both is the base branch's, and claiming it is this
  # lane's -- or quietly not mentioning it -- are the same mistake.
  stamp "expwide attribution (PRE vs POST, same box, same geometry)"
  "$HERE/expwide_preexisting.sh" 2>&1 | tee "$OUT/expwide_attribution.txt"
  ;;
differ)
  guard_soft differ
  stamp "differ canonical (split, read-local off)"
  GATE_DIFFER_OUT="$OUT/differ-canon" timeout 3000 \
    tests/differ_gate.sh ./build/tomokv 8091 8092 48-55 6:2 2>&1 | tee "$OUT/differ-canon.txt" | tail -6
  stamp "differ fused + read-local armed"
  GATE_DIFFER_OUT="$OUT/differ-fused" timeout 3000 \
    scratchpad/rlbatch/differ_gate_fused.sh ./build/tomokv 8091 8092 48-55 6:2 2>&1 \
    | tee "$OUT/differ-fused.txt" | tail -8
  ;;
*) echo "unknown phase: $phase"; exit 2;;
esac
done
stamp "ALL DONE ($PHASES)"
