#!/bin/bash
# The marker gate, written so it cannot be vacuous: `find -mmin +3` EXITS 0 regardless of the
# predicate and only prints on a match, so `find ... && make` always runs. Compare ages directly.
F=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/quiet.done
[ -f "$F" ] || { echo "GATE: marker absent"; exit 1; }
AGE=$(( $(date +%s) - $(stat -c %Y "$F") ))
[ "$AGE" -ge 180 ] || { echo "GATE: marker only ${AGE}s old (<180)"; exit 1; }
echo "GATE: ok (marker ${AGE}s old)"
