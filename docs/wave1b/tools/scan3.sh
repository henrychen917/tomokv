#!/bin/bash
# wave1b budget scan, round 3: neighbourhoods of the clean round-1/2 candidates.
cd /home/user/Projects/cx-wave1b/docs/wave1b/tools
OUT=/home/user/Projects/cx-wave1b/docs/wave1b/identity/budget-trials
scan(){ local obj=$1 extra=$2; shift 2; JOBS=${JOBS:-2} SHOW=60 ./run_trials.sh "$obj" "$extra" "$@" > "$OUT/$(echo $obj | tr / _).r3" 2> "$OUT/$(echo $obj | tr / _).r3.err"; }
JOBS=4 scan db0/src/core/reorder.o "" 148210 148220 148230 148240 148245 148255 148260 148270 148280 148290 &
JOBS=2 scan src/cmd/climon.o "" 26141 26142 26143 26144 26146 26147 26148 26149 26180 26195 26200 26210 26220 &
JOBS=2 scan db0/src/cmd/climon.o "" 26130 26135 26145 26150 26155 26165 26170 26180 26200 26220 26250 26300 &
JOBS=2 scan src/cmd/xshard.o "" 127840 127846 127848 127852 127875 127878 127882 127885 127890 &
JOBS=2 scan db0/src/cmd/xshard.o "" 126455 126458 126462 126475 126478 126482 126485 126490 &
JOBS=1 scan src/cmd/t_server.o "" 31320 31325 31335 31345 31350 &
JOBS=1 scan db0/src/cmd/t_server.o "--param max-inline-insns-auto=16" 31715 31720 31725 31735 31740 31750 &
JOBS=1 scan src/snapshot/snapshot.o "" 14710 14715 14718 14722 14725 14730 &
JOBS=1 scan db0/src/snapshot/snapshot.o "" 14550 14555 14558 14562 14565 14570 14580 &
wait
JOBS=2 scan src/cmd/acl.o "" 35365 35367 35369 35371 35373 35375 &
JOBS=2 scan db0/src/cmd/acl.o "" 35315 35318 35322 35326 35328 &
JOBS=1 scan src/cmd/geo.o "" 14380 14390 14405 14408 14412 14415 &
JOBS=1 scan db0/src/cmd/geo.o "" 14420 14425 14428 14432 14435 &
JOBS=4 scan db0/src/core/genthread.o "" 129620 129630 129640 129645 129655 129660 129670 &
JOBS=4 scan src/core/genthread.o "" 129410 129420 129430 129450 129460 129465 129476 129480 &
wait
echo SCAN3-DONE
