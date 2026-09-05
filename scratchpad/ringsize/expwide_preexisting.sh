#!/bin/bash
# The 1s battery's one red row must be shown to be the BASE BRANCH's, not this lane's: the same
# script, the same box, the same geometry, alternated between the two binaries. A row that fails
# for both is pre-existing; a row that fails only for POST would be this lane's to fix.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"
source "$HERE/lib.sh"
SRVCORES=${SRVCORES:-58-60}
for rep in 1 2; do
  for arm in pre post; do
    boot_srv "./build/tomokv-$arm" /tmp/ringsize-expw-$arm.log \
      --atomic 0 --enable-debug-command yes || exit 1
    if timeout 900 python3 tests/expwide.py 127.0.0.1 $PORT > /tmp/ringsize-expw-$arm-$rep.txt 2>&1; then
      echo "rep$rep $arm expwide PASS"
    else
      echo "rep$rep $arm expwide FAIL -- $(grep -c '^  FAIL' /tmp/ringsize-expw-$arm-$rep.txt) row(s): $(grep -m1 '^  FAIL' /tmp/ringsize-expw-$arm-$rep.txt | sed 's/^ *//')"
    fi
    stop_srv
  done
done
