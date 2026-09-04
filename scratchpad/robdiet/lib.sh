# Shared boot/guard helpers for the robdiet instruction lane. Ports 8071-8074, cores 40-47/168-175.
PORT=${PORT:-8071}
SRVCORE=${SRVCORE:-40}
CLICORE=${CLICORE:-41}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

port_owners(){ ss -H -ltnp "sport = :$1" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | paste -sd, -; }

guard_port(){ # a leaked co-binding server silently splits traffic via SO_REUSEPORT: refuse to boot
  local owners; owners=$(port_owners "$1")
  if [ -n "$owners" ] || (exec 3<>/dev/tcp/127.0.0.1/$1) 2>/dev/null; then
    echo "GUARD: port $1 already in use (pid=$owners)" >&2; return 1
  fi
  return 0
}

boot_srv(){ # boot_srv <binary> <logfile> [extra args...] -> SRV pid
  local bin="$1" log="$2"; shift 2
  guard_port "$PORT" || return 1
  taskset -c "$SRVCORE" "$bin" --port "$PORT" --bind 127.0.0.1 --shards 16 \
      --thread-mode fused --read-local "${RL:-1}" "$@" > "$log" 2>&1 &
  SRV=$!
  for _ in $(seq 150); do
    kill -0 "$SRV" 2>/dev/null || { wait "$SRV" 2>/dev/null; echo "BOOT DIED, see $log" >&2; return 1; }
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0
    sleep 0.2
  done
  echo "BOOT TIMEOUT, see $log" >&2; return 1
}

stop_srv(){ # kill by PID only; never pkill a pattern that can match this shell
  [ -n "${SRV:-}" ] && kill -TERM "$SRV" 2>/dev/null
  wait "$SRV" 2>/dev/null
  for _ in $(seq 50); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || break; sleep 0.1; done
  SRV=
}
