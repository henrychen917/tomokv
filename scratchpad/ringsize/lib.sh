# Boot/guard helpers for the ringsize lane. Ports 8091-8094, server cores 48-55, loadgen 184-191.
# Every boot is pgrep/ss-guarded: a leaked co-binding server splits traffic through SO_REUSEPORT and
# turns a real defect into a pass. Every stop kills by PID -- never a pattern that matches this shell.
PORT=${PORT:-8091}
SRVCORES=${SRVCORES:-48-55}
CLICORES=${CLICORES:-184-191}
CLI=${CLI:-/tmp/claude-1000/redis74/src/redis-cli}

port_owners(){ ss -H -ltnp "sport = :$1" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | paste -sd, -; }

guard_port(){
  local owners; owners=$(port_owners "$1")
  if [ -n "$owners" ] || (exec 3<>/dev/tcp/127.0.0.1/$1) 2>/dev/null; then
    echo "GUARD: port $1 already in use (pid=$owners)" >&2; return 1
  fi
  return 0
}

boot_srv(){ # boot_srv <binary> <logfile> [extra args...] -> sets SRV
  local bin="$1" log="$2"; shift 2
  guard_port "$PORT" || return 1
  taskset -c "$SRVCORES" "$bin" --port "$PORT" --bind 127.0.0.1 \
      --shards "${SHARDS:-16}" --thread-mode "${TM:-fused}" --read-local "${RL:-1}" \
      "$@" > "$log" 2>&1 &
  SRV=$!
  for _ in $(seq 200); do
    kill -0 "$SRV" 2>/dev/null || { wait "$SRV" 2>/dev/null; echo "BOOT DIED, see $log" >&2; return 1; }
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0
    sleep 0.2
  done
  echo "BOOT TIMEOUT, see $log" >&2; return 1
}

stop_srv(){
  [ -n "${SRV:-}" ] && kill -TERM "$SRV" 2>/dev/null
  wait "$SRV" 2>/dev/null
  for _ in $(seq 80); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null || break; sleep 0.1; done
  SRV=
}

info_field(){ $CLI -p "$PORT" info all 2>/dev/null | tr -d '\r' | sed -n "s/^$1://p"; }
