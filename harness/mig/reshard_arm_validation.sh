#!/usr/bin/env bash
# Regression gate for reshard arm-time validation (ee451 review, P0 data-loss class).
# Matrix: invalid-src / non-adjacent / misaligned / total-range arms must be REJECTED with the
# canary staying reachable; a boundary-aligned suffix arm must be ACCEPTED, complete, keep the
# canary readable through the flip, and leave ex_bucket_end consistent (proved by a second valid
# arm of the SAME range from the NEW owner succeeding).
# Hang-proof: timeout on every client, server killed by PID, no bare wait. Env: PORT.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$REPO/src/redis-cli -p ${PORT:=6503}"
D=$(mktemp -d)
cleanup(){ [ -n "${SPID:-}" ] && kill -9 "$SPID" 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT
pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; sleep 0.5
"$REPO/src/redis-server" --tomokv-io-threads 2 --tomokv-ex-threads 4 --enable-debug-command yes \
  --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.3; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { echo "BOOT FAIL"; exit 1; }
fail=0
ok(){ echo "  OK   $1"; }
bad(){ echo "  FAIL $1"; fail=$((fail+1)); }

# Derive the bucket space size + w0's range end from routing probes (works at 4096 or 16384).
# w0 owns [0, N/4) at W=4; find a w0-owned key and the max bucket to size the space.
maxb=0; KEY=""; BKT=-1
for i in $(seq 1 300); do
  info=$(timeout 3 $CLI debug reshard find "av:$i" 2>/dev/null | tr -d '\r')
  b=$(echo "$info" | grep -o 'bucket=[0-9]*' | cut -d= -f2); w=$(echo "$info" | grep -o 'routed_ex=[0-9]*' | cut -d= -f2)
  [ -n "$b" ] && [ "$b" -gt "$maxb" ] && maxb=$b
  if [ -z "$KEY" ] && [ "$w" = "0" ]; then KEY="av:$i"; BKT=$b; fi
done
NB=4096; [ "$maxb" -ge 4096 ] && NB=16384
W0_HI=$((NB/4)); HALF=$((W0_HI/2))
[ -n "$KEY" ] || { echo "no w0 key"; exit 1; }
timeout 3 $CLI set "$KEY" ARMV_CANARY >/dev/null
echo "space=$NB w0=[0,$W0_HI) canary=$KEY bucket=$BKT"

arm(){ timeout 5 $CLI debug reshard start $1 $2 $3 $4 2>&1 | tr -d '\r'; }
expect_reject(){ local r; r=$(arm $1 $2 $3 $4)
  case "$r" in ERR*) ok "$5 rejected";; *) bad "$5 ACCEPTED ($r)";; esac
  [ "$(timeout 3 $CLI get "$KEY"|tr -d '\r')" = ARMV_CANARY ] && ok "$5 canary intact" || bad "$5 canary lost"; }

echo "=== invalid arms must be rejected ==="
expect_reject 0 $HALF 2 3            "invalid-src (range owned by w0, src=2)"
expect_reject $HALF $W0_HI 0 2       "non-adjacent (dst=2 from src=0)"
expect_reject 0 $HALF 0 1            "misaligned prefix-to-right (breaks contiguity)"
expect_reject 0 $W0_HI 0 1           "total-range (would empty src)"
expect_reject $((HALF+1)) $W0_HI 1 0 "range not owned by claimed src=1"

echo "=== valid suffix arm must work end-to-end ==="
# Move w0's suffix [HALF, W0_HI) to w1; if the canary bucket is in the suffix it must survive the flip.
r=$(arm $HALF $W0_HI 0 1)
[ "$r" = OK ] && ok "valid suffix arm accepted" || bad "valid suffix arm rejected ($r)"
for i in $(seq 1 100); do
  sd=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'scan_done=[0-9]*'|cut -d= -f2)
  [ "$sd" = 1 ] && break; sleep 0.2
done
timeout 5 $CLI debug reshard cutover >/dev/null 2>&1
for i in $(seq 1 100); do
  ac=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'active=[0-9]*'|cut -d= -f2)
  [ "$ac" = 0 ] && break; sleep 0.2
done
[ "$ac" = 0 ] && ok "migration completed" || bad "migration did not complete"
[ "$(timeout 3 $CLI get "$KEY"|tr -d '\r')" = ARMV_CANARY ] && ok "canary readable post-flip" || bad "canary lost post-flip"
# ex_bucket_end consistency: w1 now owns [HALF, 2*W0_HI); a valid suffix arm FROM w1 of the moved
# piece back... w1's range is [HALF, W0_HI*2), its suffix boundary with w2 is W0_HI*2. Instead prove
# consistency by arming w1's PREFIX [HALF, W0_HI) back to w0 (dst=src-1, lo==s_lo) — must be accepted.
r=$(arm $HALF $W0_HI 1 0)
[ "$r" = OK ] && ok "post-flip end-vector consistent (return arm accepted)" || bad "return arm rejected => ex_bucket_end drifted ($r)"
for i in $(seq 1 100); do
  sd=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'scan_done=[0-9]*'|cut -d= -f2)
  [ "$sd" = 1 ] && break; sleep 0.2
done
timeout 5 $CLI debug reshard cutover >/dev/null 2>&1
for i in $(seq 1 100); do
  ac=$(timeout 3 $CLI debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'active=[0-9]*'|cut -d= -f2)
  [ "$ac" = 0 ] && break; sleep 0.2
done
[ "$(timeout 3 $CLI get "$KEY"|tr -d '\r')" = ARMV_CANARY ] && ok "canary readable after return migration" || bad "canary lost on return"
crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' "$D/s.log")
[ "$crash" = 0 ] && ok "zero crash lines" || bad "crash lines=$crash"
timeout 5 $CLI shutdown nosave >/dev/null 2>&1
echo "=== ARM_VALIDATION DONE: fails=$fail ==="
[ "$fail" = 0 ] && { echo "VERDICT: PASS"; exit 0; } || { echo "VERDICT: FAIL"; exit 1; }
