#!/bin/bash
# wave3 R7 round: compile-only trials of the reorder.o units after the R7 envelope regeneration,
# classified against the pre-regeneration cx-wave3 build (trial_r7.py). Patched IPA units grow by
# +82 (src, 114487 -> 114569) and +80 (db0, 113581 -> 113661), so the headroom-preserving values are
# 147794 + 82 = 147876 and 148772 + 80 = 148852 (db0 keeps max-inline-insns-auto=14).
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave3/docs/wave3/identity/budget-trials-r7
mkdir -p "$OUT"
seqv(){ seq "$1" "$2" "$3" | tr '\n' ' '; }
args(){ local extra=$1; shift; for v in "$@"; do printf '%s\n' "--param inline-unit-growth=0 --param large-unit-insns=$v${extra:+ $extra}"; done; }
mapfile -t SRC < <(args "" 147794 147876 $(seqv 147790 3 147970))
mapfile -t DB0 < <(args "--param max-inline-insns-auto=14" 148772 148852 $(seqv 148760 3 148950))
JOBS=8 python3 trial_r7.py try src/core/reorder.o "${SRC[@]}" > "$OUT/src_core_reorder.o.r7" 2> "$OUT/src_core_reorder.o.r7.err" &
JOBS=8 python3 trial_r7.py try db0/src/core/reorder.o "${DB0[@]}" > "$OUT/db0_src_core_reorder.o.r7" 2> "$OUT/db0_src_core_reorder.o.r7.err" &
wait
echo SCAN-R7-DONE
