#!/bin/bash
# F-clock / expiry-guard A/B DRIVER — run expiry_clock_lag.py in BOTH regimes against one build.
#
# The two defects need opposite regimes (see expiry_clock_lag.py's header), so a single cell cannot
# discriminate both:
#   D1  guard race   -> loaders=8, poll flat out.  Broken build: never=<all samples>.
#   D2  coarse clock -> loaders=0, poll every 5ms, ACTIVE EXPIRE OFF. Broken build: p95/max is the
#                       main loop's cron period minus the TTL (~40ms at hz=10 with a 60ms TTL);
#                       leaving the active cycle on hides it completely (see expiry_clock_lag.py).
# Both are printed for every arm so a "fix" that only moves one of them is visible as such.
#
# WHY A DRIVER AND NOT A ONE-LINER. Three box rules make the naive version wrong:
#   1. `pkill -f` matches the driver's own shell, and `pkill -x redis-server` on this SHARED box
#      kills whatever another agent is running. So every server started here is killed by its OWN
#      pid, recorded at boot.
#   2. Arms are distinguished by DIRECTORY, never by binary name: a binary called `unfixed` is
#      invisible to the `pkill -x redis-server` cleanup the rest of this tree relies on. Callers
#      pass a directory holding a binary literally named `redis-server`.
#   3. Anything that measures runs under the shared box lock — but this script does NOT take it, so
#      the CALLER can hold one lock across every arm. Interleaving arms inside a single lock is the
#      only way two numbers off this drift-prone box are comparable.
#
# Usage: expiry_clock_ab.sh <dir-with-redis-server> <port> [reps] [samples]
set -u
DIR=${1:?usage: expiry_clock_ab.sh <dir-with-redis-server> <port> [reps] [samples]}
PORT=${2:?port required}
REPS=${3:-3}
SAMPLES=${4:-60}
BIN=$DIR/redis-server
[ -x "$BIN" ] || { echo "expiry_clock_ab: no executable $BIN"; exit 1; }
[ "$(basename "$BIN")" = redis-server ] || { echo "expiry_clock_ab: binary must be named redis-server"; exit 1; }

SD="$(cd "$(dirname "$0")" && pwd)"
ARM=$(basename "$DIR")
RUN=$(mktemp -d "${TMPDIR:-/tmp}/fclock.XXXXXX")
PID=""
cleanup() { [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null; rm -rf "$RUN"; }
trap cleanup EXIT

boot() { # a fresh server per rep: D1's counter leak is CUMULATIVE, so a reused server would
         # carry the previous rep's leak into this one and the reps would not be independent.
    rm -rf "$RUN/d"; mkdir -p "$RUN/d"
    taskset -c 0-7 "$BIN" --port "$PORT" --dir "$RUN/d" --tomokv-nodes 1 \
        --tomokv-thread-io 4 --tomokv-thread-ex 4 --enable-debug-command local ${TOMO_XTRA:-} \
        --save '' --appendonly no --protected-mode no --logfile "$RUN/d/srv.log" >/dev/null 2>&1 &
    PID=$!
    for _ in $(seq 60); do
        sleep 0.25
        (exec 3<>/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null && return 0
    done
    echo "$ARM: server did not come up"; sed -n '1,20p' "$RUN/d/srv.log"; return 1
}
halt() { [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; PID=""; sleep 0.3; }

echo "arm=$ARM sha=$(sha256sum "$BIN" | cut -c1-16) port=$PORT reps=$REPS samples=$SAMPLES"
for r in $(seq "$REPS"); do
    # D1: worker write load, poll flat out.
    boot || exit 1
    printf 'arm=%s rep=%d D1-guard   ' "$ARM" "$r"
    python3 "$SD/expiry_clock_lag.py" "$PORT" "$SAMPLES" 60 8 0
    halt
    # D2: idle main loop, 5ms poll gap.
    boot || exit 1
    printf 'arm=%s rep=%d D2-clock   ' "$ARM" "$r"
    python3 "$SD/expiry_clock_lag.py" "$PORT" "$SAMPLES" 60 0 5 1
    halt
done
