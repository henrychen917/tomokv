#!/bin/bash
# ACTIVE-SUBEXPIRY PROBE — does a HASH FIELD with a TTL that is never touched again get reclaimed?
#
# Sibling of active_expiry_probe.sh, same defect class one level down (bug #50 vs bug #42).
#
# THE QUESTION. Hash-field TTLs (HEXPIRE/HPEXPIRE) are reclaimed two ways: LAZILY, when something
# reads the hash (hashTypeExpire off the lookup path), and ACTIVELY, by activeSubexpiresCycle()
# driven from serverCron. That active cycle walks `server.db[currentDb].subexpires` — and under
# tomokv sharding server.db is the empty DECOY (initServer: "real data lives in ex_dbs"). The real
# hashes live in server.node_dbs[node][dbid], whose subexpires estore nothing was walking. So a
# field given a TTL and never touched again was retained for the life of the process: an unbounded
# leak that NO functional test catches, because lazy expiry keeps every observable READ correct.
#
# HOW IT OBSERVES. The probe must never touch a probe hash, or lazy expiry does the work and the
# result is a tautology. So:
#   1. ONE FIELD PER HASH, and that field carries the TTL. When it expires the hash has no fields
#      left and the KEY is removed from the keyspace, which makes a FIELD-level leak visible in
#      DBSIZE — a counter that reads per-dict `used` and touches no key.
#   2. `INFO keyspace` is useless here for the same reason as in the sibling probe: it prints the
#      decoy's sizes. DBSIZE sums the real node dbs.
#   3. `expired_subkeys_active` from INFO stats is the direct instrument — the count attributed to
#      the ACTIVE field cycle specifically. `expired_subkeys - expired_subkeys_active` is lazy.
#
# MEASURED PROPERTY OF THIS FORK, and the reason DBSIZE is a sound instrument here: the LAZY field
# path does NOT remove the emptied hash from the keyspace. On the pre-fix binary a hash whose only
# field's TTL had elapsed still answered DBSIZE=1 and HLEN=1 forever, even after HGETALL returned
# empty and HTTL returned -2, and `expired_subkeys` stayed 0. So every DBSIZE decrement this probe
# sees is attributable to the ACTIVE cycle. That also means a "touch the survivors" control would
# prove nothing — it reclaims nothing on either binary — which is why the control below is built
# out of HTTL witnesses instead.
#
# THE CONTROL matters as much as the measurement: a probe reporting "not reclaimed" proves nothing
# if the TTLs were never armed or had not yet elapsed. Two witnesses, both OUTSIDE the counted
# population, establish exactly that and nothing else:
#   CANARY  — armed with a 10-MINUTE TTL. HTTL must read ~600 right after the load (proves HPEXPIRE
#             arms a field TTL at all) and the key must still be present at the end (proves the
#             cycle reclaims by DEADLINE and is not just flushing the keyspace).
#   WITNESS — armed with the SAME short TTL as the population. After the wait HTTL must read -2,
#             proving the population's deadlines have genuinely elapsed. A flat DBSIZE after that
#             is therefore a missing ACTIVE reclaim, not an unexpired TTL.
#
# BOTH REGIMES ARE RUN, and both must pass. shared_node_dbs = (workers-per-node > 1) and it selects
# the storage engine: `--tomokv-thread-ex 1` is a DICT-backed keyspace, `--tomokv-thread-ex >=2` is
# FLATSTORE. This defect is upstream of that split (it is about WHICH db array gets walked), so both
# regimes must move together — if only one does, the fix is in the wrong place.
#
# Usage: active_subexpiry_probe.sh <binary> [hashes] [ttl_s] [watch_s] [base_port] [ex-list]
# Exit 0 = active field expiry demonstrably ran in EVERY regime.
set -u
BIN=${1:?usage: active_subexpiry_probe.sh <binary> [hashes] [ttl_s] [watch_s] [base_port] [ex-list]}
HASHES=${2:-100000}
TTL=${3:-10}
WATCH=${4:-45}
BASEPORT=${5:-5996}
EXLIST=${6:-"1 4"}

DIR=$(cd "$(dirname "$BIN")" && pwd)
# redis-cli is normally beside the binary, but postmerge.sh STAGES the server under a private name
# in a directory that holds no cli. Fall back to the build tree this script lives in.
CLI="$DIR/redis-cli"
[ -x "$CLI" ] || CLI="$(cd "$(dirname "$0")/../../src" && pwd)/redis-cli"
[ -x "$BIN" ] || { echo "active_subexpiry_probe: no executable $BIN"; exit 2; }
[ -x "$CLI" ] || { echo "active_subexpiry_probe: no executable redis-cli (looked in $DIR and the build tree)"; exit 2; }

PID=""
RUN=""
# BOX RULE: never `pkill -f` (this script's own command line matches) and never `pkill -x
# redis-server` (shared box; that kills other agents' servers). Kill the recorded pid only.
cleanup() { [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; [ -n "$RUN" ] && rm -rf "$RUN"; }
trap cleanup EXIT

run_one() {   # $1 = ex threads, $2 = port ; echoes a verdict line, returns 0 PASS / 1 FAIL / 2 INVALID
  local EX=$1 PORT=$2
  RUN=$(mktemp -d "${TMPDIR:-/tmp}/asubexp.XXXXXX")
  mkdir -p "$RUN/d"
  taskset -c 0-7 "$BIN" --port "$PORT" --dir "$RUN/d" \
      --tomokv-nodes 1 --tomokv-cores-per-node 8 --tomokv-thread-io 4 --tomokv-thread-ex "$EX" \
      --tomokv-thread-mode static \
      --save '' --appendonly no --protected-mode no --daemonize no \
      --logfile "$RUN/d/srv.log" >/dev/null 2>&1 &
  PID=$!
  local up=0 _
  for _ in $(seq 80); do
      sleep 0.25
      if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG; then up=1; break; fi
  done
  [ "$up" = 1 ] || { echo "  ex=$EX INVALID: server did not come up"; sed -n '1,30p' "$RUN/d/srv.log"; return 2; }

  # Load: HASHES hashes, one field each, then arm that field with a TTL. HPEXPIRE takes ms and is
  # SIX arguments (HPEXPIRE key ms FIELDS numfields field) -- an *7 array header here silently
  # desynchronises the whole pipe and redis-cli dies with a protocol error mid-load.
  # Generate with python3 so the load window is ~1s -- the TTL is relative to each HPEXPIRE, so a
  # slow generator spreads the deadlines across the whole watch and a plateau would be
  # indistinguishable from a stalled cycle (the sibling probe learned this the hard way).
  local t0=$SECONDS
  python3 -c "
import sys
n=int(sys.argv[1]); ttlms=str(int(sys.argv[2])*1000)
w=sys.stdout.write
for i in range(1,n+1):
    k='asx:%d'%i
    w('*4\r\n\$4\r\nHSET\r\n\$%d\r\n%s\r\n\$1\r\nf\r\n\$2\r\nv1\r\n'%(len(k),k))
    w('*6\r\n\$8\r\nHPEXPIRE\r\n\$%d\r\n%s\r\n\$%d\r\n%s\r\n\$6\r\nFIELDS\r\n\$1\r\n1\r\n\$1\r\nf\r\n'%(len(k),k,len(ttlms),ttlms))
" "$HASHES" "$TTL" | "$CLI" -p "$PORT" --pipe >"$RUN/load.out" 2>&1
  grep -q "errors: 0" "$RUN/load.out" || { echo "  ex=$EX INVALID: load reported errors"; cat "$RUN/load.out"; return 2; }
  local load_secs=$((SECONDS - t0))

  local n0; n0=$("$CLI" -p "$PORT" dbsize)
  # INVALID-RESULT GUARD: a dead server yields an empty/zero reply rather than an error.
  case "$n0" in ''|0) echo "  ex=$EX INVALID: baseline dbsize='$n0' (server dead?)"; return 2;; esac

  # GATE-OPENED GUARD: prove the TTLs are actually armed before believing anything downstream.
  # Both witnesses are created AFTER n0 is read, so neither is part of the counted population.
  "$CLI" -p "$PORT" hset asx:canary f v1 >/dev/null
  "$CLI" -p "$PORT" hpexpire asx:canary 600000 FIELDS 1 f >/dev/null
  "$CLI" -p "$PORT" hset asx:witness f v1 >/dev/null
  "$CLI" -p "$PORT" hpexpire asx:witness "$((TTL*1000))" FIELDS 1 f >/dev/null
  local cttl; cttl=$("$CLI" -p "$PORT" httl asx:canary FIELDS 1 f | tr -d '\r')
  case "$cttl" in ''|-1|-2) echo "  ex=$EX INVALID: HPEXPIRE did not arm a field TTL (httl=$cttl)"; return 2;; esac

  echo "  ex=$EX loaded=$n0 hashes (1 TTL'd field each) canary_httl=${cttl}s ttl=${TTL}s load=${load_secs}s watch=${WATCH}s"

  # Wait out the TTL (plus the load window: the first field's deadline is TTL after the load
  # STARTED, the last one's TTL after it ended), then watch with NO traffic but a non-touching poll.
  sleep $((TTL + load_secs + 2))
  local end=$((SECONDS + WATCH)) last=$n0 n
  while [ $SECONDS -lt $end ]; do
      sleep 3
      n=$("$CLI" -p "$PORT" dbsize)
      [ -z "$n" ] && { echo "  ex=$EX INVALID: empty dbsize (server dead?)"; return 2; }
      last=$n
      printf '    ex=%s t=+%-3ss dbsize=%s\n' "$EX" "$((SECONDS))" "$n"
      [ "$n" -le 2 ] && break     # canary + witness, both outside the counted population
  done

  local stats act tot
  stats=$("$CLI" -p "$PORT" info stats | tr -d '\r')
  act=$(echo "$stats" | awk -F: '/^expired_subkeys_active:/{print $2}')
  tot=$(echo "$stats" | awk -F: '/^expired_subkeys:/{print $2}')
  echo "  ex=$EX after watch dbsize=$last (from $n0)  expired_subkeys=$tot expired_subkeys_active=$act"

  # CONTROL. Did the population's deadlines actually elapse? The witness carries the SAME TTL, so
  # HTTL=-2 on it means every counted field is past its deadline too. Without this a flat DBSIZE
  # would be ambiguous between "active reclaim missing" and "nothing was due yet".
  local wttl; wttl=$("$CLI" -p "$PORT" httl asx:witness FIELDS 1 f | tr -d '\r')
  echo "  ex=$EX control: witness httl=$wttl (-2 = its deadline elapsed, so the population's did too)"
  if [ "$wttl" != "-2" ]; then
      echo "  ex=$EX VERDICT: INVALID (the witness TTL had NOT elapsed when the watch ended -- this run"
      echo "                          measured an unexpired population, not active reclaim. Raise watch_s.)"
      return 2
  fi
  # And the canary, armed for 10 minutes, must still be here: reclaim must be by DEADLINE.
  local cex; cex=$("$CLI" -p "$PORT" exists asx:canary | tr -d '\r')
  if [ "$cex" != "1" ]; then
      echo "  ex=$EX VERDICT: INVALID (the 10-minute canary was reclaimed too -- whatever drained the"
      echo "                          keyspace is not honouring field deadlines)"
      return 2
  fi

  # VERDICT. Active field expiry works iff untouched TTL'd fields were reclaimed with nothing
  # reading them. Require BOTH: the counter attributed to the ACTIVE cycle moved, and the keyspace
  # drained to <5% of what was loaded (the two witnesses plus a few stragglers mid-cycle are fine).
  local thresh=$(( n0 / 20 ))
  if [ "${act:-0}" -gt 0 ] && [ "$last" -le "$thresh" ]; then
      echo "  ex=$EX VERDICT: PASS (active cycle reclaimed untouched hash-field TTLs)"
      return 0
  fi
  echo "  ex=$EX VERDICT: FAIL (untouched TTL'd fields were NOT actively reclaimed: dbsize $n0 -> $last,"
  echo "                        expired_subkeys_active=$act, while the witness proves the TTLs elapsed)"
  return 1
}

rc=0
p=$BASEPORT
for ex in $EXLIST; do
  echo "=== active-subexpiry probe: tomokv-thread-ex $ex ==="
  run_one "$ex" "$p" || rc=$?
  kill -9 "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; PID=""
  rm -rf "$RUN"; RUN=""
  p=$((p+1))
  sleep 1
done
echo "active_subexpiry_probe: exit=$rc"
exit $rc
