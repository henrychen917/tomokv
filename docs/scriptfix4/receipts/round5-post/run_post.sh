#!/bin/bash
# Re-run the round-5 auditors' witnesses (copies retargeted to CPUs 87-99, ports 21220-21299)
# against build/scriptfix4/POST. Their own assertions expect the PRE defects.
set -u
R=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/sf4/r5
O=$R/post-results; rm -rf $O; mkdir -p $O
export LC_ALL=C
cd $R/cmd-complex
for t in "T1 probes.py hook" "T8b fcall_hang.py" "T6tracking script_tracking_overreg.py" "T5 script_tracking.py" "T31b streams_track_blocked.py"; do
  set -- $t; id=$1; shift
  CC_PORT_BASE=21220 timeout 300 taskset -c 95-99 python3 "$@" > $O/$id.jsonl 2> $O/$id.err; echo "$id rc=$?" >> $O/status
done
cd $R/persist
for t in "P-T6 shutdown_functions --mode 2s --engine epoll" "P-T7 shutdown_functions --mode 1s --engine epoll" "P-T9 shutdown_functions --mode 2s --engine epoll" "P-T8 shutdown_functions --oracle --engine epoll" "P-T19 function_cron --mode 2s" "P-T21 function_cron --mode 1s" "P-T20 function_cron --oracle"; do
  set -- $t; id=$1; shift
  timeout 300 python3 audit.py "$@" --port 21240 --label post-$id > $O/$id.jsonl 2> $O/$id.err; echo "$id rc=$?" >> $O/status
done
echo done >> $O/status
