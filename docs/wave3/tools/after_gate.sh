#!/bin/bash
# wave3: once the full gate run has finished (GATE-FULL-DONE), run the Redis 7.4.10 differential
# focused proof and then the lane batteries, serially on CPUs 80-95.
cd /home/user/Projects/cx-wave3
until grep -q GATE-FULL-DONE build/wave3/gate-full/exits.txt 2>/dev/null; do sleep 20; done
echo "differ start $(date -Is)" >> build/wave3/after-gate.txt
docs/wave3/tools/differ.sh >> build/wave3/after-gate.txt 2>&1
echo "batteries start $(date -Is)" >> build/wave3/after-gate.txt
docs/wave3/tools/batteries.sh >> build/wave3/after-gate.txt 2>&1
echo "AFTER-GATE-DONE $(date -Is)" >> build/wave3/after-gate.txt
