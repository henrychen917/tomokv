# preflight_lib.sh — shared port-safety helpers (defeat SO_REUSEPORT silent split).
#
# THE BUG THESE DEFEAT. Every IO thread holds its own SO_REUSEPORT listener on the
# server's port. If a leaked or co-scheduled server is still alive on that port when a
# suite boots its own, the kernel silently load-balances NEW connections across BOTH —
# the suite then measures a blend of two binaries. A bind never fails, so the split is
# invisible. The authority is the PORT, not the process name: suites stage binaries
# under private names, so pgrep-by-name misses a leaker. These helpers gate on the port.
#
# Source-able with no side effects. POSIX-bash, no `set -e`, self-contained.

# port_has_listener <port>: 0 (true) if anything is LISTENing on the TCP port.
port_has_listener() { ss -ltn "sport = :$1" 2>/dev/null | grep -q ":$1"; }

# wait_port_free <port>: block until the port has no listener (up to ~10s); return 1 if
# it never frees. Call this BEFORE launching so a leaked server cannot join our accept
# group under SO_REUSEPORT.
wait_port_free() { local p=$1 i; for i in $(seq 1 100); do port_has_listener "$p" || return 0; sleep 0.1; done; return 1; }

# server_identity_ok <cli> <port> <pid>: N fresh INFO conns must ALL land on our pid.
# If any connection is answered by a different process_id, a second listener is stealing
# a share of our traffic (the silent split) and every measurement on this port is void.
server_identity_ok() { local cli=$1 port=$2 pid=$3 i got; for i in $(seq 1 8); do
  got=$(timeout 2 "$cli" -p "$port" info server 2>/dev/null | tr -d '\r' | sed -n 's/^process_id://p')
  [ "$got" = "$pid" ] || { echo "SO_REUSEPORT split: conn hit pid=$got not $pid on :$port" >&2; return 1; }
  done; return 0; }

# 2026-08-17 gate geometry. These are deliberately constants, not tuning defaults: a
# preflight stamp is meaningful only for the production shape it certifies. In particular,
# CPUs 128-159 are the SMT siblings of the server's physical CPUs 0-31 and therefore must
# never be offered to a load generator.
PREFLIGHT_NODES=2
PREFLIGHT_CORES_PER_NODE=16
PREFLIGHT_SERVER_CORES=0-31
PREFLIGHT_LOADGEN_CORES=32-127,160-255

preflight_cpuset_within_server() { # Linux cpulist on stdin; true iff every cpu is 0..31
  awk -F, '
    function badpart(p, a, n, lo, hi) {
      if (p !~ /^[0-9]+(-[0-9]+)?$/) return 1
      n=split(p,a,"-"); lo=a[1]+0; hi=(n==2?a[2]+0:lo)
      return lo < 0 || hi > 31 || lo > hi
    }
    NF == 0 { bad=1; next }
    { for (i=1;i<=NF;i++) if (badpart($i)) exit 1 }
    END { if (NR == 0 || bad) exit 1 }
  '
}

preflight_assert_standard_boot() { # server-log server-pid [io-per-node ex-per-node]
  local log=$1 pid=$2 want_io=${3:-} want_ex=${4:-} i n line cpus bad=0 live_tasks=0

  if [ -n "$want_io" ] && [ -n "$want_ex" ]; then
    if [ $((want_io + want_ex)) -ne "$PREFLIGHT_CORES_PER_NODE" ]; then
      echo "BOOT-GEOMETRY FAIL: io=$want_io ex=$want_ex is not a 16-thread/node split" >&2
      return 1
    fi
  fi
  [ "${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}" = "$PREFLIGHT_SERVER_CORES" ] || {
    echo "BOOT-GEOMETRY FAIL: TOMO_SERVER_CORES=${TOMO_SERVER_CORES:-unset}; gate requires 0-31" >&2
    return 1
  }
  [ "${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}" = "$PREFLIGHT_LOADGEN_CORES" ] || {
    echo "BOOT-GEOMETRY FAIL: TOMO_LOADGEN_CORES=${TOMO_LOADGEN_CORES:-unset}; gate requires 32-127,160-255" >&2
    return 1
  }

  # Pin records are emitted just after the listener starts. Give them a bounded moment to
  # reach the logfile; never turn a missing/renamed record into a green absence check.
  for i in $(seq 1 50); do
    n=$(grep -cE "^${pid}:[A-Z] .* (IO thread|Worker) [0-9]+ pinned to core [0-9]+ " "$log" 2>/dev/null || true)
    [ "${n:-0}" -ge 32 ] && break
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  kill -0 "$pid" 2>/dev/null || {
    echo "BOOT-PIN FAIL: server pid $pid exited before the live pin census" >&2
    return 1
  }

  grep -qE "^${pid}:[A-Z] .*tomokv topology: 2 node\(s\) x 16 cores \(io [0-9]+ \+ ex [0-9]+ per node\)" "$log" 2>/dev/null || {
    echo "BOOT-GEOMETRY FAIL: missing 2 node(s) x 16 cores topology line in $log" >&2
    return 1
  }
  if [ -n "$want_io" ] && [ -n "$want_ex" ]; then
    grep -qE "^${pid}:[A-Z] .*tomokv topology: 2 node\(s\) x 16 cores \(io $want_io \+ ex $want_ex per node\)" "$log" 2>/dev/null || {
      echo "BOOT-GEOMETRY FAIL: boot did not materialize requested io=$want_io ex=$want_ex in $log" >&2
      return 1
    }
  fi
  # The topology line itself is authoritative even when callers did not pass expected io/ex.
  line=$(grep -E "^${pid}:[A-Z] .*tomokv topology: 2 node\(s\) x 16 cores " "$log" | tail -1)
  local split
  split=$(printf '%s\n' "$line" | sed -nE 's/.*\(io ([0-9]+) \+ ex ([0-9]+) per node\).*/\1 \2/p')
  set -- $split
  [ "$#" -eq 2 ] && [ $(( $1 + $2 )) -eq 16 ] || {
    echo "BOOT-GEOMETRY FAIL: topology is not a 16-thread/node budget: $line" >&2
    return 1
  }

  for i in 0 1; do
    grep -qE "^${pid}:[A-Z] .*tomokv pin-mode ccd: node $i: L3 groups [0-9]+(\+[0-9]+)+, cpus " "$log" 2>/dev/null || {
      echo "BOOT-PIN FAIL: missing composed 'node $i: L3 groups A+B' boot line in $log" >&2
      return 1
    }
  done
  if grep -E "^${pid}:[A-Z] .*SMT sharing is in use" "$log" >/dev/null 2>&1; then
    echo "BOOT-PIN FAIL: server fell back to SMT in $log" >&2
    return 1
  fi
  if grep -E "^${pid}:[A-Z] .*(Failed to pin |not in the process.s allowed cpu set|floats)" "$log" >/dev/null 2>&1; then
    echo "BOOT-PIN FAIL: at least one server thread floated; see $log" >&2
    return 1
  fi

  n=0
  while IFS= read -r cpus; do
    n=$((n+1))
    [ "$cpus" -ge 0 ] 2>/dev/null && [ "$cpus" -le 31 ] 2>/dev/null || bad=1
  done < <(sed -nE "s/^${pid}:[A-Z] .* (IO thread|Worker) [0-9]+ pinned to core ([0-9]+) .*/\2/p" "$log")
  if [ "$n" -lt 32 ] || [ "$bad" != 0 ]; then
    echo "BOOT-PIN FAIL: pinned records=$n outside_0_31=$bad in $log" >&2
    return 1
  fi

  # Log assertions catch the mapping decision. The live task census catches an unlogged
  # failure/fallback: every server task must still have an affinity wholly inside 0-31.
  for line in /proc/"$pid"/task/*/status; do
    [ -r "$line" ] || continue
    live_tasks=$((live_tasks+1))
    cpus=$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' "$line")
    [ -n "$cpus" ] && printf '%s\n' "$cpus" | preflight_cpuset_within_server || {
      echo "BOOT-PIN FAIL: ${line%/status} has Cpus_allowed_list=${cpus:-unreadable}, outside 0-31" >&2
      return 1
    }
  done
  [ "$live_tasks" -ge 32 ] || {
    echo "BOOT-PIN FAIL: live task census found only $live_tasks tasks for pid $pid" >&2
    return 1
  }
  kill -0 "$pid" 2>/dev/null || {
    echo "BOOT-PIN FAIL: server pid $pid exited during the live pin census" >&2
    return 1
  }
  echo "BOOT-PIN PASS: 2x16c, composed L3 groups present, $n role threads wholly on cores 0-31"
}

preflight_flip_verdict() { # server-log phase-start-epoch phase-end-epoch
  # Port of scratchpad/movelog.py. Only completed role moves count. Search before the
  # first >=30 s quiet gap is not thrash. A move after such a gap is the sole thrash
  # verdict; lacking 45 s of terminal quiet means the observation window was too short.
  python3 - "$1" "$2" "$3" <<'PY'
import datetime as dt
import locale
import re
import sys

SETTLE_S = 30.0
TERM_S = 45.0
locale.setlocale(locale.LC_TIME, 'C')
path, start_s, end_s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
pat = re.compile(r'(\d+ \w+ \d+ \d+:\d+:\d+\.\d+) \* ee451 flip: GROW-(?:FRONT|BACK) complete')
moves = []
with open(path, errors='replace') as src:
    for line in src:
        match = pat.search(line)
        if not match:
            continue
        try:
            stamp = dt.datetime.strptime(match.group(1), '%d %b %Y %H:%M:%S.%f').timestamp()
        except ValueError:
            continue
        if start_s <= stamp <= end_s:
            moves.append(stamp)

gaps = [b - a for a, b in zip(moves, moves[1:])]
post_stable = sum(1 for gap in gaps if gap >= SETTLE_S)
last = moves[-1] if moves else start_s
terminal = max(0.0, end_s - last)
span = (moves[-1] - moves[0]) if len(moves) > 1 else 0.0
if post_stable:
    verdict = 'SETTLE_THEN_MOVED'
elif terminal >= TERM_S:
    verdict = 'STABILIZED_CLEAN'
else:
    verdict = 'STILL_SEARCHING'
print(f'{verdict}\t{len(moves)}\t{span:.3f}\t{terminal:.3f}\t{post_stable}')
PY
}
