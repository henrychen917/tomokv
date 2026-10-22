#!/bin/bash
# wave3: respresume's fragmentation corpus (tests/respresume.py fragment: every byte split of 66
# payloads, 1..1Mi+1-argument frames at seeds 7/19/20/23, bulk boundaries, protocol errors with
# close) over TLS against the integrated binary, compared with Redis 7.4.10 over plain TCP, as the
# lane ran it (proof/tlsfrag-*.out). io_uring TLS skips the 606 close-expecting trials (respresume
# finding F2, pre-existing; ntfix lane). Gate shapes: 1s = fused --read-local 1 --reorder 1,
# 2s = --thread-mode 2s 6:2; 16 shards, client/key LB off, DEBUG on, --databases 1.
# tomo 80-87, Redis 88, driver 89-95; ports 22853 (plain) / 22854 (TLS) / 22855 (Redis).
# usage: rr_tlsfrag.sh MODE ENGINE OUT
set -u
MODE=$1 ENGINE=$2 OUT=$(realpath -m "$3")
cd /home/user/Projects/cx-wave3
POST=build/tomokv ORACLE=/home/user/Projects/redis74/src/redis-server
mkdir -p "$OUT/tomo-data" "$OUT/redis-data" "$OUT/tls"
python3 tests/tls.py --generate "$OUT/tls" > "$OUT/tls-generate.log" 2>&1 || { echo "cert generation failed"; exit 2; }
if [ "$MODE" = 1s ]; then SHAPE=(--thread-mode fused --read-local 1 --reorder 1); else SHAPE=(--thread-mode 2s --ratio 6:2); fi
for p in 22853 22854 22855; do [ -z "$(ss -H -ltn "sport = :$p")" ] || { echo "port $p busy" >&2; exit 2; }; done
sha256sum "$POST" "$ORACLE" > "$OUT/binaries.sha256"
taskset -c 80-87 "$POST" --databases 1 --port 22853 --tls-port 22854 --bind 127.0.0.1 --shards 16 \
  --net-io "$ENGINE" "${SHAPE[@]}" --client-lb 0 --key-lb 0 --enable-debug-command yes --save '' \
  --appendonly no --dir "$OUT/tomo-data" --tls-cert-file "$OUT/tls/server.crt" \
  --tls-key-file "$OUT/tls/server.key" --tls-ca-cert-file "$OUT/tls/ca.crt" --tls-auth-clients no \
  > "$OUT/tomo.log" 2>&1 &
TPID=$!
taskset -c 88 "$ORACLE" --port 22855 --bind 127.0.0.1 --save '' --appendonly no --dir "$OUT/redis-data" \
  > "$OUT/redis.log" 2>&1 &
RPID=$!
cleanup(){
  kill -TERM "$TPID" "$RPID" 2>/dev/null
  for _ in $(seq 100); do kill -0 "$TPID" 2>/dev/null || kill -0 "$RPID" 2>/dev/null || break; sleep 0.1; done
  kill -KILL "$TPID" "$RPID" 2>/dev/null; wait "$TPID" "$RPID" 2>/dev/null
}
trap cleanup EXIT
for port in 22853 22854 22855; do
  for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null && break; sleep 0.1; done
done
skip=(); [ "$ENGINE" = epoll ] || skip=(--skip-close-cases)
cd tests
taskset -c 89-95 python3 respresume.py fragment 127.0.0.1 22854 --oracle-port 22855 --tls "${skip[@]}" \
  > "$OUT/tlsfrag.out" 2>&1
rc=$?
tail -n 1 "$OUT/tlsfrag.out"
echo "rc=$rc"
exit $rc
