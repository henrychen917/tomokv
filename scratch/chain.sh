#!/bin/bash
# chain.sh -- wait for the running final.sh to end (any way), then run the resumable finalw.sh.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
while ps -eo args --no-headers | awk '$1=="/bin/bash" && $2=="./scratch/final.sh"' | grep -q .; do sleep 20; done
echo "final.sh ended $(date +%T); tail: $(tail -1 "$SP/fd-final.log" | cut -c1-120)"
exec ./scratch/finalw.sh
