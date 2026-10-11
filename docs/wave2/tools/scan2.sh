#!/bin/bash
# wave2 budget scan, round 2: finer values around round 1's clean or near-clean points.
cd "$(dirname "$0")"
OUT=/home/user/Projects/cx-wave2/docs/wave2/identity/budget-trials
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-16} SHOW=40 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r2" 2> "$OUT/$(echo $obj | tr / _).r2.err"; }
scan src/core/rl2s.o "" 162301 162302 162303 162304 162306 162307 162308 162309 162310 162313 162314 162315 162316
scan db0/src/core/genthread.o "" 129692 129694 129696 129698 129699 129701 129702 129704 129706 129708 129710 129712 129715
scan db0/src/core/reorder.o "" 148325 148330 148335 148338 148339 148341 148342 148345 148350 148355 148360 148370 148380 148400
scan db0/src/cmd/xshard.o "" 126525 126528 126530 126536 126539 126545 126548 126550 126554 126556 126558 126565 126570 126575
JOBS=8 scan db0/src/persist/aof.o "" 34805 34810 34816 34825 34834 34840 34847 34853 34856 34865 34870 34875 &
JOBS=8 scan src/core/genthread.o "" 129432 129435 129438 129442 129445 129448 129450 129456 &
wait
echo SCAN2-DONE
