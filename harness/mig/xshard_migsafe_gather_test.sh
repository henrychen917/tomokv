#!/usr/bin/env bash
# Verify the GATHER-route cross-shard WRITES survive migration (the paths I claimed capture
# correctly). Fresh server per case. Keys forced in-range; write runs post-scan/pre-cutover;
# verify effect present on destination after cutover. If any is LOST, that's a second bug.
set -u
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
C="$R/src/redis-cli -p ${PORT:=6405}"
D=$(mktemp -d)
trap 'pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; rm -rf "$D"' EXIT
say(){ echo "$*"; }
fail=0
boot(){ pkill -9 -f "redis-server.*:$PORT" 2>/dev/null; sleep 1; rm -rf "$D"; mkdir -p "$D"
  $R/src/redis-server --tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-reshard-min-ops 0 \
    --enable-debug-command yes --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
  for i in $(seq 1 60); do timeout 2 $C ping >/dev/null 2>&1 && break; sleep 0.4; done; }
sh(){ $C debug reshard find "$1" 2>/dev/null|tr -d '\r'|grep -o 'routed_ex=[0-9]*'|cut -d= -f2; }
bk(){ $C debug reshard find "$1" 2>/dev/null|tr -d '\r'|grep -o 'bucket=[0-9]*'|cut -d= -f2; }
# migration range = w0's suffix half [NB/8, NB/4) — valid boundary-aligned arm (the old [0,512)
# prefix-to-right arm is rejected by reshardRangeValid now). NB derived from routing probes.
NB=""
derive_nb(){ [ -n "$NB" ] && return; local maxb=0 b
  for i in $(seq 1 60); do b=$(bk "nbp:$i"); [ -n "$b" ] && [ "$b" -gt "$maxb" ] && maxb=$b; done
  NB=4096; [ "$maxb" -ge 4096 ] && NB=16384; MLO=$((NB/8)); MHI=$((NB/4)); }
# yield N distinct in-range keys
inkeys(){ local n=$1 out="" k; local i=1; while [ $i -le 5000 ] && [ $(echo $out|wc -w) -lt $n ]; do k="g:$i"; local x=$(bk "$k"); [ -n "$x" ] && [ "$x" -ge "$MLO" ] && [ "$x" -lt "$MHI" ] && out="$out $k"; i=$((i+1)); done; echo $out; }

one(){ local label="$1" mig="$2" setup="$3" op="$4" verify="$5" want="$6"
  boot
  derive_nb
  for i in $(seq 1 5000); do echo "set fill:$i v$i"; done | timeout -s KILL 30 $C --pipe >/dev/null 2>&1
  eval "$setup"
  local rep
  if [ "$mig" = 1 ]; then
    local S=$(sh "$KA") T; T=$(( (S+1)%4 ))
    $C debug reshard start $MLO $MHI $S $T >/dev/null 2>&1
    local sd=0; for i in $(seq 1 400); do sd=$($C debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'scan_done=[0-9]*'|cut -d= -f2); [ "$sd" = 1 ] && break; sleep 0.02; done
    rep=$(eval "$op")
    $C debug reshard cutover >/dev/null 2>&1
    for i in $(seq 1 400); do local a=$($C debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'active=[0-9]*'|cut -d= -f2); [ "$a" = 0 ] && break; sleep 0.02; done
  else
    rep=$(eval "$op")
  fi
  local got=$(eval "$verify")
  local crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' $D/s.log)
  if [ "$got" = "$want" ] && [ "$crash" = 0 ]; then say "  OK   $label (reply=$rep)"
  else say "  FAIL $label reply=$rep got='$got' want='$want' crash=$crash"; fail=$((fail+1)); fi
}

say "=== gather-route cross-shard writes survive migration cutover ==="
for m in "mig 1" "ctl 0"; do set -- $m; tag=$1; mg=$2
say "--- $tag ---"
# MSET (in-range keys)
one "$tag MSET" $mg 'read K1 K2 K3 <<< "$(inkeys 3)"; KA=$K1; $C del $K1 $K2 $K3 >/dev/null' \
  '$C mset $K1 mv1 $K2 mv2 $K3 mv3|tr -d "\r"' '$C mget $K1 $K2 $K3|tr -d "\r"|tr "\n" ","' 'mv1,mv2,mv3,'
# MSETNX (in-range)
one "$tag MSETNX" $mg 'read K1 K2 <<< "$(inkeys 2)"; KA=$K1; $C del $K1 $K2 >/dev/null' \
  '$C msetnx $K1 nx1 $K2 nx2|tr -d "\r"' '$C mget $K1 $K2|tr -d "\r"|tr "\n" ","' 'nx1,nx2,'
# DEL (in-range) — tombstone must replay
one "$tag DEL" $mg 'read K1 K2 <<< "$(inkeys 2)"; KA=$K1; $C set $K1 a >/dev/null; $C set $K2 b >/dev/null' \
  '$C del $K1 $K2|tr -d "\r"' '$C exists $K1 $K2|tr -d "\r"' '0'
# SINTERSTORE (dst + srcs in-range)
one "$tag SINTERSTORE" $mg 'read KD KX KY <<< "$(inkeys 3)"; KA=$KD; $C del $KD >/dev/null; $C sadd $KX a b c >/dev/null; $C sadd $KY b c d >/dev/null' \
  '$C sinterstore $KD $KX $KY|tr -d "\r"' '$C smembers $KD|tr -d "\r"|sort|tr "\n" ","' 'b,c,'
# ZUNIONSTORE
one "$tag ZUNIONSTORE" $mg 'read KD KX KY <<< "$(inkeys 3)"; KA=$KD; $C del $KD >/dev/null; $C zadd $KX 1 m1 2 m2 >/dev/null; $C zadd $KY 3 m2 4 m3 >/dev/null' \
  '$C zunionstore $KD 2 $KX $KY|tr -d "\r"' '$C zrange $KD 0 -1|tr -d "\r"|tr "\n" ","' 'm1,m3,m2,'
# BITOP
one "$tag BITOP" $mg 'read KD KX <<< "$(inkeys 2)"; KA=$KD; $C del $KD >/dev/null; $C set $KX abc >/dev/null' \
  '$C bitop not $KD $KX|tr -d "\r"' '$C strlen $KD|tr -d "\r"' '3'
# PFMERGE
one "$tag PFMERGE" $mg 'read KD KX <<< "$(inkeys 2)"; KA=$KD; $C del $KD >/dev/null; $C pfadd $KX e1 e2 e3 >/dev/null' \
  '$C pfmerge $KD $KX|tr -d "\r"' '$C pfcount $KD|tr -d "\r"' '3'
# MGET (read, in-range) — must return correct values mid-migration
one "$tag MGET-read" $mg 'read K1 K2 <<< "$(inkeys 2)"; KA=$K1; $C set $K1 r1 >/dev/null; $C set $K2 r2 >/dev/null' \
  '$C mget $K1 $K2|tr -d "\r"|tr "\n" ","' '$C mget $K1 $K2|tr -d "\r"|tr "\n" ","' 'r1,r2,'
done
pkill -9 -f "redis-server.*:$PORT" 2>/dev/null
say "=== MIGSAFE-GATHER DONE: fails=$fail ==="
[ "$fail" = 0 ] && say "VERDICT: PASS" || say "VERDICT: FAIL"
