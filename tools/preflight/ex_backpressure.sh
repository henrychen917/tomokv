#!/bin/bash
# ex_backpressure.sh -- boot a server and drive its worker-dispatch rings into back-pressure.
#
# Closes the A3 acceptance gap: exDispatchPush() and csPushSpin() each contain a spin loop that no
# test in this tree had ever entered (INFO tomokv_ex_queue_full read 0 across a full bigstress run
# AND a full stress_validation soak), so the 2026-08-02 change to both was unverified by
# construction. See tools/preflight/ex_backpressure.py for exactly what this does and does not
# prove -- in particular it proves REACHABILITY and correctness-under-back-pressure, NOT that A3
# is beneficial.
#
# usage: ex_backpressure.sh <server-binary> [tag]
#
# Must run under the shared box lock like anything else that loads the server:
#   tools/preflight/withbox.sh -w 3600 tools/preflight/ex_backpressure.sh src/redis-server
set -u

BIN=${1:?usage: ex_backpressure.sh <server-binary> [tag]}
TAG=${2:-adhoc}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
PORT=${PORT:-5898}
IO=${IO:-4}
EX=${EX:-4}
CONNS=${CONNS:-128}
DEPTH=${DEPTH:-512}
SECONDS_PER_ARM=${SECONDS_PER_ARM:-8}

OUT=$(mktemp -d "${TMPDIR:-/tmp}/exbp.XXXXXX")
CLI=$(dirname "$BIN")/redis-cli
[ -x "$CLI" ] || CLI=$REPO/src/redis-cli

# Stage under a UNIQUE name, and only ever signal the pid we captured. `pkill -x redis-server`
# would kill other sessions' servers on this shared box, and would NOT match a staged binary --
# both halves of that trap have cost real time here before.
STAGED=$OUT/redis-exbp-$$
cp "$BIN" "$STAGED"; chmod +x "$STAGED"

SRV=""
cleanup() {
    [ -n "$SRV" ] || return 0
    kill -TERM "$SRV" 2>/dev/null
    for _ in $(seq 1 40); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$SRV" 2>/dev/null
}
trap cleanup EXIT INT TERM

# One server at a time on this box. The AUTHORITATIVE mechanism is the shared box lock in
# withbox.sh, which the caller already holds; this is only a sanity check, so it must be precise
# rather than broad. An earlier version matched the whole 78xx/79xx space and refused to run
# because an unrelated service -- not ours, no visible owning process, and on a port this tree
# never uses -- was listening on 7878. A guard that fires on other people's ports is not a safety
# feature, it is a self-inflicted outage. Check the port we are about to bind, and separately any
# port actually held by a redis-like process we can see.
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
    echo "ex-backpressure[$TAG]	SKIP	port $PORT already in use; one server at a time on this box"
    exit 2
fi
if ss -ltnp 2>/dev/null | grep -qE 'users:\(\("(redis|tomo)'; then
    echo "ex-backpressure[$TAG]	SKIP	a redis-like server is already listening; one at a time"
    exit 2
fi

# Deep pipelines are the whole mechanism here, so the client-output-buffer and query-buffer limits
# must not be what stops us. Defaults are generous enough for 512-deep GET/MGET bursts, but the
# ring depth is DERIVED from pipeline depth (4 * (io+1) * pipeline_depth, floored at 2048), so we
# leave tomokv-pipeline-depth alone: raising it would raise the very ring we are trying to fill.
taskset -c 0-7 "$STAGED" --port "$PORT" --bind 127.0.0.1 --dir "$OUT" \
    --tomokv-nodes 1 --tomokv-thread-io "$IO" --tomokv-thread-ex "$EX" \
    --tomokv-thread-mode static \
    --save '' --appendonly no --protected-mode no --enable-debug-command local \
    --logfile "$OUT/server.log" --loglevel notice >"$OUT/stdout.log" 2>&1 &
SRV=$!

for _ in $(seq 1 60); do
    [ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] && break
    kill -0 "$SRV" 2>/dev/null || { echo "ex-backpressure[$TAG]	FAIL	server died during boot (see $OUT/server.log)"; exit 1; }
    sleep 0.3
done
if [ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" != PONG ]; then
    echo "ex-backpressure[$TAG]	FAIL	server never answered PING (see $OUT/server.log)"; exit 1
fi

# ulimit: CONNS sockets plus the server's own. A probe that dies on EMFILE would report ABORTED,
# which is honest but useless -- raise it here where we can.
ulimit -n "$(( CONNS * 4 + 1024 ))" 2>/dev/null || true

taskset -c 16-23 python3 "$DIR/ex_backpressure.py" \
    --port "$PORT" --io-threads "$IO" \
    --conns "$CONNS" --depth "$DEPTH" --seconds "$SECONDS_PER_ARM" \
    2>&1 | tee "$OUT/probe.out"
rc=${PIPESTATUS[0]}

# Crash evidence gathered BEFORE the server goes away.
cm=$(grep -cE 'Guru Meditation|ASSERTION FAILED|=== REDIS BUG REPORT|crashed by signal|Sanitizer' "$OUT/server.log" 2>/dev/null)
cm=${cm:-0}
[ "$cm" = 0 ] || { echo "  crash_markers=$cm in $OUT/server.log"; rc=1; }

case $rc in 0) res=PASS ;; 2) res=SKIP ;; *) res=FAIL ;; esac
echo "ex-backpressure[$TAG]	$res	$(grep -E '^(PASS|FAIL|SKIP)' "$OUT/probe.out" | head -1)"
[ "$res" = PASS ] && rm -rf "$OUT" || echo "  artifacts: $OUT"
exit $rc
