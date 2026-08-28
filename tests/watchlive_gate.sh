#!/usr/bin/env bash
# WATCH liveness gate: EXEC must answer while the server answers PING.
#
# Usage: watchlive_gate.sh [PORT] [CORES] [REPS] [BIN]
#   PORT   default 7510      CORES default 32-47
#   REPS   default 6         BIN   default <repo>/build/tomokv
#
# WHY A FRESH SERVER PER REPETITION.  The defect is a wait-for cycle: once it forms, the affected
# executors never recover, so every later repetition on the same boot is not an independent trial
# (it reports "wedged" because the FIRST one wedged).  A rate is only a rate if each repetition
# starts from a clean server, so each one boots its own, resolves the pid FROM THE LISTENING
# SOCKET (never by name -- other lanes run a binary of the same name), and stops that exact pid.
#
# ROWS
#   watch conns=4/8/16, --atomic 1   the defect's own cells; the pre-fix rates were 6/6, 6/6, 6/6
#   no-watch control conns=16        identical shape, WATCH frames removed -- MUST be 0
#   watch conns=16, --atomic 0       the reservation path with the atomic group lane off
# The control is a hard requirement, not a decoration: a detector that cannot report zero says
# nothing about the runs that report non-zero.
#
# NOT VACUOUS.  Every armed row also asserts the mechanism was ENTERED, by reading
# watch_reservation_waits + watch_reservation_coexist from INFO before deciding the row passed.
# A run in which no unit ever met a foreign undecided reservation has not tested anything, and a
# row that is clean AND moved neither counter fails with "never entered".

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PORT="${1:-7510}"
CORES="${2:-32-47}"
REPS="${3:-6}"
BIN="${4:-$ROOT/build/tomokv}"
DEADLINE=5

FAIL=0
LOG=$(mktemp -d)
trap 'rm -rf "$LOG"' EXIT

listener_pids() {
    ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

stop_all() {
    local i pids
    for i in $(seq 1 40); do
        pids=$(listener_pids); [ -z "$pids" ] && return 0
        for p in $pids; do kill -TERM "$p" 2>/dev/null; done
        sleep 0.25
    done
    pids=$(listener_pids); for p in $pids; do kill -KILL "$p" 2>/dev/null; done
    sleep 0.5
    [ -z "$(listener_pids)" ]
}

boot() {   # boot <extra server args...>
    # A leftover listener would join the next start under SO_REUSEPORT and split the client load
    # silently across two servers, which invalidates the measurement. Refuse instead.
    if [ -n "$(listener_pids)" ]; then echo "  FAIL listener already on $PORT"; return 1; fi
    taskset -c "$CORES" "$BIN" --port "$PORT" --enable-debug-command yes "$@" \
        >"$LOG/server.log" 2>&1 &
    local i pids
    for i in $(seq 1 120); do
        pids=$(listener_pids)
        [ -n "$pids" ] && break
        sleep 0.1
    done
    pids=$(listener_pids)
    if [ -z "$pids" ]; then echo "  FAIL server did not come up on $PORT"; return 1; fi
    if [ "$(echo "$pids" | wc -l)" -ne 1 ]; then echo "  FAIL $(echo "$pids" | wc -l) listeners on $PORT"; return 1; fi
    return 0
}

# Evidence that the run entered the machinery at all: blocking waits on an EXEC validate claim
# PLUS atomic-group reservations that had to coexist with a foreign undecided one. The second term
# is the defect's own precondition, and it is the one that moves when --atomic 1 makes cross-shard
# writes into groups; the first is what moves with --atomic 0. A row that is clean and moved
# NEITHER has not tested anything, so the gate fails it.
waits_counter() {
    python3 - "$PORT" <<'PY' 2>/dev/null || echo 0
import socket, sys
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)
s.settimeout(5)
s.sendall(b"*2\r\n$4\r\nINFO\r\n$5\r\nstats\r\n")
buf = b""
try:
    while b"watch_reservation_coexist" not in buf:
        d = s.recv(65536)
        if not d: break
        buf += d
except Exception:
    pass
total = 0
for line in buf.split(b"\r\n"):
    for field in (b"watch_reservation_waits:", b"watch_reservation_coexist:"):
        if line.startswith(field):
            total += int(line.split(b":")[1])
print(total)
PY
}

row() {  # row <label> <conns> <watchflag> <boot args...>
    local label="$1" conns="$2" wflag="$3"; shift 3
    local wedged=0 ran=0 entered=0 rate
    local r
    for r in $(seq 1 "$REPS"); do
        stop_all >/dev/null
        boot "$@" || { FAIL=$((FAIL+1)); return; }
        rate=$(timeout 120 python3 "$HERE/watchlive.py" 127.0.0.1 "$PORT" --conns "$conns" \
                  --reps 1 --deadline "$DEADLINE" --rate-only $wflag 2>&1 | tail -1)
        entered=$((entered + $(waits_counter)))
        stop_all >/dev/null
        ran=$((ran+1))
        [ "$rate" = "1/1" ] && wedged=$((wedged+1))
    done
    if [ "$wedged" -ne 0 ]; then
        echo "  FAIL $label  wedged $wedged/$ran  (reservation contention $entered)"
        FAIL=$((FAIL+1))
    elif [ -n "$wflag" ]; then
        echo "  ok   $label  wedged $wedged/$ran  (control; reservation waits $entered)"
    elif [ "$entered" -eq 0 ]; then
        echo "  FAIL $label  wedged 0/$ran but the reservation machinery was NEVER ENTERED (waits+coexist = 0)"
        FAIL=$((FAIL+1))
    else
        echo "  ok   $label  wedged $wedged/$ran  (reservation contention $entered)"
    fi
}

echo "watchlive gate (port $PORT, cores $CORES, reps $REPS, fresh server per repetition)"
row "watch conns=4  --atomic 1 " 4  ""           --atomic 1
row "watch conns=8  --atomic 1 " 8  ""           --atomic 1
row "watch conns=16 --atomic 1 " 16 ""           --atomic 1
row "no-watch control conns=16 " 16 "--no-watch" --atomic 1
row "watch conns=16 --atomic 0 " 16 ""           --atomic 0

echo
if [ "$FAIL" -eq 0 ]; then echo "watchlive gate PASS"; else echo "watchlive gate FAIL ($FAIL)"; fi
exit $FAIL
