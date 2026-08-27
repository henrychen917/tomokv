#!/usr/bin/env bash
# Lane t-edgeenc harness. Cores 16-31, ports 7400-7409 ONLY.
#
# Every server is resolved and stopped by its LISTENING SOCKET pid, never by name or pattern:
# other lanes run a binary of the same name on this box, and pattern selection has taken their
# servers down twice in this program. A boot refuses to proceed until the previous listener on
# that port is gone, because a leftover listener joins the next start under SO_REUSEPORT and the
# client load then splits silently across two servers.
#
#   source scratchpad/edgeenc/lane.sh
#   boot_tomo 7400 --atomic 0 --enable-debug-command yes
#   boot_redis 7401                 # the vanilla 7.4 oracle
#   boot_redis_c 7402               # oracle under LC_ALL=C (see NOTES-EDGEENC.md on SORT ALPHA)
#   stop_port 7400
set -u
WT=${WT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
CORES=${CORES:-16-31}
REDIS=${REDIS:-/tmp/claude-1000/redis74/src/redis-server}
LOGDIR=${LOGDIR:-/tmp/claude-1000/edgeenc}
mkdir -p "$LOGDIR"

listener_pid() { ss -lntpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }

wait_listen() {
  local t=${2:-20} i=0
  while [ $i -lt $((t*20)) ]; do
    [ -n "$(listener_pid "$1")" ] && return 0
    sleep 0.05; i=$((i+1))
  done
  return 1
}

wait_gone() {
  local i=0
  while [ $i -lt 400 ]; do
    [ -z "$(listener_pid "$1")" ] && return 0
    sleep 0.05; i=$((i+1))
  done
  return 1
}

stop_port() {
  local pid
  pid=$(listener_pid "$1")
  [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null
  if ! wait_gone "$1"; then
    pid=$(listener_pid "$1")
    [ -n "$pid" ] && kill -KILL "$pid" 2>/dev/null
    wait_gone "$1" || { echo "FATAL: port $1 listener will not release"; return 1; }
  fi
  return 0
}

boot_tomo() {
  local port=$1; shift
  stop_port "$port" || return 1
  taskset -c $CORES "$WT/build/tomokv" --port "$port" --bind 127.0.0.1 --shards 4 \
      --ratio 2:2 --protected-mode no "$@" >"$LOGDIR/tomo-$port.log" 2>&1 &
  wait_listen "$port" || { echo "FATAL: tomokv did not listen on $port"; tail -20 "$LOGDIR/tomo-$port.log"; return 1; }
  echo "tomokv listening on $port pid=$(listener_pid "$port")"
}

_boot_redis() {
  local locale=$1 port=$2; shift 2
  stop_port "$port" || return 1
  env LC_ALL="$locale" taskset -c $CORES "$REDIS" --port "$port" --bind 127.0.0.1 \
      --save '' --appendonly no --protected-mode no "$@" >"$LOGDIR/redis-$port.log" 2>&1 &
  wait_listen "$port" || { echo "FATAL: redis did not listen on $port"; tail -20 "$LOGDIR/redis-$port.log"; return 1; }
  echo "redis(LC_ALL=$locale) listening on $port pid=$(listener_pid "$port")"
}

boot_redis()   { _boot_redis "${LC_ALL:-en_US.UTF-8}" "$@"; }
boot_redis_c() { _boot_redis C "$@"; }
