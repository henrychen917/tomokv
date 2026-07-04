#!/usr/bin/env bash
# ============================================================================
# ALLOCATOR A/B — run on an IDLE box only (another session was benching when
# this was authored, so it was prepared, validated for syntax, and NOT run).
#
# Static facts already established (no bench needed):
#  - Every THredis binary here (incl. the April v4 paper binary) and the redis/
#    keydb baselines are built MALLOC=jemalloc-5.3.0 (see redis-server --version:
#    "malloc=jemalloc-5.3.0"). jemalloc is compiled in via je_-prefixed symbols,
#    so LD_PRELOADing another allocator does NOT swap it. Therefore the allocator
#    CANNOT explain the v4 paper-vs-now gap (same binary, same allocator).
#  - Dragonfly bundles mimalloc internally — not swappable without rebuilding
#    Dragonfly; its 256B+ loopback GET collapse is not allocator-related anyway
#    (its SET path, same allocator, pipelines fine).
#  - The real methodology gap: v4's DEFAULT myiothreadpipelinedepth is 16; the
#    paper conf set 32. Recent v4 re-tests used bare flags -> depth 16 -> ~6.75M
#    vs the paper's 8.17M. Re-test v4 WITH pd32+qd2048 on an idle box.
# This script measures what a rebuild CAN answer: libc vs jemalloc for the two
# canonical forks (paper-era laptop data said jemalloc = +30-54% over libc).
# ============================================================================
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6396
CLI="$P/redis/src/redis-cli -p $PORT"; D=/tmp/alloc_ab; mkdir -p $D
build_variant(){ local src="$1" dst="$2" malloc="$3"
  [ -x "$dst/src/redis-server" ] && { echo "reuse $dst"; return; }
  rm -rf "$dst"; cp -r "$src" "$dst"
  (cd "$dst/src" && make distclean >/dev/null 2>&1; make -j12 MALLOC=$malloc USE_URING=yes redis-server redis-cli >/dev/null 2>&1)
  "$dst/src/redis-server" --version; }
bench(){ local label="$1"; shift
  pkill -9 -x redis-server 2>/dev/null; sleep 1; rm -f $D/*.rdb
  "$@" --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/srv.log 2>&1 &
  for i in $(seq 1 80); do timeout 2 $CLI ping >/dev/null 2>&1 && break; sleep 0.3; done
  timeout 90 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 260000 -d 64 --hide-histogram >/dev/null 2>&1
  local g=$(timeout 45 $MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=20 --ratio=0:100 --key-pattern=R:R --key-maximum=2000000 -d 64 --hide-histogram 2>&1|awk '/^Totals/{print $2}')
  local s=$(timeout 45 $MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=20 --ratio=1:0 --key-pattern=R:R --key-maximum=2000000 -d 64 --hide-histogram 2>&1|awk '/^Totals/{print $2}')
  echo "$label GET=$g SET=$s"; pkill -9 -x redis-server 2>/dev/null; }
echo "== building libc variants (jemalloc variants = the existing canonical binaries) =="
build_variant $P/THredis-v12 /tmp/v12-libc libc
build_variant $P/THredis-strict-pool /tmp/pool-libc libc
echo "== bench (interleaved jemalloc/libc x 2 reps) =="
for rep in 1 2; do
  bench "v12-jemalloc(r$rep)"  $P/THredis-v12/src/redis-server --myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048
  bench "v12-libc(r$rep)"      /tmp/v12-libc/src/redis-server --myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048
  bench "pool-jemalloc(r$rep)" $P/THredis-strict-pool/src/redis-server --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2 --thredis-operand-pool-tiered yes
  bench "pool-libc(r$rep)"     /tmp/pool-libc/src/redis-server --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2 --thredis-operand-pool-tiered yes
done
echo "== also re-test the v4 gap properly (idle box, PAPER conf incl. pd32/qd2048) =="
bench "v4-paperconf" $P/old/THredis/src/redis-server --myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048
echo ALLOC_AB_DONE
