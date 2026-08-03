#!/bin/bash
# INFO total_commands_processed must equal the number of commands the client actually sent.
#
# ee451 2026-07-29: THIS WAS NOT A SUITE. preflight.sh has listed it since 2026-07-28 and graded it
# "FAIL — produced no result file (exit 0)" every run. A suite that exits 0 cannot be a real
# failure, and the reason it wrote nothing is that it was never written as a suite at all: it was a
# private two-binary A/B driver that
#   * hardcoded $W to ANOTHER AGENT'S WORKTREE (agent-a6117f52725763a8a) and ran that tree's
#     src/redis-server as the "AFTER" arm -- so it never once exercised the binary preflight was
#     about to stamp;
#   * hardcoded the "BEFORE" arm to /tmp/numcmd_bins/redis-server.BEFORE, a path that does not
#     survive a reboot;
#   * printed its verdicts to STDOUT only, so they landed in preflight's per-suite log and nothing
#     was ever written to $PF/numcmd_check.out;
#   * ended on `pkill; sleep 1`, whose status is 0, so the driver reported success no matter what
#     the probe found. Both defects at once: no result file AND an exit code that could not fail.
#
# It is now a suite: it tests $TOMO_BIN, writes $PF/numcmd_check.out, and its exit status follows
# its verdict. The A/B arm is retained but OPTIONAL (NUMCMD_BEFORE_BIN), because the discrimination
# it provided is real and already recorded: on the pre-fix build the same probe measured
# A_setget_worker ratio 0.0000, C_mget8_xshard 0.0001, D_mixed 0.2500, TOTAL 0.2976 -- worker-routed
# and cross-shard commands were not counted at all -- against 1.0000 on every row post-fix.
set -u
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${1:-${TOMO_BIN:?TOMO_BIN required (or pass the binary as a positional argument)}}
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT=$J/numcmd_check.out; : > "$OUT"
PORT=7997
D=$J/numcmd_work
FAIL=0; PASS=0
for _c in "$(dirname "$BIN")/redis-cli" "$SD/../../src/redis-cli" /shared/Projects/redis/src/redis-cli; do
  [ -x "$_c" ] && { CLI=$_c; break; }
done
if [ -z "${CLI:-}" ]; then
  echo "harness-cli	FAIL	no redis-cli found (HARNESS failure, not the server)" >> "$OUT"; cat "$OUT"; exit 1
fi

# PRIVATE COMM + OUR-OWN-PID LIFECYCLE. Never `pkill -x redis-server` on this shared box: it
# SIGKILLs other sessions' servers with no crash marker, and it does not even match our own server
# once the caller stages the binary under a private name.
NCPID=""
cleanup_numcmd(){
  if [ -n "${NCPID:-}" ]; then
    kill -9 "$NCPID" 2>/dev/null
    wait "$NCPID" 2>/dev/null
    NCPID=""
  fi
}
# TERM/INT/HUP must `exit` rather than reap directly, so the EXIT trap is the single teardown path.
trap cleanup_numcmd EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

boot() {  # boot <binary> -> 0 if serving
  cleanup_numcmd; sleep 1
  rm -rf "$D"; mkdir -p "$D"
  cp -f "$1" "$D/redis-numcmd" || return 1
  chmod +x "$D/redis-numcmd"
  taskset -c 0-7 "$D/redis-numcmd" --port $PORT --dir "$D" --tomokv-nodes 1 \
     --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
     --protected-mode no --logfile "$D/srv.log" --loglevel notice >/dev/null 2>&1 &
  NCPID=$!
  local i
  for i in $(seq 1 40); do
    kill -0 "$NCPID" 2>/dev/null || return 1
    timeout 2 "$CLI" -p $PORT ping 2>/dev/null | grep -q PONG && return 0
    sleep 0.5
  done
  return 1
}

# one arm -> writes rows, echoes the raw probe output into the log for evidence
arm() {  # arm <label> <binary> <expect: OK|WRONG>
  local label=$1 bin=$2 expect=$3 raw rc
  if [ ! -x "$bin" ]; then
    echo "numcmd-$label	SKIP	no binary at $bin" >> "$OUT"; return 0
  fi
  if ! boot "$bin"; then
    echo "numcmd-$label	FAIL	server did not boot; see $D/srv.log" >> "$OUT"
    FAIL=$((FAIL+1)); return 1
  fi
  raw=$(timeout 600 python3 "$SD/numcmd_check.py" $PORT "$label" 2>&1); rc=$?
  cleanup_numcmd
  printf '%s\n' "$raw" >> "$J/numcmd_check.raw"
  if [ "$rc" -ne 0 ]; then
    echo "numcmd-$label	FAIL	probe exited $rc: $(printf '%s' "$raw" | tail -1)" >> "$OUT"
    FAIL=$((FAIL+1)); return 1
  fi
  # rows look like:  <label> <name> sent=N INFO_counted=M ratio=R  OK|WRONG
  local n=0 bad=0 line name verdict
  while IFS= read -r line; do
    case "$line" in *" OK"|*" WRONG") ;; *) continue ;; esac
    n=$((n+1))
    name=$(printf '%s' "$line" | awk '{print $2}')
    verdict=$(printf '%s' "$line" | awk '{print $NF}')
    if [ "$verdict" = "$expect" ]; then
      echo "numcmd-$label-$name	PASS	$(printf '%s' "$line" | cut -d' ' -f3-)" >> "$OUT"; PASS=$((PASS+1))
    else
      echo "numcmd-$label-$name	FAIL	expected $expect, got $verdict — $(printf '%s' "$line" | cut -d' ' -f3-)" >> "$OUT"
      FAIL=$((FAIL+1)); bad=$((bad+1))
    fi
  done <<EOF
$raw
EOF
  # A probe that produced no scored rows is not a pass. This is the exact shape of the defect this
  # rewrite closes: silence graded as success.
  if [ "$n" = 0 ]; then
    echo "numcmd-$label	FAIL	probe produced no scored rows (silence is not a pass)" >> "$OUT"
    FAIL=$((FAIL+1)); return 1
  fi
  printf '%s\n' "$raw" | grep 'TOTAL' | tail -1 | sed "s/^/numcmd-$label-total	NOTE	/" >> "$OUT"
  return 0
}

: > "$J/numcmd_check.raw"

# Optional discrimination arm: a build with the defect reintroduced MUST measure WRONG. When it is
# absent we say so in the result file rather than implying the probe was proven to discriminate on
# this run.
BEFORE=${NUMCMD_BEFORE_BIN:-}
if [ -n "$BEFORE" ] && [ -x "$BEFORE" ]; then
  echo "=== arm 1/2: defect-reintroduced (rows must read WRONG) ===" >> "$OUT"
  arm before "$BEFORE" WRONG
else
  echo "numcmd-discrimination	SUSPECT	no NUMCMD_BEFORE_BIN arm this run — this run did not itself demonstrate that the probe can fail. Recorded pre-fix evidence: TOTAL ratio 0.2976, worker+xshard rows 0.0000/0.0001." >> "$OUT"
fi

echo "=== arm: binary under test (every row must read OK) ===" >> "$OUT"
arm under-test "$BIN" OK

echo "RESULT: $PASS passed, $FAIL failed" >> "$OUT"
cat "$OUT"
[ "$FAIL" = 0 ]
