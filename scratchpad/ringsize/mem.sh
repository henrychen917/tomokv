#!/bin/bash
# Resident set with many ARMED connections. The sidecar is allocated at accept on a read-local
# server (io_loop.h), so an idle armed connection pays for the ring whether it ever writes or not:
# that is the cost this lane must report, and it is measured, not size-classed on paper.
#   mem.sh <binary> <label> [conns]
set -u
BIN="$1"; LABEL="$2"; N="${3:-2000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
LOG=/tmp/ringsize-mem-$LABEL.log
boot_srv "$BIN" "$LOG" --atomic 0 --enable-debug-command yes || exit 1
sleep 2
rss0=$(awk '/^VmRSS/{print $2}' /proc/$SRV/status)
coro=$(mktemp -u); mkfifo "$coro"
taskset -c "$CLICORES" "$HERE/holdconns" "$PORT" "$N" < "$coro" > /tmp/ringsize-mem-$LABEL.n &
HOLD=$!
exec 9>"$coro"
for _ in $(seq 100); do [ -s /tmp/ringsize-mem-$LABEL.n ] && break; sleep 0.2; done
sleep 3
up=$(cat /tmp/ringsize-mem-$LABEL.n)
rss1=$(awk '/^VmRSS/{print $2}' /proc/$SRV/status)
clients=$($CLI -p $PORT info clients 2>/dev/null | tr -d '\r' | sed -n 's/^connected_clients://p')
exec 9>&-
wait $HOLD 2>/dev/null
rm -f "$coro"
stop_srv
per=$(python3 -c "print(f'{(($rss1-$rss0)*1024.0)/max(1,$up):.1f}')")
echo "$LABEL conns_up=$up connected_clients=$clients rss_idle_kB=$rss0 rss_loaded_kB=$rss1 delta_kB=$((rss1-rss0)) bytes_per_conn=$per"
