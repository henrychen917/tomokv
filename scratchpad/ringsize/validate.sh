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
#   satcheck the saturation ladder: is the server the bottleneck, or is the load generator? No rate
#           A/B is run until this says the rate belongs to the server
#   ratioshape whether the matrix's cells measure write fraction or write run length
#   null    the same-binary null: what this rate instrument calls zero, measured first
#   rate    the saturated ABBA A/B: rate + instr/op + cycles/op + IPC + both counters
#   matched the same A/B with both arms rate-limited to the same delivered load, which is the only
#           geometry in which instructions/op is a work measure rather than a spin measure
#   rlvalue is read-local itself worth anything in this geometry: --read-local 0 vs 1, base arm
#   ovf     ring overflows per arm, from the two instrumented binaries
#   expwide the S1 MGET reproduction across m14 / pre / post -- the red row that blocks the merge
#   conn    512 vs 2048 connections with DRAM fills: what the per-connection footprint costs
#   mset    MSET 8 vs 32 keys: what the OTHER fixed sixteen costs
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
# Every src file any phase here writes: rob.h (mutate/codegen/probe), conn.h and config.h (the PRE
# arm of build_arms.sh) and t_server.cc (the overflow graft). Digesting only rob.h would have let a
# leaked graft in t_server.cc ride into a commit.
SRCSUM=$(md5sum src/net/rob.h src/net/conn.h src/core/config.h src/cmd/t_server.cc | md5sum)
check_restored(){
  [ "$(md5sum src/net/rob.h src/net/conn.h src/core/config.h src/cmd/t_server.cc | md5sum)" = "$SRCSUM" ] \
    && echo "tree restored: lane source digests unchanged" \
    || { echo "REFUSING TO CONTINUE: $1 left a lane source file modified"; exit 1; }
}
PHASES="${*:-build unit sizes mutate codegen expwide probe satcheck ratioshape null rate matched rlvalue ovf conn mset slope mem batt differ}"

# THE SATURATION LADDER CHOOSES THE LOAD GEOMETRY FOR EVERY RATE PHASE, and they read it out of a
# file rather than out of a decision taken by eye from a table. If satcheck has run in this OUT
# directory, its chosen rung is in force; if it has not, the defaults in lib.sh and ab_triad.sh
# apply and the run says so once.
load_geometry(){
  if [ -s "$OUT/satcheck.env" ]; then
    # shellcheck disable=SC1090
    . "$OUT/satcheck.env"
    export CLICORES THREADS CONNS
    echo "geometry from satcheck: cpus $CLICORES, $THREADS threads x $CONNS conns, plateau=$PLATEAU"
    [ "${PLATEAU:-yes}" = yes ] || echo "!! PLATEAU=no -- the ladder was still climbing at its last rung. Every RATE in this run is the load generator's limit; read instructions/op and the counters only."
  else
    echo "geometry: lane defaults (satcheck has not run in $OUT)"
  fi
}

# ROWS ACCUMULATE ACROSS ATTEMPTS, because on a contested box a phase that restarts from zero every
# time the owner takes the box back never finishes. Between 01:01 and 02:47 this lane got two
# windows, of four minutes and of fifty-two seconds, against a null that needs twenty. Each cell
# writes its own csv row the moment it completes, so an interrupted attempt leaves whole, valid
# cells behind and the next attempt adds to them. Set RESET=1 to start a phase's csv clean.
# WHAT THIS COSTS: the ABBA visit order cancels drift WITHIN a round, and rows gathered an hour
# apart are not protected that way. So every report prints its visit count per arm and its per-cell
# spread, and a table built from lopsided or widely separated attempts says so on its face.
keep_or_reset(){ [ "${RESET:-0}" = 1 ] && rm -f "$1"; return 0; }

for phase in $PHASES; do
case "$phase" in
build)
  stamp "build both arms"
  OUT="$OUT" "$HERE/build_arms.sh" 2>&1 | tee "$OUT/build_arms.txt"
  ;;
unit)
  stamp "make unit"
  taskset -c 58-63,186-191 make unit 2>&1 | tee "$OUT/unit.txt"
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
satcheck)
  # THE INSTRUMENT CHECK THAT COMES BEFORE THE NULL. A null proves the two arms are the same binary;
  # it cannot prove the rate it reports is a property of the server. Two nulls were thrown away for
  # exactly that -- the first moved -12.14% on one binary against itself, the second came back tight
  # in the median but with a read-only control swinging 14% and the server idle an eighth of every
  # core in every cell. This ladder holds the server fixed and grows the load generator until the
  # rate stops climbing. Where it stops is where the server is the limit, and that is the only place
  # a rate A/B in this lane may be run.
  guard satcheck
  stamp "saturation ladder (is the server the bottleneck?)"
  rm -f "$OUT/satcheck.csv"
  "$HERE/satcheck.sh" ./build/tomokv-pre "$OUT/satcheck.csv" 2>&1 | tee "$OUT/satcheck.txt"
  ;;
ratioshape)
  # WHAT DOES A "55% WRITES" CELL ACTUALLY DELIVER? The connection regime demoted 902 reads at
  # --ratio=1:1 and 3,007,793 at --ratio=55:45 on the same arm, same 512 connections, same depth.
  # A five-point move in write fraction cannot do that; a change in the SHAPE of the stream can.
  # Two pairs hold the fraction constant and move the block length (1:1 against 50:50, 11:9 against
  # 55:45), which is the only arrangement that can tell them apart -- and it decides how every row
  # of this lane's matrix has to be LABELLED.
  guard ratioshape
  load_geometry
  stamp "ratio shape: is the matrix a write-fraction sweep or a run-length sweep?"
  rm -f "$OUT/ratio_shape.csv"
  "$HERE/ratio_shape.sh" ./build/tomokv-pre "$OUT/ratio_shape.csv" 2>&1 | tee "$OUT/ratio_shape.txt"
  ;;
null)
  # SAME-BINARY NULL, RUN FIRST. Both arms are the PRE binary, so every delta this instrument
  # reports here is its own noise -- and a rate delta smaller than that is not a result no matter
  # how it is averaged. It is cheap (one round) and it is the only honest floor for section 4.
  guard null
  load_geometry
  stamp "same-binary null (PRE vs PRE)"
  keep_or_reset "$OUT/ab_null.csv"
  "$HERE/ab_triad.sh" ./build/tomokv-pre ./build/tomokv-pre "$OUT/ab_null.csv" \
      "${NULL_ROUNDS:-1}" 2>&1 | tail -3
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_null.csv" | tee "$OUT/ab_null.txt"
  ;;
rate)
  guard rate
  load_geometry
  stamp "saturated ABBA rate + triad + counters"
  keep_or_reset "$OUT/ab_triad.csv"
  "$HERE/ab_triad.sh" ./build/tomokv-pre ./build/tomokv-post "$OUT/ab_triad.csv" \
      "${ROUNDS:-3}" 2>&1 | tail -6
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_triad.csv" | tee "$OUT/ab_triad.txt"
  ;;
matched)
  # INSTRUCTIONS/OP, WITH THE SPIN HELD EQUAL. RATE is per CONNECTION ops/s; with 4 threads x 64
  # connections the delivered load is 256x that, and it must sit below the SLOWER arm's saturation
  # or the limit does not bind and this is just the saturated run again. The rate phase above
  # prints both arms' maxima; MATCHED_RATE is set from them.
  guard matched
  load_geometry
  # DERIVED FROM THE SATURATED RUN THAT JUST RAN, not typed in. One rate limit is applied to every
  # cell, so it has to sit below the SLOWEST cell of the SLOWER arm or it does not bind there and
  # that cell is simply the saturated run again -- which is the failure mode this phase exists to
  # avoid. 85% of that minimum, per connection, over this run's 512.
  if [ -z "${MATCHED_RATE:-}" ] && [ -s "$OUT/ab_triad.csv" ]; then
    MATCHED_RATE=$(python3 - "$OUT/ab_triad.csv" <<'PYEOF'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1])))
per = {}
for r in rows:
    per.setdefault((r['cell'], r['arm']), []).append(float(r['rate']))
worst = min(statistics.median(v) for v in per.values())
print(int(0.85 * worst / 512))
PYEOF
)
    echo "MATCHED_RATE derived from ab_triad.csv: $MATCHED_RATE ops/s/connection"
  fi
  : "${MATCHED_RATE:?set MATCHED_RATE (per-connection ops/s) from the saturated run first}"
  stamp "matched-rate A/B at ${MATCHED_RATE} ops/s/conn"
  keep_or_reset "$OUT/ab_matched.csv"
  RATELIMIT="$MATCHED_RATE" "$HERE/ab_triad.sh" ./build/tomokv-pre ./build/tomokv-post \
      "$OUT/ab_matched.csv" "${MATCHED_ROUNDS:-2}" 2>&1 | tail -4
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_matched.csv" | tee "$OUT/ab_matched.txt"
  ;;
expwide)
  # EVIDENCE ONLY -- THIS ROW NO LONGER GATES THIS LANE. The owner reproduced the same failure on
  # the frozen train-9 mainline binary (e902c67d5) under --thread-mode fused --read-local 1, and it
  # passes there with read-local off and in split mode: the gate's feature loop only ever boots
  # split, and its fused section runs four batteries with read-local off, so fused+armed was never
  # covered (expwide and climon2 both fall in that hole). A separate lane off t-merge14 adds the
  # fused+armed feature leg and fixes both. This phase still runs, because the counters are the
  # evidence for WHY, but expwide under fused+armed is excused for this lane's merge bar and every
  # other row must still be green.
  guard_soft expwide
  stamp "expwide S1 reproduction: m14 vs pre vs post"
  "$HERE/expwide_bisect.sh" 2>&1 | tee "$OUT/expwide_bisect.txt" | grep -vE "^\s*$"
  check_restored expwide_bisect.sh
  ;;
conn)
  # The connection-footprint regime: does +960 bytes per armed connection cost more than the
  # demotion fix earns once there are 2048 of them?
  guard conn
  load_geometry
  stamp "connection scaling 512 vs 2048, with DRAM fills"
  keep_or_reset "$OUT/regimes_conn.csv"
  "$HERE/regimes.sh" conn ./build/tomokv-pre ./build/tomokv-post "$OUT/regimes_conn.csv" \
      "${CONN_ROUNDS:-2}" 2>&1 | tail -4
  python3 "$HERE/regimes_report.py" "$OUT/regimes_conn.csv" | tee "$OUT/regimes_conn.txt"
  ;;
mset)
  # The other fixed sixteen: kMaxPreciseKeysetKeys, measured rather than flagged.
  guard mset
  load_geometry
  stamp "MSET width 8 vs 32 keys at depth 8"
  keep_or_reset "$OUT/regimes_mset.csv"
  "$HERE/regimes.sh" mset ./build/tomokv-pre ./build/tomokv-post "$OUT/regimes_mset.csv" \
      "${MSET_ROUNDS:-2}" 2>&1 | tail -4
  python3 "$HERE/regimes_report.py" "$OUT/regimes_mset.csv" | tee "$OUT/regimes_mset.txt"
  ;;
rlvalue)
  # WHAT IS READ-LOCAL WORTH HERE AT ALL? This lane's cost is +43 instructions per write and, at 70%
  # writes, +249 per read -- and the tag sweep's own microbenchmark cannot account for more than +90
  # of that. The remainder is the difference between SERVING a read locally and DEMOTING it, and
  # until it is measured the lane cannot say whether it bought the wrong thing or the right thing
  # badly. One binary, one knob: --read-local 0 against 1 on the BASE arm, at 1:1 (where the ring
  # never fills, so the feature runs with nothing in its way) and at 55:45 (where it gives up).
  guard rlvalue
  load_geometry
  stamp "read-local value: --read-local 0 vs 1 on the base arm"
  keep_or_reset "$OUT/rl_value.csv"
  "$HERE/rl_value.sh" ./build/tomokv-pre "$OUT/rl_value.csv" "${RLV_ROUNDS:-2}" 2>&1 \
    | tee "$OUT/rl_value.txt" | tail -14
  ;;
ovf)
  # THE COUNTER THAT COULD HAVE FALSIFIED THE CLAIM. POST asserts capacity overflow is unreachable;
  # this is the run in which it is asked, on the same three regimes, with the same counter grafted
  # onto both arms. A non-zero POST count here would end this lane.
  guard ovf
  load_geometry
  stamp "ring overflows per arm (instrumented binaries)"
  keep_or_reset "$OUT/ab_ovf.csv"
  "$HERE/ab_triad.sh" ./build/tomokv-pre-ovf ./build/tomokv-post-ovf "$OUT/ab_ovf.csv" \
      "${OVF_ROUNDS:-1}" 2>&1 | tail -3
  python3 "$HERE/ab_triad_report.py" "$OUT/ab_ovf.csv" | tee "$OUT/ab_ovf.txt"
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
    tests/differ_gate.sh ./build/tomokv 8300 8301 58-63,186-191 6:2 2>&1 | tee "$OUT/differ-canon.txt" | tail -6
  stamp "differ fused + read-local armed"
  GATE_DIFFER_OUT="$OUT/differ-fused" timeout 3000 \
    scratchpad/rlbatch/differ_gate_fused.sh ./build/tomokv 8300 8301 58-63,186-191 6:2 2>&1 \
    | tee "$OUT/differ-fused.txt" | tail -8
  ;;
*) echo "unknown phase: $phase"; exit 2;;
esac
done
stamp "ALL DONE ($PHASES)"
