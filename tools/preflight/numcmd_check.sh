#!/bin/bash
# FIX 2 sanity check driver: run the exact-count probe against BOTH binaries
# (pre-fix and post-fix) in one box-lock acquisition, so the numbers are comparable.
set -u
W=/shared/Projects/THredis/.claude/worktrees/agent-a6117f52725763a8a
PORT=7997
D=/tmp/numcmd_check

one() {   # one <label> <binary>
  local label=$1 bin=$2
  pkill -9 -x numcmd-srv 2>/dev/null; sleep 1
  rm -rf $D; mkdir -p $D
  cp "$bin" $D/numcmd-srv
  taskset -c 0-7 $D/numcmd-srv --port $PORT --dir $D --tomokv-nodes 1 \
     --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
     --protected-mode no --logfile $D/srv.log >/dev/null 2>&1 &
  sleep 3
  python3 "$W/tools/preflight/numcmd_check.py" $PORT "$label"
  pkill -9 -x numcmd-srv 2>/dev/null; sleep 1
}

one BEFORE /tmp/numcmd_bins/redis-server.BEFORE
echo
one AFTER  $W/src/redis-server
