#!/bin/bash
# wave1b budget scan, round 1: compile-only trials around each object's origin headroom centre
# (centre = wave1b IPA starting unit + (origin budget - origin unit)); see unit-sizes.jsonl.
cd /home/user/Projects/cx-wave1b/docs/wave1b/tools
OUT=/home/user/Projects/cx-wave1b/docs/wave1b/identity/budget-trials
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-8} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r1" 2> "$OUT/$(echo $obj | tr / _).r1.err"; }
JOBS=4 scan src/cmd/climon.o "" 25743 26100 26120 26130 26135 26140 26145 26150 26160 26167 26175 26190 26205 26230 26250 26300 &
JOBS=4 scan db0/src/cmd/climon.o "" 25670 26040 26060 26070 26080 26085 26090 26095 26102 26110 26120 26140 26160 &
JOBS=4 scan src/cmd/acl.o "" 35360 35370 35377 35380 35390 35400 35410 35420 35430 35432 35440 35450 35470 35500 &
JOBS=4 scan db0/src/cmd/acl.o "" 35300 35310 35320 35324 35330 35340 35350 35360 35368 35380 35400 35420 &
wait
JOBS=4 scan src/snapshot/snapshot.o "" 14584 14680 14700 14714 14720 14740 14760 &
JOBS=4 scan db0/src/snapshot/snapshot.o "" 14457 14540 14560 14587 14600 14620 &
JOBS=4 scan src/cmd/t_server.o "" 31297 31310 31330 31340 31355 31370 31400 &
JOBS=4 scan db0/src/cmd/t_server.o "--param max-inline-insns-auto=16" 31629 31660 31687 31700 31710 31730 31760 &
JOBS=2 scan src/cmd/geo.o "" 14400 14410 14420 14430 14450 &
JOBS=2 scan db0/src/cmd/geo.o "" 14430 14440 14450 14460 14480 &
wait
JOBS=8 scan src/cmd/xshard.o "" 127820 127830 127844 127850 127855 127864 127870 127880 127900 127950 &
JOBS=8 scan db0/src/cmd/xshard.o "" 126421 126440 126450 126460 126464 126470 126480 126500 &
wait
echo SCAN1-DONE
