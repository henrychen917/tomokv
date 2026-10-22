#!/bin/bash
# wave3: every reference rebuild (git archive, own Makefile) against the binary its lane handed off
# and the mainline measured: loadable sections only (docs/deadswitch/linked_bytes.py). No execution.
set -u
cd /home/user/Projects/cx-wave3
R=build/wave3/refs; O=docs/wave3/identity/refs-vs-lanes; mkdir -p "$O"
pairs="base991=/home/user/Projects/bench-bins/tomokv-headline-991d48f65
pre=/home/user/Projects/bench-bins/tomokv-headline-f821104a9
respresume=/home/user/Projects/bins/respresume-post-18d24b9d-tomokv
rlfix=/home/user/Projects/bins/rlfix-post-d3880ba6-tomokv
mkfix=/home/user/Projects/bins/mkfix2-ab-3bb97dae-tomokv
aoforder=/home/user/Projects/cx-aoforder/build/aoforder/final/tomokv
hexpread=/home/user/Projects/bins/hexpread-post-b09bb310"
for p in $pairs; do
  name=${p%%=*}; lane=${p#*=}
  taskset -c 80-95 python3 docs/deadswitch/linked_bytes.py "$lane" "$R/$name-src/build/tomokv" "$O/$name.json" > "$O/$name.log" 2>&1
  printf '%s exit=%s %s\n' "$name" "$?" "$(cat "$O/$name.log")"
done
