#!/bin/bash
# NT-new-7 oracle receipt: run tests/ntnew4_clock.py's `boundary` action, unchanged, against one
# server booted under that file's frozen-clock shim. Correctness only; owned PID only.
#   boundary_oracle.sh redis  <redis-server> <port> <cpus> <out.log>
#   boundary_oracle.sh tomokv <tomokv> <port> <cpus> <out.log> [2s|1s|1s-armed]
set -u
cd "$(dirname "$0")/../.."
kind=$1 binary=$2 port=$3 cpus=$4 out=$5 mode=${6:-2s}
work=$(mktemp -d "$PWD/build/clockcut/boundary.XXXXXX") || exit 2
python3 tests/ntnew4_clock.py prepare --clock-file "$work/clock" || exit 2
if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then echo "port $port busy" >&2; exit 2; fi
if [ "$kind" = redis ]; then
  args=(--port "$port" --bind 127.0.0.1 --save '' --appendonly no --enable-debug-command yes
        --dir "$work" --daemonize no)
else
  args=(--port "$port" --bind 127.0.0.1 --shards 16 --dir "$work" --save '' --databases 1
        --atomic 0 --key-lb 0 --client-lb 0 --flip-auto 0 --enable-debug-command yes
        --appendonly no)
  case "$mode" in
    2s) args+=(--ratio 6:2 --read-local 0);;
    1s) args+=(--thread-mode fused --read-local 0);;
    1s-armed) args+=(--thread-mode fused --read-local 1);;
    *) echo "unknown mode $mode" >&2; exit 2;;
  esac
fi
LD_PRELOAD="$work/clock.so" TOMO_NTNEW4_CLOCK="$work/clock" \
  taskset -c "$cpus" "$binary" "${args[@]}" >"$work/server.log" 2>&1 &
pid=$!
echo "$pid" >"$work/server.pid"
for _ in $(seq 150); do
  (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && break
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.2
done
{
  echo "server=$kind mode=$mode binary=$binary sha256=$(sha256sum "$binary" | cut -d' ' -f1)"
  python3 tests/ntnew4_clock.py boundary --port "$port" --clock-file "$work/clock" 2>&1
  echo "boundary_rc=$?"
} >"$out"
if [ "$(readlink "/proc/$pid/exe")" = "$(readlink -f "$binary")" ]; then
  kill -TERM "$pid"; wait "$pid" 2>/dev/null
fi
rc=$(sed -n 's/^boundary_rc=//p' "$out")
rm -rf "$work"
exit "${rc:-2}"
