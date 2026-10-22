#!/bin/bash
# wave2 budget scan, round 3: wider ranges where rounds 1-2 left one unattributed (C) body
# (db0 xshard.o, db0 aof.o), plus neighbours of the chosen db0 reorder / src genthread values.
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave2/docs/wave2/identity/budget-trials
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r3" 2> "$OUT/$(echo $obj | tr / _).r3.err"; }
scan db0/src/cmd/xshard.o "" 126450 126470 126500 126540 126544 126546 126562 126566 126580 126590 126610 126630 126660 126700 126750 126800
JOBS=8 scan db0/src/persist/aof.o "" 34700 34750 34780 34790 34880 34890 34900 34920 34950 35000 35050 35100 &
JOBS=8 scan db0/src/core/reorder.o "" 148355 148357 148358 148359 148361 148362 148363 148365 &
wait
scan src/core/genthread.o "" 129446 129447 129449 129450 129451 129452 129454 129455 129457 129458
echo SCAN3-DONE
