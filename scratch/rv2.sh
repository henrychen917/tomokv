#!/bin/bash
# rv2.sh -- build the refinement commit, unit, then rv.sh (gate row x2, directed, 120 s cells).
source /home/user/Projects/wt-flipdamp/scratch/lib.sh; cd "$WT"
while ! gate_ok; do sleep 30; done
taskset -c 52-57,180-185 make -j12 >"$SP/fd-r5-build.txt" 2>&1; rc=$?
echo "$(date +%T) BUILD rc=$rc diag=$(grep -c -E 'error|warning' "$SP/fd-r5-build.txt") sha=$(sha256sum "$FIX_BIN" | cut -c1-16)"
[ $rc = 0 ] || exit 1
taskset -c 52-57,180-185 make unit >"$SP/fd-r5-unit.txt" 2>&1; echo "$(date +%T) UNIT rc=$?"
rm -f "$SP"/fd-r3-ctl-*.txt "$SP"/fd-r3-costgate.txt "$SP"/fd-r3-tm-*.txt "$SP"/fd-r3-tmtrace-*.txt "$SP"/fd-r3-tmdbg-*.txt "$SP"/fd-r3.done
exec ./scratch/rv.sh
