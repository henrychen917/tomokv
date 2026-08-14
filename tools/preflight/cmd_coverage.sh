#!/bin/bash
# COMMAND-COVERAGE SUITE — breadth check across every command family + a concurrency race sweep.
# Exists because SORT shipped with (a) a full-sort where LIMIT should top-k, and (b) a real per-worker
# race: sortCompare read process-global server.sort_desc/alpha, so concurrent SORTs with different
# DESC/ALPHA on different workers returned wrong-direction results (measured 19 mis-sorts). Part A runs a
# few representative KNOWN-correct invocations per family; Part B runs many connections, each deterministic
# on its OWN keys with per-connection-VARIED parameters, and verifies every reply — that is the net that
# catches the "command stashes per-invocation state in a process global" class across worker threads.
# Runs at reorder=0 AND reorder=2 (the drain path must not corrupt results either).
# io_uring mode-2 note: this broad command-family sweep intentionally remains on the default network
# mode. Its dedicated correctness cell must build USE_URING=yes and boot --tomokv-io-uring 1; the
# discriminating assertions are no stalled completions under DEFER_TASKRUN and byte-exact FIFO replies
# for pipelined/large responses (GET/SET coverage by itself does not distinguish the enter/order bugs).
#
# CASE cmd-coverage-r{0,2}
#   OUT OF SPEC: boot times out, or cmd_coverage.py reports any failing command-family check or any
#   concurrency-sweep mismatch (per-connection result diverges from its own deterministic expectation).
set -u
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
BIN=${TOMO_BIN:?TOMO_BIN required}
SD="$(cd "$(dirname "$0")" && pwd)"
GATE="$SD/cmd_coverage.py"
PORT=${TOMO_CMDCOV_PORT:-7993}
BOOT_TIMEOUT=${TOMO_BOOT_TIMEOUT:-20}
CLI="$(dirname "$BIN")/redis-cli"; [ -x "$CLI" ] || CLI="$(dirname "$BIN")/redis-pf-cli"
[ -f "$SD/preflight_lib.sh" ] && . "$SD/preflight_lib.sh"
OUT=${TOMO_RESULT_FILE:-$(mktemp "$J/cmd_coverage.XXXXXX.out")}
: > "$OUT"
WORK=$(mktemp -d "$J/cmd_coverage.XXXXXX.work") || { echo -e "cmd-coverage\tFAIL\tno workdir" >>"$OUT"; exit 2; }
SP=""
port_free(){ ! ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; }
stop(){ [ -n "$SP" ]||return 0; kill -9 "$SP" 2>/dev/null
  for _ in $(seq 1 100); do port_free && break; sleep 0.2; done; SP=""; }
trap 'stop; rm -rf "$WORK"' EXIT
boot(){ # $1 = reorder
  port_free || { echo -e "cmd-coverage-r$1\tFAIL\tport $PORT busy before boot" >>"$OUT"; return 1; }
  rm -rf "$WORK/d"; mkdir -p "$WORK/d"
  taskset -c 0-7 "$BIN" --port $PORT --bind 127.0.0.1 --dir "$WORK/d" --tomokv-nodes 1 --tomokv-thread-mode static \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-reorder "$1" --proto-max-bulk-len 512mb --maxclients 5000 \
    --save '' --appendonly no --protected-mode no --logfile "$WORK/d/s.log" --daemonize no >/dev/null 2>&1 & SP=$!
  for _ in $(seq 1 $((BOOT_TIMEOUT*5))); do timeout 2 "$CLI" -p $PORT ping 2>/dev/null|grep -q PONG && return 0; sleep 0.2; done
  echo -e "cmd-coverage-r$1\tFAIL\tboot timeout" >>"$OUT"; return 1
}
rc=0
for R in 0 2; do
  boot "$R" || { rc=1; stop; continue; }
  detail=$(taskset -c 8-15 python3 "$GATE" $PORT "r$R" 2>&1); prc=$?
  if [ $prc -eq 0 ]; then echo -e "cmd-coverage-r$R\tPASS\t$(echo "$detail"|tail -1)" >>"$OUT"
  else rc=1; echo -e "cmd-coverage-r$R\tFAIL\t$(echo "$detail"|grep -E '^  -|FAIL'|head -6|tr '\n' '|')" >>"$OUT"; fi
  stop
done
exit $rc
