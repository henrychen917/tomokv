#!/bin/bash
# The two counters, in the SAME single-connection geometry the instructions/op table uses. A rate
# without them cannot say whether the mechanism fired; an instructions/op table cannot either.
#   replay_counters.sh <binary> <label>
set -u
BIN="$1"; LABEL="$2"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PORT=${PORT:-8302} SRVCORE=${SRVCORE:-58} CLICORE=${CLICORE:-61}
CLI=${CLI:-/tmp/claude-1000/redis74/src/redis-cli}
source "$ROOT/scratchpad/rlbatch/lib.sh"
boot_srv "$BIN" /tmp/ringsize-rc-$LABEL.log --enable-debug-command yes || exit 1
taskset -c "$CLICORE" "$ROOT/scratchpad/rlbatch/replay" $PORT warm 16 0 0 0 32 4096 >/dev/null
for cell in "32 41" "32 61" "32 71" "8 41" "64 41" "64 10"; do
  set -- $cell
  h0=$($CLI -p $PORT info all | tr -d '\r' | sed -n 's/^read_local_hits://p')
  f0=$($CLI -p $PORT info all | tr -d '\r' | sed -n 's/^read_local_fallback_inflight_write://p')
  taskset -c "$CLICORE" "$ROOT/scratchpad/rlbatch/replay" $PORT mix 16 3000000 "$1" "$2" 32 4096 >/dev/null
  h1=$($CLI -p $PORT info all | tr -d '\r' | sed -n 's/^read_local_hits://p')
  f1=$($CLI -p $PORT info all | tr -d '\r' | sed -n 's/^read_local_fallback_inflight_write://p')
  python3 -c "
h=$h1-$h0; f=$f1-$f0
print(f'$LABEL pipe=$1 read%=$2 read_local_hits={h} fallback_inflight_write={f} local={100.0*h/max(1,h+f):.1f}%')"
done
stop_srv
