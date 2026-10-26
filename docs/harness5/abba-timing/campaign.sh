#!/bin/bash
# ABBA-ordered timing of the abba_selftest row through tests/gate.sh (landing-like L), then the
# isolated after-run (I) that is also the green gate run of this branch. One run at a time.
set -u
rm -f /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/timing/summary.txt
for spec in "before L 1" "after L 1" "after L 2" "before L 2" "after I 1"; do
  bash /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/timing/run_one.sh $spec
done
echo DONE >> /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/timing/summary.txt
