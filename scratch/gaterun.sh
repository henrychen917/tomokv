#!/bin/bash
# gaterun.sh CMD... -- wait until the box gate is clear, then run CMD at once (closes the window
# between a gate check and a launch; ab.sh still re-checks the gate before every cell).
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
while ! gate_ok; do echo "gaterun waiting $(date +%T): quiet.done=$([ -f "$SP/quiet.done" ] && stat -c %y "$SP/quiet.done" | cut -c12-19 || echo MISSING)"; sleep 30; done
echo "gaterun GO $(date +%T)"; exec "$@"
