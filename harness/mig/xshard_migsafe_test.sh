#!/usr/bin/env bash
# Gold-standard: FRESH server per command (no routing carryover). Each: seed, arm w0's suffix
# half (a VALID boundary-aligned arm — the old [0,512) prefix-to-right arm is now rejected by
# reshardRangeValid), wait scan_done, run the same-shard in-range op post-scan/pre-cutover,
# CUTOVER, verify survival. Also a matched no-migration control per command (must also pass).
# Portable: repo-relative paths, PORT env, mktemp. Hang-proof: timeouts, kill by PID/pattern.
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
# migration range = w0's suffix half [NB/8, NB/4) — derive NB from routing probes (4096 or 16384)
NB=""
derive_nb(){ [ -n "$NB" ] && return; local maxb=0 b
  for i in $(seq 1 60); do b=$(bk "nbp:$i"); [ -n "$b" ] && [ "$b" -gt "$maxb" ] && maxb=$b; done
  NB=4096; [ "$maxb" -ge 4096 ] && NB=16384; MLO=$((NB/8)); MHI=$((NB/4)); }
inpair(){ local a="" b="" k; for i in $(seq 1 2000); do k="p:$i"; local x=$(bk "$k"); if [ -n "$x" ] && [ "$x" -ge "$MLO" ] && [ "$x" -lt "$MHI" ]; then if [ -z "$a" ]; then a="$k"; else b="$k"; break; fi; fi; done; echo "$a $b"; }

one(){ local label="$1" migrate="$2" setup="$3" op="$4" verify="$5" want="$6"
  boot
  derive_nb
  for i in $(seq 1 5000); do echo "set fill:$i v$i"; done | timeout -s KILL 30 $C --pipe >/dev/null 2>&1
  read A B < <(inpair)
  local s2=${setup//@A/$A}; eval "${s2//@B/$B}" ; eval_op=${op//@A/$A}; eval_op=${eval_op//@B/$B}
  eval_ver=${verify//@A/$A}; eval_ver=${eval_ver//@B/$B}
  local rep
  if [ "$migrate" = 1 ]; then
    local S=$(sh "$A"); local T=$(( (S+1)%4 ))
    $C debug reshard start $MLO $MHI $S $T >/dev/null 2>&1
    local sd=0; for i in $(seq 1 400); do sd=$($C debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'scan_done=[0-9]*'|cut -d= -f2); [ "$sd" = 1 ] && break; sleep 0.02; done
    rep=$(eval "$eval_op")
    $C debug reshard cutover >/dev/null 2>&1
    for i in $(seq 1 400); do local a=$($C debug reshard status 2>/dev/null|tr -d '\r'|grep -o 'active=[0-9]*'|cut -d= -f2); [ "$a" = 0 ] && break; sleep 0.02; done
  else
    rep=$(eval "$eval_op")
  fi
  local got=$(eval "$eval_ver")
  local crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' $D/s.log)
  if [ "$got" = "$want" ] && [ "$crash" = 0 ]; then say "  OK   $label (reply=$rep)"
  else say "  FAIL $label reply=$rep got='$got' want='$want' crash=$crash"; fail=$((fail+1)); fi
}

say "=== migration-safety: same-shard conditional moves to in-range keys survive cutover ==="
for m in "mig 1" "ctl 0"; do set -- $m; tag=$1; mg=$2
say "--- $tag (migrate=$mg) ---"
one "$tag RENAMENX"    $mg '$C set @A av >/dev/null; $C del @B >/dev/null'                       '$C renamenx @A @B|tr -d "\r"'      '$C get @B|tr -d "\r"'            av
one "$tag RENAMENX-dstpresent" $mg '$C set @A x >/dev/null; $C set @B y >/dev/null'              '$C renamenx @A @B|tr -d "\r"'      '$C get @B|tr -d "\r"'            y
one "$tag COPY"        $mg '$C set @A cv >/dev/null; $C del @B >/dev/null'                        '$C copy @A @B|tr -d "\r"'          '$C get @B|tr -d "\r"'            cv
one "$tag COPY-srckept" $mg '$C set @A cv2 >/dev/null; $C del @B >/dev/null'                      '$C copy @A @B|tr -d "\r"'          '$C get @A|tr -d "\r"'            cv2
one "$tag RENAME"      $mg '$C set @A rv >/dev/null; $C del @B >/dev/null'                        '$C rename @A @B|tr -d "\r"'        '$C get @B|tr -d "\r"'            rv
one "$tag SMOVE-dst"   $mg '$C del @A @B >/dev/null; $C sadd @A m1 m2 >/dev/null; $C sadd @B z >/dev/null' '$C smove @A @B m1|tr -d "\r"' '$C sismember @B m1|tr -d "\r"' 1
one "$tag SMOVE-src"   $mg '$C del @A @B >/dev/null; $C sadd @A m1 m2 >/dev/null'                  '$C smove @A @B m1|tr -d "\r"'      '$C sismember @A m1|tr -d "\r"'  0
one "$tag LMOVE"       $mg '$C del @A @B >/dev/null; $C rpush @A e1 e2 e3 >/dev/null'              '$C lmove @A @B left right|tr -d "\r"' '$C lrange @B 0 -1|tr -d "\r"' e1
one "$tag RPOPLPUSH"   $mg '$C del @A @B >/dev/null; $C rpush @A e1 e2 e3 >/dev/null'              '$C rpoplpush @A @B|tr -d "\r"'     '$C lrange @B 0 -1|tr -d "\r"'   e3
one "$tag RENAME-samekey" $mg '$C set @A skv >/dev/null'                                          '$C rename @A @A|tr -d "\r"'        '$C get @A|tr -d "\r"'           skv
one "$tag SMOVE-samekey" $mg '$C del @A >/dev/null; $C sadd @A m1 m2 >/dev/null'                    '$C smove @A @A m1|tr -d "\r"'      '$C sismember @A m1|tr -d "\r"'  1
one "$tag COPY-samekey"  $mg '$C set @A ckv >/dev/null'                                             '$C copy @A @A 2>&1|tr -d "\r"'     '$C get @A|tr -d "\r"'           ckv
done
pkill -9 -f "redis-server.*:$PORT" 2>/dev/null
say "=== MIGSAFE DONE: fails=$fail ==="
[ "$fail" = 0 ] && say "VERDICT: PASS" || say "VERDICT: FAIL"
