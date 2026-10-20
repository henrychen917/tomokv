#!/bin/bash
# wave3 budget scan, round 2: fine steps around round 1's clean values (hotCD = C = D = 0, fewest
# changed bodies), including each plateau's edges. src/core/reorder.o (no override at f821104a9):
# GCC's unit limit is (100 + inline-unit-growth)% of the running minimal unit size, which ends at
# 105268 (f821104a9) / 105722 (integrated) per -fdump-ipa-inline (build/wave3/dump), so the default's
# final limit is 147375 / 148010 and its inline headroom grew by 0.4 x 454 = 181 insns; an absolute
# limit (inline-unit-growth=0) of 147375 + 454 = 147829 preserves f821104a9's headroom. Round 1's
# 159900-160300 assumed 1.4 x the starting size and is far too loose.
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave3/docs/wave3/identity/budget-trials
scan(){ local obj=$1 extra=$2 tag=$3; shift 3; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _)$tag.r2" 2> "$OUT/$(echo $obj | tr / _)$tag.r2.err"; }
seqv(){ seq "$1" "$2" "$3" | tr '\n' ' '; }
scan src/core/reorder.o "" "" 147829 $(seqv 147500 20 148100)
scan src/core/genthread.o "" "" $(seqv 129962 2 129978) $(seqv 129985 5 130100)
scan db0/src/core/genthread.o "" "" $(seqv 130010 1 130020) $(seqv 130115 1 130125) $(seqv 130170 2 130196)
scan src/core/rl2s.o "" "" $(seqv 162666 2 162722)
JOBS=8 scan db0/src/core/reorder.o "--param max-inline-insns-auto=14" ".auto14" $(seqv 148740 2 148780) &
JOBS=8 scan src/persist/aof.o "" "" $(seqv 37150 10 37290) &
wait
JOBS=8 scan db0/src/persist/aof.o "" "" $(seqv 37550 10 37690) &
JOBS=8 scan src/cmd/xshard.o "" "" $(seqv 128010 2 128032) &
wait
JOBS=8 scan db0/src/cmd/xshard.o "" "" $(seqv 126650 2 126690) &
JOBS=8 scan src/cmd/t_server.o "" "" $(seqv 31383 1 31392) &
wait
JOBS=8 scan db0/src/cmd/t_server.o "--param max-inline-insns-auto=16" "" $(seqv 31784 1 31789) &
JOBS=8 scan db0/src/core/rl2s.o "" "" 162334 162786 &
wait
JOBS=8 scan src/main.o "" "" 147428 147632 &
JOBS=8 scan db0/src/main.o "--param max-inline-insns-auto=18" "" 147449 147653 &
wait
echo SCAN2-DONE
