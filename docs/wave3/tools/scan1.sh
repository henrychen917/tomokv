#!/bin/bash
# wave3 budget scan, round 1: compile-only trials around each budgeted object's headroom-preserving
# centre (centre = f821104a9 budget + integrated IPA unit growth over f821104a9; unit-sizes.jsonl),
# covering every lane's own value and the provisional merge value. src/core/reorder.o has no
# override: its default limit is 1.4 x unit (GCC 13 inline-unit-growth=40), so the PRE-equivalent
# absolute limit is 114033 * 1.4 = 159646 and the headroom-preserving value is 159646 + 454 = 160100.
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave3/docs/wave3/identity/budget-trials
mkdir -p "$OUT"
scan(){ local obj=$1 extra=$2 tag=$3; shift 3; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _)$tag.r1" 2> "$OUT/$(echo $obj | tr / _)$tag.r1.err"; }
seqv(){ seq "$1" "$2" "$3" | tr '\n' ' '; }
scan src/core/genthread.o "" "" 129447 129780 129807 129835 $(seqv 129700 10 129980)
scan db0/src/core/genthread.o "" "" 129704 129730 129794 130090 $(seqv 129850 15 130300)
scan src/core/rl2s.o "" "" 162305 162609 162614 162759 $(seqv 162580 12 162940)
scan db0/src/core/rl2s.o "" "" 162334 162786 $(seqv 162600 20 162960)
scan src/core/reorder.o "" "" 160100 $(seqv 159900 20 160300)
scan db0/src/core/reorder.o "" "" 148358 148538 148799 $(seqv 148600 20 149000)
scan db0/src/core/reorder.o "--param max-inline-insns-auto=14" ".auto14" 148358 148438 148538 148799 $(seqv 148600 20 149000)
JOBS=8 scan src/main.o "" "" 147428 147500 147560 147632 147700 &
JOBS=8 scan db0/src/main.o "--param max-inline-insns-auto=18" "" 147449 147520 147580 147653 147720 &
wait
JOBS=8 scan src/persist/aof.o "" "" 34437 37300 37337 36099 $(seqv 35900 100 37500) &
JOBS=8 scan db0/src/persist/aof.o "" "" 34840 37800 37840 36496 $(seqv 36300 100 37900) &
wait
JOBS=8 scan src/cmd/xshard.o "" "" 127924 128003 $(seqv 127900 12 128110) &
JOBS=8 scan db0/src/cmd/xshard.o "" "" 126566 126645 $(seqv 126540 12 126760) &
wait
JOBS=8 scan src/cmd/t_server.o "" "" 31379 31402 $(seqv 31370 4 31440) &
JOBS=8 scan db0/src/cmd/t_server.o "--param max-inline-insns-auto=16" "" 31776 31799 $(seqv 31770 4 31840) &
wait
echo SCAN1-DONE
