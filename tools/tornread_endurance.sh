#!/usr/bin/env bash
# Full Phase B correctness matrix, adapted to lane tornread's authorized CPUs and ports.
# Every arm runs for at least 180 s unless a violation/error fails it early.
# Usage: tools/tornread_endurance.sh [tomo1|tomo0]...
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HERE=$ROOT/tests
BIN=${TORNREAD_BIN:-$ROOT/build/tornread/tomokv-part2}
REDIS74_ROOT=${REDIS74_ROOT:-/tmp/claude-1000/redis74}
REDIS_BIN=$REDIS74_ROOT/src/redis-server
SERVER_CPUS=0-7
CLIENT_CPUS=8-11
FAILED=0

[ -x "$BIN" ] || { echo "missing $BIN" >&2; exit 2; }

RUN=$ROOT/build/tornread/endurance-$(date +%Y%m%d-%H%M%S)
mkdir -p "$RUN" || exit 2
SUMMARY=$RUN/summary.tsv
echo "$RUN"
OWN_PIDS=()

stop_pid(){ # stop one of OUR servers by PID
  local pid=$1
  [ -n "$pid" ] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  kill -TERM "$pid" 2>/dev/null
  if ! timeout 30 tail --pid="$pid" -f /dev/null 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null
  fi
  wait "$pid" 2>/dev/null
}
cleanup(){ for p in "${OWN_PIDS[@]}"; do stop_pid "$p"; done; }
trap cleanup EXIT
trap 'exit 130' INT TERM

port_free(){ # no listener and no accepting peer
  local port=$1
  [ -z "$(ss -ltnH "sport = :$port" 2>/dev/null)" ] || return 1
  (exec 3<>/dev/tcp/127.0.0.1/"$port") 2>/dev/null && return 1
  return 0
}

boot(){ # tag port kind(tomo|redis) [extra args...]  -> sets SRV_PID
  local tag=$1 port=$2 kind=$3; shift 3
  SRV_PID=
  if ! port_free "$port"; then
    echo "BOOT $tag: port $port busy (listener: $(ss -ltnpH "sport = :$port"))" >&2
    return 1
  fi
  local dir=$RUN/data-$tag log=$RUN/server-$tag.log
  mkdir -p "$dir"
  if [ "$kind" = tomo ]; then
    LC_ALL=C taskset -c "$SERVER_CPUS" "$BIN" --port "$port" --bind 127.0.0.1 --shards 16 \
        --ratio 6:2 --dir "$dir" --save '' --databases 1 "$@" >"$log" 2>&1 &
  else
    LC_ALL=C taskset -c "$SERVER_CPUS" "$REDIS_BIN" --port "$port" --bind 127.0.0.1 \
        --dir "$dir" --save '' --appendonly no --protected-mode no --daemonize no \
        "$@" >"$log" 2>&1 &
  fi
  SRV_PID=$!
  OWN_PIDS+=("$SRV_PID")
  echo "$SRV_PID" >"$RUN/server-$tag.pid"
  for _ in $(seq 150); do
    if ! kill -0 "$SRV_PID" 2>/dev/null; then
      echo "BOOT $tag: exited before listening; log tail:" >&2; tail -n 20 "$log" >&2; return 1
    fi
    (exec 3<>/dev/tcp/127.0.0.1/"$port") 2>/dev/null && break
    sleep 0.2
  done
  # pgrep-guard: the listener on our port must be OUR pid, nothing else.
  local owners
  owners=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | sort -u | tr '\n' ' ')
  if [ "$owners" != "pid=$SRV_PID " ]; then
    echo "BOOT $tag: listener owners '$owners' != pid=$SRV_PID; refusing to run" >&2
    return 1
  fi
  echo "BOOT $tag: pid $SRV_PID on port $port, cpus $SERVER_CPUS ($(taskset -cp "$SRV_PID" 2>/dev/null | sed 's/.*: //'))"
}

arm(){ # tag port label seconds [torntest args...]
  local tag=$1 port=$2 label=$3 seconds=$4; shift 4
  local out=$RUN/$tag-$label
  seconds=180
  LC_ALL=C taskset -c "$CLIENT_CPUS" python3 -I "$HERE/tornread.py" --port "$port" \
      --label "$tag-$label" --seconds "$seconds" --max-violations "1" --json "$out.json" "$@" \
      2>&1 | tee "$out.log"
  local rc=${PIPESTATUS[0]}
  [ "$rc" = 0 ] || FAILED=1
  printf '%s\t%s\t%s\n' "$tag" "$label" "$rc" >>"$SUMMARY"
}

echo "== binary: $("$BIN" --version 2>&1 | head -1); sha256 $(sha256sum "$BIN" | cut -c1-16)"
echo "== redis:  $("$REDIS_BIN" --version 2>&1 | head -1)"
echo "== CPU share check (processes on CPUs 0-11 using >5% CPU, informational)"
ps -eo pid,psr,pcpu,comm --sort=-pcpu | awk 'NR==1 || ($2>=0 && $2<=11 && $3>5)' | head -20
echo "== tomokv processes already running (not ours, never touched):"
pgrep -a -x tomokv | head || true

run_matrix(){ # tag port atomic(1|0|-) kind
  local tag=$1 port=$2 at=$3 kind=$4
  local req=()
  [ "$at" != - ] && req=(--require-atomic "$at" --geometry debug)
  if [ "$at" = 1 ] || [ "$at" = - ]; then
    arm "$tag" "$port" pipe            120 "${req[@]}" --read-mode pipe
    arm "$tag" "$port" pipe-lag         60 "${req[@]}" --read-mode pipe --readers 5 --lag-noise 2
    arm "$tag" "$port" pipe-mgetnoise   60 "${req[@]}" --read-mode pipe --readers 5 --mget-noise 2
    arm "$tag" "$port" pipe-multiwriter 60 "${req[@]}" --read-mode pipe --writers 4 --groups 1 --readers 4
    arm "$tag" "$port" split            45 "${req[@]}" --read-mode split
    arm "$tag" "$port" pipe-exec        60 "${req[@]}" --read-mode pipe --writer-kind exec
    arm "$tag" "$port" seq-control      60 "${req[@]}" --read-mode seq
    if [ "$kind" = tomo ]; then
      arm "$tag" "$port" pipe-readdelay20 45 "${req[@]}" --read-mode pipe --read-delay-us 20
    fi
  else
    # --atomic 0 (the default): MSET is documented non-atomic there; EXEC is still atomic.
    arm "$tag" "$port" pipe-exec        90 "${req[@]}" --read-mode pipe --writer-kind exec
    arm "$tag" "$port" pipe-exec-lag    60 "${req[@]}" --read-mode pipe --writer-kind exec --readers 5 --lag-noise 2
    arm "$tag" "$port" seq-exec-control 30 "${req[@]}" --read-mode seq --writer-kind exec
  fi
}

TARGETS=("$@")
[ ${#TARGETS[@]} -gt 0 ] || TARGETS=(tomo1 tomo0)
for target in "${TARGETS[@]}"; do
  case "$target" in
    tomo1)
      boot tomo1 26090 tomo --atomic 1 --key-lb 0 --flip-auto 0 --enable-debug-command yes || { FAILED=1; continue; }
      run_matrix tomo1 26090 1 tomo
      stop_pid "$SRV_PID";;
    tomo0)
      boot tomo0 26091 tomo --atomic 0 --key-lb 0 --flip-auto 0 --enable-debug-command yes || { FAILED=1; continue; }
      run_matrix tomo0 26091 0 tomo
      stop_pid "$SRV_PID";;
    redis)
      boot redis 26092 redis || { FAILED=1; continue; }
      run_matrix redis 26092 - redis
      stop_pid "$SRV_PID";;
    *) echo "unknown target $target" >&2;;
  esac
done

echo "== summary (exit codes: 0 clean, 1 violations, 2 vacuous/error)"
cat "$SUMMARY"
python3 -I - "$RUN" <<'EOF'
import glob, json, os, sys
rows = []
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    s = json.load(open(path))
    rows.append((s["label"], s["server"], s["atomic"], s["elapsed_s"], s["read_pairs"], s["writes"],
                 s["value_changes_seen"], s["violations"], s["torn_pairs"], s["mget_violations"],
                 "; ".join(s["vacuous"]) or "-"))
print("label\tserver\tatomic\tsecs\tpairs\twrites\tchanges\tviol\ttorn\tmgetviol\tvacuous")
for r in rows:
    print("\t".join(str(x) for x in r))
EOF

exit "$FAILED"
