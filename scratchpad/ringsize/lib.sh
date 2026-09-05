# Boot/guard helpers for the ringsize lane. Ports 8300-8309.
#
# CORES. This lane owns physical 58-63 and their SMT siblings 186-191, and nothing else:
#     server           58-59        two shards, one per core
#     server siblings  186-187      LEFT IDLE, ALWAYS -- see below
#     load generators  60-63,188-191   four physical cores, both hardware threads of each
#
# WHY THE SERVER'S SIBLINGS ARE IDLE AND THE GENERATOR'S ARE NOT. These are two different rules and
# only one of them is a law. The law: nothing may run on 186-187, because a server measured with a
# co-tenant on its own execution units reports an IPC and a cycles/op that are properties of the
# co-tenant, and cycles/op is this lane's verdict column. The generator's siblings carry no such
# rule -- nobody reports generator IPC -- and leaving them idle was a choice that turned out to be
# the wrong one: eight memtier threads were time-slicing FOUR logical cpus, two threads per hardware
# thread, so the generator was rationed by the OS scheduler rather than by the hardware.
#
# WHY THAT MATTERS, from the data. The first null (3 server / 3 load cores) moved -12.14% on one
# binary against itself. Re-pinned to 2/4 it moved -0.03/+0.14/+0.57% on its three real cells --
# medians finally honest -- but the read-only control still swung 14.17% visit to visit and the
# server burned 1.75 of its 2 cores in EVERY cell at every rate. A server with an eighth of a core
# spare is not the thing being measured, and a control that swings 14% cannot resolve the 2-4%
# question this lane exists to answer. Eight generator threads now get eight hardware threads.
#
# THE SATURATION CLAIM IS TESTED, NOT ASSERTED (satcheck.sh): the generator is given progressively
# more capacity and the rate is watched. If more generator buys more rate, the generator was the
# limit and no rate A/B taken there means anything.

PORT=${PORT:-8300}
SRVCORES=${SRVCORES:-58-59}
CLICORES=${CLICORES:-60-63,188-191}
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
  # A FAILED BOOT PRINTS ITS OWN LOG. "see $log" is a pointer into a file that a killed run, a
  # cleaned tmpdir or a lost transcript can all take away, and a boot failure diagnosed an hour
  # later from no evidence is a boot failure diagnosed by guessing. The server always says why it
  # refused -- the 2s battery's "16 threads but only 8 allowed cpus" was a correct refusal that read
  # as a mystery for as long as nobody printed it.
  for _ in $(seq 200); do
    kill -0 "$SRV" 2>/dev/null || { wait "$SRV" 2>/dev/null
      echo "BOOT DIED ($bin, port $PORT) -- last 25 lines of $log:" >&2
      tail -25 "$log" >&2; return 1; }
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && return 0
    sleep 0.2
  done
  echo "BOOT TIMEOUT ($bin, port $PORT) -- last 25 lines of $log:" >&2
  tail -25 "$log" >&2; return 1
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
  # COMPARE SETS, NOT STRINGS. The kernel prints its own normalisation of the mask, so "60-63,188-191"
  # and a differently-spelled but identical set are the same pin and must not fail the check --
  # while a genuinely different set must, whatever it looks like.
  if ! python3 -c '
import sys
def ex(s):
    o=set()
    for p in s.split(","):
        p=p.strip()
        if not p: continue
        if "-" in p:
            a,b=p.split("-",1); o.update(range(int(a),int(b)+1))
        else: o.add(int(p))
    return o
sys.exit(0 if ex(sys.argv[1])==ex(sys.argv[2]) else 1)' "$got" "$want"; then
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
