#!/usr/bin/env bash
# Gold-standard: FRESH server per command (no routing carryover). Each: seed, arm [0,512) 0->1,
# wait scan_done, run the same-shard in-range op post-scan/pre-cutover, CUTOVER, verify survival.
# Also a matched no-migration control per command (must also pass). With the migration-safety fix
# every migration case survives; the control proves the command works normally.
set -u
R=/shared/Projects/THredis-v13-2s; C="/shared/Projects/redis/src/redis-cli -p 6405"
D=/shared/Projects/.claude/jobs/fd085c8e/tmp/mb3
L=/shared/Projects/overnight_sweep/selfimprove/xshard_migsafe.log; : >"$L"
say(){ echo "$*" | tee -a "$L"; }
fail=0
boot(){ pkill -9 -f 'redis-server.*6405' 2>/dev/null; sleep 1; rm -rf $D; mkdir -p $D
  taskset -c 0-7 $R/src/redis-server --tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-reshard-min-ops 0 \
    --enable-debug-command yes --save '' --appendonly no --protected-mode no --dir $D --port 6405 >$D/s.log 2>&1 &
  for i in $(seq 1 60); do timeout 2 $C ping >/dev/null 2>&1 && break; sleep 0.4; done; }
sh(){ $C debug reshard find "$1" 2>/dev/null|tr -d '\r'|grep -o 'routed_ex=[0-9]*'|cut -d= -f2; }
bk(){ $C debug reshard find "$1" 2>/dev/null|tr -d '\r'|grep -o 'bucket=[0-9]*'|cut -d= -f2; }
inpair(){ local a="" b="" k; for i in $(seq 1 900); do k="p:$i"; local x=$(bk "$k"); if [ -n "$x" ] && [ "$x" -lt 512 ]; then if [ -z "$a" ]; then a="$k"; else b="$k"; break; fi; fi; done; echo "$a $b"; }

one(){ local label="$1" migrate="$2" setup="$3" op="$4" verify="$5" want="$6"
  boot
  for i in $(seq 1 5000); do echo "set fill:$i v$i"; done | $C --pipe >/dev/null 2>&1
  read A B < <(inpair)
  local s2=${setup//@A/$A}; eval "${s2//@B/$B}" ; eval_op=${op//@A/$A}; eval_op=${eval_op//@B/$B}
  eval_ver=${verify//@A/$A}; eval_ver=${eval_ver//@B/$B}
  local rep
  if [ "$migrate" = 1 ]; then
    local S=$(sh "$A"); local T=$(( (S+1)%4 ))
    $C debug reshard start 0 512 $S $T >/dev/null 2>&1
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
pkill -9 -f 'redis-server.*6405' 2>/dev/null
say "=== MIGSAFE DONE: fails=$fail ==="
[ "$fail" = 0 ] && say "VERDICT: PASS" || say "VERDICT: FAIL"
