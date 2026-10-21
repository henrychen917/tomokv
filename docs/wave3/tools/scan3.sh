#!/bin/bash
# wave3 budget scan, round 3: step-1 scans of the narrow plateaus left by round 2 (src reorder
# 147800, db0 genthread 130178-130180, db0 xshard 126680-126682, db0 reorder 148764-148774) and of the
# fewest-change regions where one structural D body remains at every scanned value (db0 aof:
# aoforder's record_post_image_impl no longer inlines Slice::key_eq; src genthread: wave2's
# atomic_prepare_capacity_read_local, register allocation of the merged unit).
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave3/docs/wave3/identity/budget-trials
scan(){ local obj=$1 extra=$2 tag=$3; shift 3; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _)$tag.r3" 2> "$OUT/$(echo $obj | tr / _)$tag.r3.err"; }
seqv(){ seq "$1" "$2" "$3" | tr '\n' ' '; }
scan src/core/reorder.o "" "" $(seqv 147781 1 147819)
scan db0/src/core/genthread.o "" "" $(seqv 130176 1 130182) $(seqv 130011 1 130016) $(seqv 130116 1 130121)
scan src/core/genthread.o "" "" $(seqv 129966 1 129978)
JOBS=8 scan db0/src/core/reorder.o "--param max-inline-insns-auto=14" ".auto14" $(seqv 148762 1 148776) &
JOBS=8 scan db0/src/cmd/xshard.o "" "" $(seqv 126677 1 126685) &
wait
JOBS=8 scan src/persist/aof.o "" "" $(seqv 37175 1 37195) &
JOBS=8 scan db0/src/persist/aof.o "" "" $(seqv 37575 1 37605) $(seqv 37615 1 37635) &
wait
echo SCAN3-DONE
