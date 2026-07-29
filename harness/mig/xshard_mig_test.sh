#!/usr/bin/env bash
# Migration-interaction test for the step 4-9 cross-shard commands. Arms a manual migration
# (DEBUG RESHARD START) and, while it is ACTIVE (pre-cutover: mig holds + effect capture live),
# fires every ported write command with keys INSIDE the migrating bucket range; then cutover and
# verify each effect is present + correct AFTER the flip (proves capture/replay + hold-rerouting
# carried the HOP2 writes). Also STATUS checksums, dbsize, alive. ASAN=1 supported.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI="$REPO/src/redis-cli -p ${PORT:=6405}"
D=$(mktemp -d); mkdir -p $D/srv
trap 'pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; rm -rf "$D"' EXIT
say(){ echo "$*"; }
ASAN=${ASAN:-0}
pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; sleep 1
if [ "$ASAN" = 1 ]; then
  ( cd $REPO && make distclean >/dev/null 2>&1 && make -j SANITIZER=address MALLOC=libc USE_URING=yes ) >$D/b.log 2>&1
  nm $REPO/src/redis-server 2>/dev/null|grep -qi asan || { say "ASAN BUILD FAIL"; exit 1; }
  export ASAN_OPTIONS="detect_leaks=1:halt_on_error=0:log_path=$D/asan:abort_on_error=0"
fi
$REPO/src/redis-server --tomokv-thread-io 4 --tomokv-thread-ex 4 \
  --tomokv-reshard-min-ops 0 --enable-debug-command yes \
  --save '' --appendonly no --protected-mode no --dir $D/srv --port $PORT >$D/s.log 2>&1 &
PID=$!
for i in $(seq 1 150); do timeout 2 $CLI ping >/dev/null 2>&1 && break; sleep 0.4; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { say "BOOT FAIL"; tail $D/s.log; exit 1; }
say "booted (ASAN=$ASAN)"
fail=0
ck(){ local desc="$1" got="$2" want="$3"; case "$got" in $want) say "  OK   $desc";; *) say "  FAIL $desc -> '$got' (want $want)"; fail=$((fail+1));; esac; }
finfo(){ timeout 5 $CLI debug reshard find "$1" 2>/dev/null | tr -d '\r'; }
bucket_of(){ finfo "$1" | grep -o 'bucket=[0-9]*' | cut -d= -f2; }
shard_of(){ finfo "$1" | grep -o 'routed_ex=[0-9]*' | cut -d= -f2; }

# Migration range = w0's suffix half [NB/8, NB/4): a VALID boundary-aligned arm — the old
# [0,512) prefix-to-right arm is now rejected by reshardRangeValid. NB derived from probes.
maxb=0; for i in $(seq 1 60); do
  b=$(bucket_of "nbp:$i"); [ -n "$b" ] && [ "$b" -gt "$maxb" ] && maxb=$b; done
NB=4096; [ "$maxb" -ge 4096 ] && NB=16384; MLO=$((NB/8)); MHI=$((NB/4))
# Collect key sets: IN = bucket in [MLO,MHI) (so shard src = owner of those buckets now);
# OUT = bucket outside. Also note src worker from an in-range key.
say "=== classify candidate keys (range [$MLO,$MHI)) ==="
IN=(); OUT=(); SRC=""
for i in $(seq 1 2000); do
  k="mg:$i"; b=$(bucket_of "$k")
  if [ -n "$b" ] && [ "$b" -ge "$MLO" ] && [ "$b" -lt "$MHI" ]; then IN+=("$k"); [ -z "$SRC" ] && SRC=$(shard_of "$k")
  else OUT+=("$k"); fi
  [ ${#IN[@]} -ge 24 ] && [ ${#OUT[@]} -ge 12 ] && break
done
say "in-range keys=${#IN[@]} out=${#OUT[@]} src_worker=$SRC"
[ ${#IN[@]} -ge 16 ] && [ -n "$SRC" ] || { say "CLASSIFY FAIL"; exit 1; }
DST=$(( (SRC + 1) % 4 ))
# bulk ballast so the range isn't empty (5k keys, some land in-range)
for i in $(seq 1 5000); do echo "set bal:$i v$i"; done | $CLI --pipe >/dev/null 2>&1

# Pre-stage source values for the mid-migration barrage (all IN-range)
K=("${IN[@]}")
$CLI set "${K[0]}" ren_src_val >/dev/null                      # RENAME src (in-range) -> out key
$CLI set "${K[1]}" rnx_src_val >/dev/null                      # RENAMENX src -> in-range dst K[2] (absent)
$CLI del "${K[2]}" >/dev/null
$CLI set "${K[3]}" copy_src_val >/dev/null                     # COPY src -> in-range dst K[4]
$CLI del "${K[4]}" >/dev/null
$CLI sadd "${K[5]}" mm1 mm2 >/dev/null; $CLI sadd "${K[6]}" zz >/dev/null   # SMOVE K5 -> K6
$CLI sadd "${K[7]}" a b c >/dev/null; $CLI sadd "${K[8]}" b c d >/dev/null  # SINTERSTORE dst K[9]
$CLI del "${K[9]}" >/dev/null
$CLI zadd "${K[10]}" 1 m1 2 m2 >/dev/null; $CLI zadd "${K[11]}" 3 m2 4 m3 >/dev/null  # ZUNIONSTORE dst K[12]
$CLI del "${K[12]}" >/dev/null
$CLI set "${K[13]}" abc >/dev/null                             # BITOP NOT dst K[14]
$CLI del "${K[14]}" >/dev/null
$CLI pfadd "${K[15]}" h1 h2 h3 >/dev/null                      # PFMERGE dst = K[15] itself + out-src
$CLI pfadd pf:outsrc o1 o2 >/dev/null
$CLI rpush "${IN[16]:-mg:x1}" l1 l2 l3 >/dev/null              # LMOVE src -> in-range dst
LM_SRC="${IN[16]:-mg:x1}"; LM_DST="${IN[17]:-mg:x2}"; $CLI del "$LM_DST" >/dev/null
MS_A="${IN[18]:-mg:x3}"; MS_B="${IN[19]:-mg:x4}"; $CLI del "$MS_A" "$MS_B" >/dev/null   # MSETNX
LP_A="${IN[20]:-mg:x5}"; $CLI del "$LP_A" >/dev/null; $CLI rpush "$LP_A" p1 p2 >/dev/null  # LMPOP winner in-range
db0=$(timeout 5 $CLI dbsize|tr -d '\r')

say "=== ARM migration [$MLO,$MHI) w$SRC -> w$DST, then mid-flight barrage ==="
ck "arm" "$(timeout 5 $CLI debug reshard start $MLO $MHI $SRC $DST 2>&1|tr -d '\r')" 'OK'
ck "active" "$(timeout 5 $CLI debug reshard status 2>/dev/null | tr -d '\r' | grep -o 'active=[0-9]*')" 'active=1'
# barrage WHILE ACTIVE (capture/hold window). Every write goes through the 2-hop/coalesced paths.
ck "mid RENAME"      "$($CLI rename "${K[0]}" migren:out 2>&1|tr -d '\r')" 'OK'
ck "mid RENAMENX"    "$($CLI renamenx "${K[1]}" "${K[2]}"|tr -d '\r')" '1'
ck "mid COPY"        "$($CLI copy "${K[3]}" "${K[4]}"|tr -d '\r')" '1'
ck "mid SMOVE"       "$($CLI smove "${K[5]}" "${K[6]}" mm1|tr -d '\r')" '1'
ck "mid SINTERSTORE" "$($CLI sinterstore "${K[9]}" "${K[7]}" "${K[8]}"|tr -d '\r')" '2'
ck "mid ZUNIONSTORE" "$($CLI zunionstore "${K[12]}" 2 "${K[10]}" "${K[11]}"|tr -d '\r')" '3'
ck "mid BITOP NOT"   "$($CLI bitop not "${K[14]}" "${K[13]}"|tr -d '\r')" '3'
ck "mid PFMERGE"     "$($CLI pfmerge "${K[15]}" pf:outsrc|tr -d '\r')" 'OK'
ck "mid LMOVE"       "$($CLI lmove "$LM_SRC" "$LM_DST" left right|tr -d '\r')" 'l1'
ck "mid MSETNX"      "$($CLI msetnx "$MS_A" ms1 "$MS_B" ms2|tr -d '\r')" '1'
ck "mid LMPOP"       "$($CLI lmpop 2 mig:miss "$LP_A" left | tr -d '\r' | tr '\n' ',')" "$LP_A,p1,"
ck "mid MSET"        "$($CLI mset "${IN[21]:-mg:y1}" mv1 "${OUT[0]}" mv2|tr -d '\r')" 'OK'
ck "mid DEL"         "$($CLI del "${IN[22]:-mg:y2}" "${OUT[1]}" nosuch:k|tr -d '\r')" '[0-9]'
say "=== CUTOVER ==="
for i in $(seq 1 100); do
  sd=$(timeout 5 $CLI debug reshard status 2>/dev/null | tr -d '\r' | grep -o 'scan_done=[0-9]*' | cut -d= -f2)
  [ "$sd" = 1 ] && break; sleep 0.2
done
ck "scan_done" "$sd" '1'
say "  pre-cutover STATUS: $(timeout 5 $CLI debug reshard status 2>/dev/null | tr -d '\r' | tr '\n' ' ')"
# NOTE (2026-07-28): the `converged=1` gate that used to sit here has been REMOVED, not relocated.
# It polled STATUS for "src range-checksum == dst range-checksum", and STATUS computed both by
# walking a shard each. Two problems: (a) with >1 worker per node every worker ALIASES one physical
# db, so the two checksums were the same table compared with itself — converged=1 for any data, on
# any build, i.e. a check that could not fail; (b) the walk is O(keyspace) and ran on the calling IO
# thread, which for ~1/io_threads of connections is MAIN — the only thread that advances the cutover
# coordinator — so polling it stalled the very cutover it was watching. The content check now lives
# in `DEBUG RESHARD VERIFY`, which is refused while a migration is active. This test cannot use a
# before/after equality check because it deliberately WRITES to the range mid-flight, so it asserts
# the weaker post-flip property instead; the real content verification here is the per-command
# POST-FLIP effect block below.
ck "cutover" "$(timeout 5 $CLI debug reshard cutover 2>&1|tr -d '\r')" 'OK'
for i in $(seq 1 100); do
  ph=$(timeout 5 $CLI debug reshard status 2>/dev/null | tr -d '\r' | grep -o 'active=[0-9]*' | cut -d= -f2)
  [ "$ph" = 0 ] && break; sleep 0.2
done
st=$(timeout 5 $CLI debug reshard status 2>/dev/null | tr -d '\r' | tr '\n' ' ')
say "  final STATUS: $st"
ck "migration done" "$ph" '0'
# The migrated range must still hold data on exactly one physical db once the flip is done.
vpost=$(timeout 120 $CLI debug reshard verify $MLO $MHI 2>/dev/null | tr -d '\r' | grep '^total')
say "  post-migration VERIFY: $vpost"
ck "post-flip range non-empty" "$(echo "$vpost" | grep -o 'keys=[0-9]*')" 'keys=[1-9]*'

say "=== POST-FLIP effect verification (replay carried every write) ==="
ck "post RENAME moved"      "$($CLI get migren:out|tr -d '\r')" 'ren_src_val'
ck "post RENAME src gone"   "$($CLI exists "${K[0]}"|tr -d '\r')" '0'
ck "post RENAMENX val"      "$($CLI get "${K[2]}"|tr -d '\r')" 'rnx_src_val'
ck "post COPY val"          "$($CLI get "${K[4]}"|tr -d '\r')" 'copy_src_val'
ck "post COPY src intact"   "$($CLI get "${K[3]}"|tr -d '\r')" 'copy_src_val'
ck "post SMOVE dst"         "$($CLI sismember "${K[6]}" mm1|tr -d '\r')" '1'
ck "post SMOVE src"         "$($CLI sismember "${K[5]}" mm1|tr -d '\r')" '0'
ck "post SINTERSTORE"       "$($CLI smembers "${K[9]}"|tr -d '\r'|sort|tr '\n' ',')" 'b,c,'
ck "post ZUNIONSTORE"       "$($CLI zrange "${K[12]}" 0 -1 withscores|tr -d '\r'|tr '\n' ',')" 'm1,1,m3,4,m2,5,'
ck "post BITOP roundtrip"   "$($CLI bitop not "${K[14]}" "${K[14]}" >/dev/null; $CLI get "${K[14]}"|tr -d '\r')" 'abc'
ck "post PFMERGE count"     "$($CLI pfcount "${K[15]}"|tr -d '\r')" '5'
ck "post LMOVE dst"         "$($CLI lrange "$LM_DST" 0 -1|tr -d '\r'|tr '\n' ',')" 'l1,'
ck "post LMOVE src"         "$($CLI lrange "$LM_SRC" 0 -1|tr -d '\r'|tr '\n' ',')" 'l2,l3,'
ck "post MSETNX"            "$($CLI mget "$MS_A" "$MS_B"|tr -d '\r'|tr '\n' ',')" 'ms1,ms2,'
ck "post LMPOP state"       "$($CLI lrange "$LP_A" 0 -1|tr -d '\r'|tr '\n' ',')" 'p2,'
ck "post MSET in-range"     "$($CLI get "${IN[21]:-mg:y1}"|tr -d '\r')" 'mv1'
# routing sanity: an in-range key now routes to DST
ck "post routing flipped"   "$(shard_of "${K[2]}")" "$DST"
db1=$(timeout 5 $CLI dbsize|tr -d '\r')
say "  dbsize $db0 -> $db1 (barrage adds/moves keys; sanity only)"
ck "alive" "$(timeout 5 $CLI ping|tr -d '\r')" 'PONG'
crash=$(grep -icE 'crash|=== REDIS BUG|signal [0-9]|Assertion|Segmentation' $D/s.log)
ck "zero crash lines" "$crash" '0'
if [ "$ASAN" = 1 ]; then
  sleep 1; fnd=$(cat $D/asan.* 2>/dev/null | grep -E "ERROR|SUMMARY" | head -10)
  say "=== ASAN ==="; [ -n "$fnd" ] && { say "FINDINGS:"; echo "$fnd"; fail=$((fail+1)); } || say "  (none)"
fi
timeout 8 $CLI shutdown nosave >/dev/null 2>&1; kill $PID 2>/dev/null; sleep 1; pkill -9 -f "redis-server.*:$PORT" 2>/dev/null
if [ "$ASAN" = 1 ]; then
  ( cd $REPO && make distclean >/dev/null 2>&1 && make -j USE_URING=yes ) >$D/rb.log 2>&1 && say "rebuilt non-ASAN"
fi
say "=== MIG TEST DONE: fails=$fail ==="
[ "$fail" = 0 ] && say "VERDICT: PASS" || say "VERDICT: FAIL"
