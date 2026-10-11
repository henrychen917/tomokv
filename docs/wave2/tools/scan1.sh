#!/bin/bash
# wave2 budget scan, round 1: compile-only trials around each object's headroom-preserving centre
# (centre = 991d48f65 budget + integrated IPA unit growth; see unit-sizes.jsonl), covering every
# lane's own value and the provisional merge value.
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave2/docs/wave2/identity/budget-trials
mkdir -p "$OUT"
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r1" 2> "$OUT/$(echo $obj | tr / _).r1.err"; }
scan src/core/rl2s.o "" 162280 162290 162297 162300 162305 162311 162312 162318 162323 162330 162340 162360
scan db0/src/core/genthread.o "" 129640 129652 129655 129660 129667 129675 129683 129690 129700 129720
scan db0/src/core/reorder.o "" 148258 148269 148280 148290 148301 148310 148320 148340
scan src/core/genthread.o "" 129400 129410 129418 129420 129430 129440 129453 129460 129480
JOBS=8 scan src/main.o "" 147428 147434 147450 147480 &
JOBS=8 scan db0/src/main.o "--param max-inline-insns-auto=18" 147449 147480 147500 147520 &
wait
JOBS=8 scan db0/src/core/rl2s.o "" 162334 162350 162376 162400 &
JOBS=8 scan db0/src/cmd/xshard.o "" 126482 126492 126510 126520 126533 126542 126552 126560 126580 126600 &
wait
JOBS=8 scan src/cmd/xshard.o "" 127880 127900 127915 127924 127930 127950 &
JOBS=8 scan src/cmd/t_server.o "" 31330 31340 31350 31360 31367 31370 31375 31379 31385 31390 31400 31420 &
wait
JOBS=8 scan db0/src/cmd/t_server.o "--param max-inline-insns-auto=16" 31725 31737 31750 31760 31766 31770 31776 31778 31785 31790 31800 31820 &
JOBS=8 scan db0/src/persist/aof.o "" 34800 34813 34820 34830 34837 34844 34850 34860 34880 &
wait
scan src/persist/aof.o "" 34400 34420 34430 34437 34445 34460
echo SCAN1-DONE
