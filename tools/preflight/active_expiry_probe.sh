#!/bin/bash
# ACTIVE-EXPIRY PROBE — does a TTL'd key that is never touched again ever get reclaimed?
#
# THE QUESTION. Stock Redis expires keys two ways: LAZILY (expireIfNeeded on access) and ACTIVELY
# (activeExpireCycle, driven from serverCron/beforeSleep on the main thread). A functional test
# cannot tell them apart, because lazy expiry makes every *observable* read return the right
# answer; only the memory of the never-read keys differs. So this probe deliberately never touches
# the keys again and watches the SIZE of the keyspace instead of any key's value.
#
# HOW IT OBSERVES (three rules, each of which the naive version gets wrong):
#   1. `INFO keyspace` is USELESS on this fork — it prints kvstoreSize(server.db[j]...), and
#      server.db is the empty DECOY (initServer: "real data lives in ex_dbs"). It reports nothing
#      at all with sharding on. DBSIZE is the observable: dbsizeCommand() sums the real node dbs.
#   2. DBSIZE must not itself expire anything. It reads the per-dict `used` counters and never
#      touches a key, so polling it cannot mask the answer via lazy expiry. (A `SCAN`/`KEYS`/`GET`
#      poll WOULD mask it — those run expireIfNeeded on what they walk.)
#   3. Polling keeps the main event loop turning, which is the *best* case for the active cycle
#      (its fast pass runs from beforeSleep). If the count still does not fall, that is decisive.
#
# `expired_keys_active` from INFO stats is the direct instrument: it is incremented ONLY by
# activeExpireCycleTryExpire(). expired_keys - expired_keys_active is the lazy count.
#
# BOTH REGIMES MATTER. shared_node_dbs = (workers-per-node > 1), and it decides FLATSTORE:
# `--tomokv-thread-ex 1` is a DICT-backed keyspace, `--tomokv-thread-ex >=2` is a flat table.
# A defect can hide in one and not the other, so the caller runs both.
#
# Usage: active_expiry_probe.sh <dir-with-binary> <binary-name> <port> <ex-threads> <keys> <ttl_s> <watch_s>
# Prints one PASS/FAIL verdict line. Exit 0 = active expiry demonstrably ran.
set -u
DIR=${1:?usage: active_expiry_probe.sh <dir> <binname> <port> <ex> <keys> <ttl_s> <watch_s>}
BINNAME=${2:?binary name required}
PORT=${3:?port required}
EX=${4:-4}
KEYS=${5:-200000}
TTL=${6:-10}
WATCH=${7:-45}

BIN="$DIR/$BINNAME"
CLI="$DIR/redis-cli"
[ -x "$BIN" ] || { echo "active_expiry_probe: no executable $BIN"; exit 2; }
[ -x "$CLI" ] || { echo "active_expiry_probe: no executable $CLI"; exit 2; }

RUN=$(mktemp -d "${TMPDIR:-/tmp}/aexp.XXXXXX")
PID=""
# BOX RULE: never `pkill -f` (matches this script's own command line) and never `pkill -x
# redis-server` (this box is shared; that kills other agents' servers). Kill the recorded pid only.
cleanup() { [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -rf "$RUN"; }
trap cleanup EXIT

mkdir -p "$RUN/d"
taskset -c 0-7 "$BIN" --port "$PORT" --dir "$RUN/d" \
    --tomokv-nodes 1 --tomokv-cores-per-node 8 --tomokv-thread-io 4 --tomokv-thread-ex "$EX" \
    --tomokv-thread-mode static \
    --save '' --appendonly no --protected-mode no --daemonize no \
    --logfile "$RUN/d/srv.log" >/dev/null 2>&1 &
PID=$!
up=0
for _ in $(seq 80); do
    sleep 0.25
    if "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG; then up=1; break; fi
done
[ "$up" = 1 ] || { echo "active_expiry_probe: server did not come up (ex=$EX)"; sed -n '1,30p' "$RUN/d/srv.log"; exit 2; }

# Load KEYS keys, each with a TTL, in one pipe. Values are small: we are measuring the COUNT.
# `EX $TTL` is relative to each SET, so the load WINDOW is part of the deadline -- and redis-cli
# --pipe flushes in bursts, which can spread the SETs over many seconds if the generator is slow
# (a bash printf loop is; that produced a run where 82% of the keys were still 10s from their
# deadline when the watch started, and the plateau looked like a stalled expiry). Generate with
# python3 so the window is ~1s, and measure it so the wait can cover it either way.
t_load_start=$SECONDS
python3 -c "
import sys
n=int(sys.argv[1]); ttl=sys.argv[2]
w=sys.stdout.write
for i in range(1,n+1):
    k='aexp:%d'%i; v='v%d'%i
    w('*5\r\n\$3\r\nSET\r\n\$%d\r\n%s\r\n\$%d\r\n%s\r\n\$2\r\nEX\r\n\$%d\r\n%s\r\n'%(len(k),k,len(v),v,len(ttl),ttl))
" "$KEYS" "$TTL" | "$CLI" -p "$PORT" --pipe >"$RUN/load.out" 2>&1
grep -q "errors: 0" "$RUN/load.out" || { echo "active_expiry_probe: load reported errors"; cat "$RUN/load.out"; exit 2; }
load_secs=$((SECONDS - t_load_start))

n0=$("$CLI" -p "$PORT" dbsize)
# INVALID-RESULT GUARD: a dead server yields an empty/zero reply rather than an error.
case "$n0" in ''|0) echo "active_expiry_probe: INVALID baseline dbsize='$n0' (server dead?)"; exit 2;; esac
rss0=$("$CLI" -p "$PORT" info memory | tr -d '\r' | awk -F: '/^used_memory:/{print $2}')
info_ks=$("$CLI" -p "$PORT" info keyspace | tr -d '\r' | grep -c '^db[0-9]*:keys=')

echo "  ex=$EX loaded=$n0 used_memory=$rss0 info_keyspace_lines=$info_ks ttl=${TTL}s load=${load_secs}s watch=${WATCH}s"

# Wait out the TTL (plus the load window: the FIRST key's deadline is TTL after the load STARTED,
# the last one's is TTL after it ended), then watch with NO traffic other than the non-touching
# DBSIZE/INFO poll.
sleep $((TTL + load_secs + 2))
end=$((SECONDS + WATCH))
last=$n0
while [ $SECONDS -lt $end ]; do
    sleep 3
    n=$("$CLI" -p "$PORT" dbsize)
    case "$n" in ''|0*) : ;; esac
    [ -z "$n" ] && { echo "active_expiry_probe: INVALID dbsize (server dead?)"; exit 2; }
    last=$n
    printf '    t=+%-3ss dbsize=%s\n' "$((SECONDS))" "$n"
    [ "$n" = 0 ] && break
done

stats=$("$CLI" -p "$PORT" info stats | tr -d '\r')
act=$(echo "$stats" | awk -F: '/^expired_keys_active:/{print $2}')
tot=$(echo "$stats" | awk -F: '/^expired_keys:/{print $2}')
rss1=$("$CLI" -p "$PORT" info memory | tr -d '\r' | awk -F: '/^used_memory:/{print $2}')

echo "  ex=$EX final dbsize=$last (from $n0)  expired_keys=$tot expired_keys_active=$act  used_memory $rss0 -> $rss1"

# VERDICT. Active expiry is working iff the untouched keys were reclaimed with no client touching
# them. Require BOTH: the counter attributed to the active cycle moved, and the keyspace drained
# to <5% of what was loaded (a handful of stragglers mid-cycle is fine).
thresh=$(( n0 / 20 ))
if [ "${act:-0}" -gt 0 ] && [ "$last" -le "$thresh" ]; then
    echo "  ex=$EX VERDICT: PASS (active expiry reclaimed untouched keys)"
    exit 0
fi
echo "  ex=$EX VERDICT: FAIL (untouched TTL'd keys were NOT reclaimed: dbsize $n0 -> $last, expired_keys_active=$act)"
exit 1
