#!/bin/bash
# gatewait.sh -- block until the box gate is clear (quiet.done older than 3 min AND no intruder on
# my cores). Prints one status line per minute; exits 0 when clear.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
while true; do
  if gate_ok; then echo "GATE CLEAR $(date +%T): quiet.done $(stat -c %y "$SP/quiet.done" | cut -c1-19), no intruders"; exit 0; fi
  echo "waiting $(date +%T): quiet.done=$([ -f "$SP/quiet.done" ] && stat -c %y "$SP/quiet.done" | cut -c12-19 || echo MISSING) intruders=$(intruders | tr '\n' ';')"
  sleep 60
done
