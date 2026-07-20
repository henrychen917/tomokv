#!/usr/bin/env bash
# xshard-localfast differential: for SAME-WORKER key groups, every read-only multi-key op must
# return IDENTICAL results with tomokv-xshard-localfast on vs off (off = legacy gather), incl.
# WRONGTYPE and missing-key semantics. Then bench the co-located pair on vs off. Port 6512.
set -u
R=/shared/Projects/THredis-v13-2s; C="$R/src/redis-cli -p 6512"
D=$(mktemp -d); trap 'kill -9 ${SPID:-0} 2>/dev/null; rm -rf "$D"' EXIT
pkill -9 -f 'redis-server.*6512' 2>/dev/null; sleep 0.5
taskset -c 0-7 "$R/src/redis-server" --tomokv-io-threads 4 --tomokv-ex-threads 4 --enable-debug-command yes \
  --save '' --appendonly no --protected-mode no --dir "$D" --port 6512 >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $C ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.3; done
shard_of(){ timeout 3 $C debug reshard find "$1" 2>/dev/null | tr -d '\r' | grep -o 'routed_ex=[0-9]*' | cut -d= -f2; }
# find FOUR keys on the SAME worker
KS=(); w0=""
for i in $(seq 1 800); do k="lf:$i"; w=$(shard_of "$k"); [ -z "$w" ] && continue
  if [ -z "$w0" ]; then w0=$w; KS+=("$k"); elif [ "$w" = "$w0" ]; then KS+=("$k"); fi
  [ ${#KS[@]} -ge 4 ] && break
done
A=${KS[0]}; B=${KS[1]}; Z1=${KS[2]}; Z2=${KS[3]}
echo "same-worker keys on w$w0: $A $B $Z1 $Z2"
timeout 5 $C sadd "$A" a b c d e >/dev/null; timeout 5 $C sadd "$B" c d e f g >/dev/null
timeout 5 $C zadd "$Z1" 1 a 2 b 3 c >/dev/null; timeout 5 $C zadd "$Z2" 10 b 20 c 30 d >/dev/null
timeout 5 $C set lfstr:key strval >/dev/null   # (may be any worker; used only same-worker if it lands there)
fail=0
diffit(){ local name=$1; shift
  timeout 5 $C config set tomokv-xshard-localfast yes >/dev/null
  local on=$(timeout 8 $C "$@" 2>&1 | tr -d '\r' | sort | tr '\n' ',')
  timeout 5 $C config set tomokv-xshard-localfast no >/dev/null
  local off=$(timeout 8 $C "$@" 2>&1 | tr -d '\r' | sort | tr '\n' ',')
  timeout 5 $C config set tomokv-xshard-localfast yes >/dev/null
  if [ "$on" = "$off" ]; then echo "  OK   $name ($on)"
  else echo "  FAIL $name on='$on' off='$off'"; fail=$((fail+1)); fi; }
echo "=== differential (on == off), same-worker groups ==="
diffit "SINTER"          sinter "$A" "$B"
diffit "SUNION"          sunion "$A" "$B"
diffit "SDIFF"           sdiff "$A" "$B"
diffit "SINTERCARD"      sintercard 2 "$A" "$B"
diffit "SINTERCARD LIM"  sintercard 2 "$A" "$B" limit 2
diffit "ZINTER"          zinter 2 "$Z1" "$Z2" withscores
diffit "ZINTER WEIGHTS"  zinter 2 "$Z1" "$Z2" weights 2 3 withscores
diffit "ZUNION"          zunion 2 "$Z1" "$Z2" withscores
diffit "ZDIFF"           zdiff 2 "$Z1" "$Z2" withscores
diffit "ZINTERCARD"      zintercard 2 "$Z1" "$Z2"
diffit "MGET"            mget "$A" "$B" nosuch:k
diffit "EXISTS"          exists "$A" "$B" "$A" nosuch:k
diffit "SINTER missing"  sinter "$A" "nosuch:$A"
diffit "SINTER wrongtype" sinter "$A" "$Z1"
diffit "ZINTER wrongtype" zinter 2 "$Z1" "$A"
# cross-worker sanity: localfast must NOT engage (find a cross pair; results must still match off-path)
CX=""; for i in $(seq 801 1600); do k="lf:$i"; w=$(shard_of "$k"); [ -n "$w" ] && [ "$w" != "$w0" ] && { CX="$k"; break; }; done
timeout 5 $C sadd "$CX" c d x >/dev/null
diffit "SINTER cross-pair" sinter "$A" "$CX"
echo "=== bench: co-located SINTER 10k x 10k (1k overlap), 20 iters, on vs off ==="
timeout 5 $C del "$A" "$B" >/dev/null
seq 1 10000 | awk -v k="$A" '{print "sadd "k" m"$1}' | timeout -s KILL 60 $C --pipe >/dev/null 2>&1
seq 9000 19000 | awk -v k="$B" '{print "sadd "k" m"$1}' | timeout -s KILL 60 $C --pipe >/dev/null 2>&1
t20(){ local s e; s=$(date +%s%N); for i in $(seq 1 20); do timeout 20 $C sinter "$A" "$B" >/dev/null 2>&1; done; e=$(date +%s%N); echo $(( (e-s)/1000000 )); }
timeout 5 $C config set tomokv-xshard-localfast yes >/dev/null; on_ms=$(t20)
timeout 5 $C config set tomokv-xshard-localfast no  >/dev/null; off_ms=$(t20)
timeout 5 $C config set tomokv-xshard-localfast yes >/dev/null; on2_ms=$(t20)
echo "  localfast ON: ${on_ms}ms/20, ${on2_ms}ms/20   OFF(gather): ${off_ms}ms/20"
# MGET co-located k=8 bench
for i in 1 2 3 4 5 6 7 8; do timeout 5 $C set "mg$i:$A" v$i >/dev/null; done   # not guaranteed same worker; use A B repeated instead
tm(){ local s e; s=$(date +%s%N); for i in $(seq 1 200); do timeout 20 $C mget "$A" "$B" "$A" "$B" "$A" "$B" "$A" "$B" >/dev/null 2>&1; done; e=$(date +%s%N); echo $(( (e-s)/1000000 )); }
timeout 5 $C config set tomokv-xshard-localfast yes >/dev/null; mon=$(tm)
timeout 5 $C config set tomokv-xshard-localfast no  >/dev/null; moff=$(tm)
echo "  MGET k=8 same-worker: ON=${mon}ms/200 OFF=${moff}ms/200"
crash=$(grep -icE 'REDIS BUG|signal|Assertion|Segmentation' "$D/s.log")
echo "=== LOCALFAST DONE fails=$fail crash=$crash ==="
[ "$fail" = 0 ] && [ "$crash" = 0 ] && echo "VERDICT: PASS" || echo "VERDICT: FAIL"
