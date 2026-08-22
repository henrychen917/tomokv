#!/bin/bash
# Arm C io_uring PEWB discriminator.  A timed-out infinite script on main's
# IO owner holds the outer command frame while a second main-owned connection
# receives a reply through the nested event loop.  The third connection kills
# the still-running script.  This exercises receive parsing, CQ advancement,
# and guarded direct-send retirement under processEventsWhileBlocked(), then
# requires the Arm C counters to prove both optional paths actually engaged.
set -u

SD="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$SD/preflight_lib.sh"
BIN=${TOMO_BIN:?TOMO_BIN required}
CLI="$(dirname "$BIN")/redis-cli"
[ -x "$CLI" ] || CLI="$SD/../../src/redis-cli"
PORT=${TOMO_PORT:-${TOMO_URING_C_PORT:-5983}}
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
OUT=${TOMO_RESULT_FILE:-${TOMO_PREFLIGHT_DIR:-/tmp}/uring_arm_c_pewb.out}
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
WORK=$(mktemp -d "${TOMO_PREFLIGHT_DIR:-/tmp}/uring_arm_c_pewb.XXXXXX") || {
  printf 'uring-arm-c-pewb\tFAIL\tcould not create work directory\n' >> "$OUT"
  exit 2
}
SP=""

port_free() {
  ! ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"
}

cleanup() {
  if [ -n "$SP" ] && kill -0 "$SP" 2>/dev/null; then
    kill -TERM "$SP" 2>/dev/null
    for _ in $(seq 1 30); do
      kill -0 "$SP" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$SP" 2>/dev/null
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

if ! port_free; then
  printf 'uring-arm-c-pewb\tFAIL\tport %s busy before boot\n' "$PORT" >> "$OUT"
  exit 1
fi

taskset -c "$SERVER_CORES" "$BIN" \
  --port "$PORT" --bind 127.0.0.1 --dir "$WORK" \
  --tomokv-nodes 2 --tomokv-cores-per-node 16 \
  --tomokv-thread-mode static --tomokv-thread-io 8 --tomokv-thread-ex 8 \
  --tomokv-pin-mode ccd --tomokv-client-lb no \
  --tomokv-atomic no --tomokv-io-uring 1 \
  --tomokv-uring-multishot 256 --tomokv-uring-sendcopy-min 4096 \
  --lua-time-limit 50 --save '' --appendonly no --protected-mode no \
  --logfile "$WORK/server.log" --daemonize no >"$WORK/stdout.log" 2>&1 &
SP=$!

ready=0
for _ in $(seq 1 100); do
  if [ "$(timeout 2 "$CLI" -p "$PORT" --raw PING 2>/dev/null | tr -d '\r')" = PONG ]; then
    ready=1
    break
  fi
  kill -0 "$SP" 2>/dev/null || break
  sleep 0.2
done
if [ "$ready" != 1 ]; then
  printf 'uring-arm-c-pewb\tFAIL\tserver did not boot; log=%s\n' "$WORK/server.log" >> "$OUT"
  exit 1
fi
if ! preflight_assert_standard_boot "$WORK/server.log" "$SP" 8 8; then
  printf 'uring-arm-c-pewb\tFAIL\tstandard 2x16c boot assertions failed\n' >> "$OUT"
  exit 1
fi

detail=$(taskset -c "$LOAD_CORES" python3 "$SD/uring_arm_c_pewb.py" \
  --port "$PORT" 2>&1)
rc=$?
crashes=$(grep -cE 'Guru Meditation|ASSERTION FAILED|crashed by signal|Sanitizer' \
  "$WORK/server.log" 2>/dev/null || true)
if [ "$rc" -eq 0 ] && [ "${crashes:-0}" -eq 0 ]; then
  printf 'uring-arm-c-pewb\tPASS\t%s\n' "$(printf '%s' "$detail" | tail -1)" >> "$OUT"
else
  printf 'uring-arm-c-pewb\tFAIL\t%s crash_markers=%s\n' \
    "$(printf '%s' "$detail" | tail -1)" "${crashes:-0}" >> "$OUT"
  exit 1
fi

timeout 5 "$CLI" -p "$PORT" SHUTDOWN NOSAVE >/dev/null 2>&1 || true
wait "$SP" 2>/dev/null || true
SP=""
exit 0
