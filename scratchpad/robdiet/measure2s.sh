#!/bin/bash
# The same slope instrument booted in --thread-mode 2s. read-local is a 1s-only lane, so this arm
# must read as a null: it is the empirical form of "2s is untouched", covering the shared TU's
# compiler collateral as well as the source.
set -u
BIN="$1"; TAG="$2"; OUT="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT=8072; SRVCORE=40-41; CLICORE=42
source "$HERE/lib.sh"
N1=1000000; N2=3000000
LOG=$(mktemp /tmp/robdiet-2s-$TAG.XXXXXX)
guard_port "$PORT" || exit 1
taskset -c "$SRVCORE" "$BIN" --port "$PORT" --bind 127.0.0.1 --shards 16 \
    --thread-mode 2s --ratio 1:1 > "$LOG" 2>&1 &
SRV=$!
for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 0.2; done
for kl in 16 24 40; do taskset -c "$CLICORE" "$HERE/replay" "$PORT" warm "$kl" 0 0 32 4096 >/dev/null; done
for shape in get_hit get_miss set_over mixed11; do
  for kl in 16 24 40; do
    out=()
    for n in $N1 $N2; do
      pf=$(mktemp /tmp/robdiet-perf2s.XXXXXX)
      rep=$(perf stat -e instructions:u,instructions -x, -o "$pf" -C "$SRVCORE" -- \
            taskset -c "$CLICORE" "$HERE/replay" "$PORT" "$shape" "$kl" "$n" 32 32 4096 2>/dev/null)
      out+=("$(grep -m1 ',instructions:u,' "$pf" | cut -d, -f1) $(grep -m1 ',instructions,' "$pf" | cut -d, -f1) $(echo "$rep" | awk '{print $3}')")
      rm -f "$pf"
    done
    echo "$TAG,1,$shape,$kl,32,$N1,$N2,${out[0]},${out[1]}" >> "$OUT"
  done
done
kill -TERM "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null
echo "2s done $TAG"
