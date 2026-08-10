#!/usr/bin/env bash
# v11-F: validate cross-shard SINTER/SUNION/SDIFF against vanilla Redis.
# THredis on 7908 (cross-setop ON, 4 workers => keys spread across shards), vanilla on 7909.
set -u
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
VANILLA=/home/henry/Projects/redis/src/redis-server
THREDIS=/home/henry/Projects/THredis/src/redis-server
pkill -9 -x redis-server 2>/dev/null; sleep 1
$THREDIS --port 7908 --save '' --appendonly no --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/setop_t.log 2>&1 &
$VANILLA --port 7909 --save '' --appendonly no --protected-mode no >/tmp/setop_v.log 2>&1 &
for i in $(seq 1 40); do $CLI -p 7908 ping >/dev/null 2>&1 && $CLI -p 7909 ping >/dev/null 2>&1 && break; sleep 0.5; done
$CLI -p 7908 config set thredis-opt-cross-setop yes >/dev/null

# Sorted reply so set-order differences don't cause false mismatches.
run() { $CLI -p "$1" "${@:2}" 2>&1 | sort | tr '\n' ' '; }
PASS=0; FAIL=0
chk() { # chk "label" CMD ARGS...
  local label="$1"; shift
  local t v
  t=$(run 7908 "$@"); v=$(run 7909 "$@")
  if [ "$t" == "$v" ]; then PASS=$((PASS+1)); else
    FAIL=$((FAIL+1)); printf 'FAIL %-22s THB=[%s] REDIS=[%s]\n' "$label" "$t" "$v"; fi
}

# Seed identical data on both. Members chosen to span shards; keys span shards too.
seed() {
  for p in 7908 7909; do
    $CLI -p $p flushall >/dev/null
    $CLI -p $p sadd s1 a b c d e f g h >/dev/null
    $CLI -p $p sadd s2 c d e f i j     >/dev/null   # overlaps s1 on c d e f
    $CLI -p $p sadd s3 x y z           >/dev/null   # disjoint from s1
    $CLI -p $p sadd s4 a b c d e f g h >/dev/null   # == s1 (full overlap)
    $CLI -p $p set  str hello          >/dev/null   # wrong type
    for k in $(seq 1 500); do $CLI -p $p sadd big1 "m$k" >/dev/null; done
    for k in $(seq 250 750); do $CLI -p $p sadd big2 "m$k" >/dev/null; done
  done
}
seed

chk "inter-overlap"      SINTER s1 s2
chk "inter-disjoint"     SINTER s1 s3
chk "inter-full"         SINTER s1 s4
chk "inter-missing"      SINTER s1 nope
chk "inter-single"       SINTER s1
chk "inter-dupkey"       SINTER s1 s1
chk "inter-3way"         SINTER s1 s2 s4
chk "inter-big"          SINTER big1 big2
chk "union-overlap"      SUNION s1 s2
chk "union-disjoint"     SUNION s1 s3
chk "union-missing"      SUNION s1 nope
chk "union-single"       SUNION s1
chk "union-dupkey"       SUNION s1 s1
chk "union-3way"         SUNION s1 s2 s3
chk "union-big"          SUNION big1 big2
chk "diff-overlap"       SDIFF s1 s2
chk "diff-disjoint"      SDIFF s1 s3
chk "diff-full"          SDIFF s1 s4
chk "diff-missing-rhs"   SDIFF s1 nope
chk "diff-missing-lhs"   SDIFF nope s1
chk "diff-single"        SDIFF s1
chk "diff-dupkey"        SDIFF s1 s1
chk "diff-3way"          SDIFF s1 s2 s3
chk "diff-big"           SDIFF big1 big2
chk "inter-wrongtype"    SINTER s1 str
chk "union-wrongtype"    SUNION s1 str
chk "diff-wrongtype"     SDIFF s1 str
chk "inter-allmissing"   SINTER no1 no2
chk "union-allmissing"   SUNION no1 no2
chk "diff-allmissing"    SDIFF no1 no2

echo "----- PASS=$PASS FAIL=$FAIL -----"
$CLI -p 7908 shutdown nosave >/dev/null 2>&1; $CLI -p 7909 shutdown nosave >/dev/null 2>&1
pkill -9 -x redis-server 2>/dev/null
