#!/bin/bash
# close_asap_livelock.sh -- boot a server and drive docs/BUGS.md N's livelock at it.
#
# See tools/preflight/close_asap_livelock.py for the defect and why this shape reproduces it.
# The whole point of this probe is that it DISCRIMINATES: run it against a pre-fix binary and it
# must wedge; against the fixed binary it must survive AND report a non-zero deferral counter.
# A probe that passes on both proves nothing (docs/BUGS.md, vacuous-validation).
#
# usage: close_asap_livelock.sh <server-binary> [tag]
#   tools/preflight/withbox.sh -w 900 tools/preflight/close_asap_livelock.sh src/redis-server
set -u
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"

BIN=${1:?usage: close_asap_livelock.sh <server-binary> [tag]}
TAG=${2:-adhoc}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
PORT=${PORT:-5895}
IO=${IO:-8}
EX=${EX:-8}
ROUNDS=${ROUNDS:-40}
CONNS=${CONNS:-64}
DEPTH=${DEPTH:-256}
MODE=${MODE:-auto}
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
[ $((IO + EX)) -eq 16 ] || { echo "close-asap-livelock[$TAG]	FAIL	IO+EX must equal 16 per node"; exit 2; }

OUT=$(mktemp -d "${TMPDIR:-/tmp}/casaplive.XXXXXX")
CLI=$REPO/src/redis-cli
STAGED=$OUT/redis-casap-$$
cp "$BIN" "$STAGED"; chmod +x "$STAGED"

SRV=""
cleanup() {
    [ -n "$SRV" ] || return 0
    kill -TERM "$SRV" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$SRV" 2>/dev/null
}
trap cleanup EXIT INT TERM

if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
    echo "close-asap-livelock[$TAG]	SKIP	port $PORT in use"; exit 2
fi

taskset -c "$SERVER_CORES" "$STAGED" --port "$PORT" --bind 127.0.0.1 --dir "$OUT" \
    --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-io "$IO" --tomokv-thread-ex "$EX" \
    --tomokv-thread-mode "$MODE" \
    --save '' --appendonly no --protected-mode no --enable-debug-command local \
    --logfile "$OUT/server.log" --loglevel notice >"$OUT/stdout.log" 2>&1 &
SRV=$!

for _ in $(seq 1 80); do
    [ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] && break
    kill -0 "$SRV" 2>/dev/null || { echo "close-asap-livelock[$TAG]	FAIL	server died at boot"; exit 1; }
    sleep 0.3
done
[ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] || {
    echo "close-asap-livelock[$TAG]	FAIL	server never answered PING"; exit 1; }
preflight_assert_standard_boot "$OUT/server.log" "$SRV" "$IO" "$EX" || exit 1

ulimit -n "$(( CONNS * 8 + 4096 ))" 2>/dev/null || true

taskset -c "$LOAD_CORES" timeout 420 python3 "$DIR/close_asap_livelock.py" \
    --port "$PORT" --rounds "$ROUNDS" --conns "$CONNS" --depth "$DEPTH" 2>&1 | tee "$OUT/probe.out"
rc=${PIPESTATUS[0]}
[ "$rc" = 124 ] && echo "TIMEOUT	the probe itself did not finish in 420s -- treat as a wedge" | tee -a "$OUT/probe.out"

# The resize watchdog is the SYMPTOM this defect produces (main starved on the allocator lock).
# Report it: on the fixed build it must stay 0 here.
wd=$(grep -c 'WATCHDOG aborted' "$OUT/server.log" 2>/dev/null); wd=${wd:-0}
cm=$(grep -cE 'Guru Meditation|ASSERTION FAILED|=== REDIS BUG REPORT|crashed by signal|Sanitizer' "$OUT/server.log" 2>/dev/null); cm=${cm:-0}
echo "  resize_watchdog_aborts=$wd crash_markers=$cm"
[ "$cm" = 0 ] || rc=1

case $rc in 0) res=PASS ;; 2) res=SKIP ;; *) res=FAIL ;; esac
echo "close-asap-livelock[$TAG]	$res	$(grep -E '^(PASS|FAIL|TIMEOUT)' "$OUT/probe.out" | head -1)"
[ "$res" = PASS ] && rm -rf "$OUT" || echo "  artifacts: $OUT"
exit $rc
