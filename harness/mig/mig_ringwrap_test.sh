#!/usr/bin/env bash
# Regression gate for the migLogPush wrap-safe full-check (ee451 review, P0). Drives a migration
# whose effect log crosses the 64K-entry ring boundary (the old masked-vs-raw full test disarmed
# backpressure permanently once head >= 65536): seed enough keys that the COLD SCAN ALONE emits
# > 64K log entries, migrate, and assert the migration completes (no false-full wedge at wrap),
# checksums converge pre-cutover, and data is byte-exact post-flip (no lapped/lost effects).
# Hang-proof: timeouts everywhere, server killed by PID, no bare wait. Env: PORT, NKEYS.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$REPO/src/redis-cli -p ${PORT:=6504}"
NKEYS=${NKEYS:-700000}   # uniform over buckets => ~NKEYS/8 keys land in w0's suffix half (>64K needs NKEYS>=524k)
D=$(mktemp -d)
cleanup(){ [ -n "${SPID:-}" ] && kill -9 "$SPID" 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT
pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; sleep 0.5
"$REPO/src/redis-server" --tomokv-thread-io 2 --tomokv-thread-ex 4 --enable-debug-command yes \
  --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.3; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { echo "BOOT FAIL"; exit 1; }
fail=0; ok(){ echo "  OK   $1"; }; bad(){ echo "  FAIL $1"; fail=$((fail+1)); }

# bucket-space size from probes; w0 suffix = [N/8, N/4)
maxb=0; for i in $(seq 1 60); do
  b=$(timeout 3 $CLI debug reshard find "rw:$i" 2>/dev/null | tr -d '\r' | grep -o 'bucket=[0-9]*' | cut -d= -f2)
  [ -n "$b" ] && [ "$b" -gt "$maxb" ] && maxb=$b; done
NB=4096; [ "$maxb" -ge 4096 ] && NB=16384
LO=$((NB/8)); HI=$((NB/4))
echo "space=$NB migrating w0 suffix [$LO,$HI); seeding $NKEYS keys..."
seq 1 $NKEYS | awk '{print "set rw:"$1" v"$1}' | timeout -s KILL 180 $CLI --pipe >/dev/null 2>&1
db0=$(timeout 5 $CLI dbsize|tr -d '\r'); echo "seeded dbsize=$db0"
[ "$db0" -ge $NKEYS ] || { bad "seed incomplete ($db0)"; }

t0=$SECONDS
# Byte-exact baseline, taken BEFORE the arm. `DEBUG RESHARD VERIFY` walks the keyspace, so it is
# refused while a migration is active — deliberately: it used to be folded into STATUS, which every
# reshard harness polls in a loop, and an O(keyspace) walk on an IO thread stalls the cutover
# coordinator it is supposed to be observing. The `total` line is invariant across a correct
# migration in both shard shapes (ownership-only under shared_node_dbs; count-additive +
# XOR-folded under the copy shape), so before/after equality IS the byte-exactness check.
VPRE=$(timeout 120 $CLI debug reshard verify $LO $HI 2>/dev/null | tr -d '\r' | grep '^total')
[ -n "$VPRE" ] && ok "pre-migration checksum ($VPRE)" || bad "VERIFY returned nothing pre-arm"
[ "$(timeout 5 $CLI debug reshard start $LO $HI 0 1 2>&1|tr -d '\r')" = OK ] && ok "armed" || bad "arm rejected"
# wait for the cold scan (~NKEYS/8 log entries > 64K => crosses the wrap threshold)
sd=""
for i in $(seq 1 600); do
  sd=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'scan_done=[0-9]*'|cut -d= -f2)
  [ "$sd" = 1 ] && break; sleep 0.5
done
[ "$sd" = 1 ] && ok "cold scan finished (no ring wedge)" || bad "scan wedged (false-full at wrap?)"
st=$(timeout 5 $CLI debug reshard status 2>/dev/null|tr -d '\r')
issued=$(echo "$st"|grep -o 'issued=[0-9]*'|cut -d= -f2)
echo "  pre-cutover: $st"
[ -n "$issued" ] && [ "$issued" -gt 65536 ] && ok "log crossed 64K ring boundary (issued=$issued)" || bad "issued=$issued did not cross 64K — test not exercising wrap"
timeout 5 $CLI debug reshard cutover >/dev/null 2>&1
for i in $(seq 1 200); do
  ac=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'active=[0-9]*'|cut -d= -f2)
  [ "$ac" = 0 ] && break; sleep 0.3
done
[ "$ac" = 0 ] && ok "migration completed in $((SECONDS-t0))s" || bad "migration never completed"
# Byte-exactness across the flip. This REPLACES a `converged=1` poll that could not fail: with more
# than one worker per node every worker ALIASES one physical db, so the old src-vs-dst comparison
# was the same table compared with itself and reported converged=1 for any data, on any build.
VPOST=$(timeout 120 $CLI debug reshard verify $LO $HI 2>/dev/null | tr -d '\r' | grep '^total')
[ -n "$VPOST" ] && [ "$VPOST" = "$VPRE" ] && ok "range byte-exact across the flip ($VPOST)" \
    || bad "range checksum changed across the flip: '$VPRE' -> '$VPOST'"
db1=$(timeout 5 $CLI dbsize|tr -d '\r')
[ "$db1" = "$db0" ] && ok "dbsize parity ($db1)" || bad "dbsize $db0 -> $db1 (lost/duplicated keys)"
# sample byte-exactness across the keyspace (hits migrated + unmigrated keys)
sbad=0
for i in $(seq 7 9973 $NKEYS); do
  v=$(timeout 3 $CLI get "rw:$i" 2>/dev/null|tr -d '\r')
  [ "$v" = "v$i" ] || { sbad=$((sbad+1)); echo "  MISMATCH rw:$i='$v'"; }
done
[ "$sbad" = 0 ] && ok "sampled values byte-exact" || bad "$sbad sampled mismatches"
crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' "$D/s.log")
[ "$crash" = 0 ] && ok "zero crash lines" || bad "crash lines=$crash"
timeout 5 $CLI shutdown nosave >/dev/null 2>&1
echo "=== RINGWRAP DONE: fails=$fail ==="
[ "$fail" = 0 ] && { echo "VERDICT: PASS"; exit 0; } || { echo "VERDICT: FAIL"; exit 1; }
