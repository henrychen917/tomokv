#!/bin/bash
# Reshard hot-skew HANG reproduction + state capture.
#
# Regime (mirrors the run in which the server was observed to stop answering after ~8 migrations):
#   sustained 16-key gaussian skew, 200 connections, pipeline 32, 1:1 read/write, 64B values,
#   auto-reshard trigger with a LOW floor so migrations fire back to back.
#
# When the server stops answering, this captures — BEFORE anything is killed — the state that
# CLASSIFIES the stall:
#   * gdb "thread apply all bt" x3, 2s apart   (livelock advances a stack; deadlock does not)
#   * /proc/<pid>/status                        (VmRSS => OOM/unbounded memory; Threads)
#   * per-thread state + utime/stime deltas     (100% CPU spinner vs everyone idle)
#   * fresh connect + PING from the shell       (listener accepting? accepting-but-never-replying?)
# Every artifact lands in a per-run directory the NEXT boot cannot overwrite; this fork truncates
# its own logfile on start, which is how the previous occurrence was lost.
#
# usage: reshard_hang_run.sh <run-tag> [-- extra server args]
set -u
BIN=${TOMO_BIN:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src/redis-server}
CLI=$(dirname "$BIN")/redis-cli
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUTROOT=${TOMO_HANG_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp/hangw}
TAG=${1:?run tag required}; shift
PORT=${PORT:-7893}
IO=${IO:-4}; EX=${EX:-4}
KEYLB=${KEYLB:-1000}
SECS=${SECS:-90}
MODE=${MODE:-auto}                  # auto = balancer drives; manual = DEBUG RESHARD drives
RUN=$OUTROOT/$TAG
rm -rf "$RUN"; mkdir -p "$RUN/data"

# TOMO_STAGE_NAME: run the server under a UNIQUE process name. This is the discriminator for
# "did something outside this harness kill it": every suite on this box cleans up with
# `pkill -x redis-server`, which cannot match a differently-named binary. If the silent deaths
# stop when the name changes, they were an external kill, not a defect. Cleanup here is by PID,
# so renaming does not leak a server (the trap documented in docs/BUGS.md E-extra).
PROCNAME=redis-server
if [ -n "${TOMO_STAGE_NAME:-}" ]; then
  PROCNAME=$TOMO_STAGE_NAME
  cp "$BIN" "$RUN/$PROCNAME"
  BIN="$RUN/$PROCNAME"
fi

pkill -x redis-server 2>/dev/null; sleep 1

# Reap the server through a wrapper that records its WAIT STATUS. This one datum separates the
# whole failure class: 137 = SIGKILL (external kill or the OOM killer — nothing the process can
# log), 134 = SIGABRT (assert/panic/zmalloc-OOM), 139 = SIGSEGV, small N = a deliberate exit().
# Without it, "the process is gone and the log has no crash marker" is unclassifiable.
SRV_ARGS=(--port $PORT --dir "$RUN/data"
          --tomokv-nodes 1 --tomokv-thread-io $IO --tomokv-thread-ex $EX --tomokv-thread-mode static
          --tomokv-key-lb $KEYLB --save '' --appendonly no --protected-mode no
          --enable-debug-command yes "$@" --logfile "$RUN/server.log")
# TOMO_UNDER_GDB=1 runs the server under gdb. gdb reports the fatal signal AND a backtrace even
# when redis's own handler cannot run (no SA_ONSTACK => a stack-overflow SIGSEGV kills silently),
# and it distinguishes that from an external SIGKILL, which no in-process mechanism can.
if [ "${TOMO_UNDER_GDB:-0}" = 1 ]; then
  RUNNER=(gdb -batch -ex "set pagination off" -ex "handle SIGPIPE nostop noprint pass"
          -ex run -ex "thread apply all bt" -ex "info registers" --args "$BIN" "${SRV_ARGS[@]}")
else
  RUNNER=("$BIN" "${SRV_ARGS[@]}")
fi
( taskset -c 0-7 "${RUNNER[@]}" >"$RUN/stdout.log" 2>&1
  st=$?
  { echo "server_wait_status=$st"
    [ $st -gt 128 ] && echo "server_signal=$((st - 128)) ($(kill -l $((st - 128)) 2>/dev/null))"
  } >> "$RUN/exit_status.txt" ) &
for i in $(seq 1 40); do [ "$($CLI -p $PORT ping 2>/dev/null | tr -d '\r')" = PONG ] && break; sleep 0.3; done
PID=$(pgrep -x "$PROCNAME" | head -1)
[ -n "$PID" ] || { echo "$TAG	BOOTFAIL"; tail -20 "$RUN/stdout.log"; exit 2; }
{ echo "tag=$TAG pid=$PID port=$PORT keylb=$KEYLB mode=$MODE secs=$SECS io=$IO ex=$EX"
  echo "bin=$BIN sha=$(sha1sum "$BIN" | cut -c1-16)"
  echo "extra_args=$*"; } > "$RUN/meta.txt"
cat "$RUN/meta.txt"

# ---- continuous process sampler: RSS (OOM / unbounded memory), thread count, and per-thread
# CPU time. A stall that is a livelock burns utime; a deadlock does not; an OOM shows in VmRSS.
# Runs for the whole test so the PRE-stall trend is on record, not just the post-mortem sample.
( while [ -d /proc/$PID ]; do
    rss=$(awk '/VmRSS/{print $2}' /proc/$PID/status 2>/dev/null)
    thr=$(awk '/Threads/{print $2}' /proc/$PID/status 2>/dev/null)
    cpu=$(awk '{print $14+$15}' /proc/$PID/stat 2>/dev/null)
    # MemAvailable too: if the BOX runs out while this process stays small, the OOM killer
    # picking us is a box-level event, not a leak in the server.
    avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null)
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "${rss:-NA}" "${thr:-NA}" "${cpu:-NA}" "${avail:-NA}"
    sleep 1
  done; echo "PROCESS_GONE $(date +%s)" ) > "$RUN/proc_sample.tsv" 2>/dev/null &
SAMP=$!

# ---- preload so the dataset (and the FLATSTORE table) is at a realistic size, as the original did
taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
    --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=${PRELOAD:-2000000} -n allkeys \
    -t 8 -c 25 --pipeline 32 > "$RUN/mt_preload.out" 2>&1

# ---- uniform background: makes the skew a real statistical OUTLIER for the trigger
taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
    --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=${PRELOAD:-2000000} -t 2 -c 5 --pipeline 8 \
    --test-time=$((SECS + 20)) > "$RUN/mt_uniform.out" 2>&1 &
MT1=$!
sleep 2
MT2=""
PROBE_ARGS="--conns 0"
if [ "$MODE" = plain ]; then
  # CONTROL ARM: no skew, no migration pressure at all (run with KEYLB=0 to turn the balancer
  # off outright). Plain sustained p32 SET — if the server still dies here, resharding is not
  # an ingredient and the defect is in the base serving path.
  taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
      --ratio=1:0 -d 32 --key-pattern=R:R --key-maximum=${PRELOAD:-2000000} -t 8 -c 25 --pipeline 32 \
      --test-time=$SECS > "$RUN/mt_skew.out" 2>&1 &
  MT2=$!
elif [ "$MODE" = manual ]; then
  # cutovers are driven directly, and the hot keys are chosen INSIDE the moving range by the
  # probe itself, so the load has to come from the probe too.
  PROBE_ARGS="--conns 32 --pipeline 32 --keys 16 --drive-cutovers"
else
  # the faithful regime: 16-key gaussian skew, 200 conns, pipeline 32 -- the balancer triggers.
  taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
      --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 8 -c 25 --pipeline 32 \
      --test-time=$SECS > "$RUN/mt_skew.out" 2>&1 &
  MT2=$!
fi

# ---- watchdog (+ cutover driver in manual mode). This process never kills the server.
# shellcheck disable=SC2086
python3 "$DIR/reshard_hang_probe.py" --port $PORT --seconds $((SECS + 5)) $PROBE_ARGS \
        --logfile "$RUN/probe.log" > "$RUN/probe.out" 2>&1
rc=$?

if [ $rc = 3 ]; then
  echo "$TAG: STALL DETECTED -> capturing state (server left running)" | tee -a "$RUN/meta.txt"
  # FIRST question: is the process even there? A vanished pid is a crash/OOM, not a hang, and
  # every later artifact would then be empty for the wrong reason.
  if [ -d /proc/$PID ]; then echo "PROCESS_ALIVE" >> "$RUN/meta.txt"
  else echo "PROCESS_GONE (crash or kill — see server.log / proc_sample.tsv tail)" >> "$RUN/meta.txt"; fi
  grep -acE 'Guru Meditation|crashed by signal|ASSERTION FAILED|=== REDIS BUG REPORT' "$RUN/server.log" \
      2>/dev/null | sed 's/^/crash_markers=/' >> "$RUN/meta.txt"
  for i in 1 2 3; do
    date -u +%H:%M:%S.%N                              > "$RUN/sample$i.time"
    cp /proc/$PID/status                                "$RUN/sample$i.status" 2>/dev/null
    { for t in /proc/$PID/task/*; do
        tid=$(basename "$t")
        awk -v tid="$tid" '{c=$2; s=$3; print tid"\t"c"\t"s"\tutime="$14"\tstime="$15}' "$t/stat" 2>/dev/null
      done; } > "$RUN/sample$i.threads"
    timeout 150 gdb -p $PID -batch -ex "set pagination off" \
        -ex "thread apply all bt" \
        -ex "printf \"MIGACTIVE=%d PHASE=%d LO=%d HI=%d SRC=%d DST=%d\\n\", server.migration_active, server.migration.phase, server.migration.lo, server.migration.hi, server.migration.src, server.migration.dst" \
        -ex "print co_state" -ex "print mig_arm_lock" -ex "print tomo_flush_gate" \
        -ex "print server.flat_resize_active" -ex "print flat_rz_state" \
        -ex "print server.migration.fence_acked" \
        -ex "print server.migration.issued_seq" -ex "print server.migration.applied_seq" \
        -ex "print server.migration.scan_done" -ex "print server.migration.fence_gen" \
        -ex "print server.ex_bucket_end" \
        > "$RUN/sample$i.bt" 2>&1
    { echo "--- redis-cli PING (5s timeout), fresh connection:"
      timeout 5 "$CLI" -p $PORT ping; echo "cli_rc=$?"
      echo "--- raw connect test:"
      timeout 5 python3 -c "
import socket,sys,time
t=time.time()
try:
    s=socket.create_connection(('127.0.0.1',$PORT),timeout=4)
    print('connect OK in %.2fs'%(time.time()-t))
    s.sendall(b'PING\r\n'); s.settimeout(4)
    try: print('reply=%r'%s.recv(64))
    except Exception as e: print('NO REPLY: %r'%e)
except Exception as e:
    print('CONNECT FAILED: %r'%e)
"; } > "$RUN/sample$i.ping" 2>&1
    [ $i -lt 3 ] && sleep 2
  done
  cp "$RUN/server.log" "$RUN/server.log.frozen" 2>/dev/null
  "$CLI" -p $PORT --timeout 3 info clients > "$RUN/info_clients.txt" 2>&1
fi

kill -9 $MT1 $MT2 $SAMP 2>/dev/null
migs=$(grep -cE 'ee451 reshard (AUTO|DIFFUSE|RELEVEL):' "$RUN/server.log" 2>/dev/null); migs=${migs:-0}
done_n=$(grep -c 'ee451 reshard DONE' "$RUN/server.log" 2>/dev/null); done_n=${done_n:-0}
last=$(tail -3 "$RUN/probe.out" | tr '\n' ' ')

# Shut down politely FIRST and only escalate if that fails, leaving a marker when we escalate.
# Otherwise our own teardown SIGKILL lands in exit_status.txt as a 137 and is indistinguishable
# from the very thing being investigated (it already faked one).
"$CLI" -p $PORT --timeout 3 shutdown nosave >/dev/null 2>&1
sleep 2
if [ -n "$PID" ] && [ -d /proc/$PID ]; then
  echo "harness_escalated_to_SIGKILL=1" >> "$RUN/exit_status.txt"
  kill -9 "$PID" 2>/dev/null
fi
sleep 1
xs=$(tr '\n' ' ' < "$RUN/exit_status.txt" 2>/dev/null)
echo "$TAG	rc=$rc	armed=$migs	completed=$done_n	${xs:-status=?}	$last"
exit $rc
