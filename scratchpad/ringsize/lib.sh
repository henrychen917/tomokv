# Boot/guard helpers for the ringsize lane. Ports 8300-8309.
#
# CORES (re-allocated 2026-09-05: the old 48-55/176-183 pin collided with another lane through SMT
# siblings, so every number taken under it is void). This lane owns physical 58-63 and their SMT
# siblings 186-191, and nothing else:
#     server           58-61   (siblings 186-189 deliberately left IDLE)
#     load generators  62-63   plus their siblings 190-191
# Server and load generator are on different PHYSICAL cores, so no arm of an A/B is ever measured
# against a load generator sharing its execution units. The server's siblings are left idle rather
# than reclaimed: a server measured with its own SMT siblings loaded reports an IPC that is a
# property of the co-tenant, not of the change. The load generator may use its siblings -- nothing
# reports the generator's IPC. See laneguard.sh.
#
# Every boot is pgrep/ss-guarded: a leaked co-binding server splits traffic through SO_REUSEPORT and
# turns a real defect into a pass. Every stop kills by PID -- never a pattern that matches this shell.
PORT=${PORT:-8300}
SRVCORES=${SRVCORES:-58-61}
CLICORES=${CLICORES:-62-63,190-191}
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
  assert_pinned "$SRV" "$SRVCORES" "server" || return 1
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

# EVERY LOAD GENERATOR IS CHECKED, NOT JUST WRAPPED. An unpinned memtier lands on whatever cores the
# scheduler likes -- including another lane's benchmark server -- and corrupts a verdict at BOTH
# ends: theirs, because our load competes with their server, and ours, because their server competes
# with our load generator. A `taskset` prefix that silently failed to apply is indistinguishable
# from one that applied, unless somebody reads the mask back out of the kernel. So this reads it
# back, and refuses to measure anything if it does not match.
: "${CLICORES:?CLICORES must be set before any load generator starts}"
: "${SRVCORES:?SRVCORES must be set before any server starts}"

assert_pinned(){ # assert_pinned <pid> <expected-cpu-list> [label]
  local pid="$1" want="$2" label="${3:-process $1}" got=""
  for _ in $(seq 60); do
    got=$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' "/proc/$pid/status" 2>/dev/null)
    [ -n "$got" ] && break
    sleep 0.05
  done
  if [ -z "$got" ]; then
    echo "PIN CHECK: $label (pid $pid) exited before its mask could be read" >&2
    return 0                       # it is gone; it cannot be on anyone's cores
  fi
  if [ "$got" != "$want" ]; then
    echo "PIN FAIL: $label (pid $pid) is on [$got], expected [$want]" >&2
    kill -TERM "$pid" 2>/dev/null
    return 1
  fi
  return 0
}

# Start memtier pinned to $CLICORES, prove it, and return its pid in MEMTIER_PID. The caller waits.
start_cli(){ # start_cli <outfile> <memtier args...>
  local out="$1"; shift
  taskset -c "$CLICORES" memtier_benchmark "$@" > "$out" 2>&1 &
  MEMTIER_PID=$!
  assert_pinned "$MEMTIER_PID" "$CLICORES" "load generator" || return 1
  return 0
}

# The whole of a memtier run, pinned and proven, with no perf window around it.
run_cli(){ # run_cli <outfile> <memtier args...>
  start_cli "$@" || return 1
  wait "$MEMTIER_PID"
}
