#!/bin/bash
# wave1b budget scan, round 2: the four large TUs (main/rl2s/genthread both namespaces, db0 reorder)
# around each origin-headroom centre, plus the b959fc844 (lanes' own) value for reference.
cd /home/user/Projects/cx-wave1b/docs/wave1b/tools
OUT=/home/user/Projects/cx-wave1b/docs/wave1b/identity/budget-trials
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-2} SHOW=60 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r2" 2> "$OUT/$(echo $obj | tr / _).r2.err"; }
JOBS=2 scan src/main.o "" 146891 147300 147350 147380 147400 147419 147428 147440 147460 147500 147550 147600 &
JOBS=2 scan db0/src/main.o "--param max-inline-insns-auto=18" 146928 147350 147400 147430 147449 147470 147485 147500 147550 147600 &
JOBS=2 scan src/core/rl2s.o "" 162035 162250 162300 162330 162351 162369 162390 162420 162450 162500 &
JOBS=2 scan db0/src/core/rl2s.o "" 162000 162250 162300 162334 162361 162390 162420 162450 &
JOBS=2 scan src/core/genthread.o "" 129025 129400 129440 129471 129490 129508 129530 129560 129600 129650 &
JOBS=3 scan db0/src/core/genthread.o "" 129370 129450 129500 129530 129553 129580 129600 129650 129681 129720 129760 &
JOBS=3 scan db0/src/core/reorder.o "" 147752 147900 147979 148020 148060 148100 148150 148200 148250 148300 148319 148347 148400 &
wait
echo SCAN2-DONE
