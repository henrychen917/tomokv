#!/bin/bash
# Unchanged standard matrix (tests/differ_gate.sh: permanent seeds 7/19/20/23 plus one rotating
# seed, every suite, both atomic modes, both geometries) on both network engines. The engine is
# selected only by a target executable wrapper; differ_gate.sh/differ.py and tolerances are
# untouched. Target CPUs 64-71, Redis 7.4 oracle on 72, clients 73-79, ports 24820/24821.
# Correctness only, never a performance run. Per-leg logs stay in build/clockcut/differ/.
set -u
cd "$(dirname "$0")/../.."
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
export GATE_LOAD_CORES=73-79 GATE_DIFFER_ORACLE_CORES=72
export GATE_RUN_ID=clockcut-final-standard
root="$PWD/build/clockcut/differ"
mkdir -p "$root"
cat >"$root/tomokv-epoll" <<WRAPPER
#!/bin/bash
exec "$PWD/build/tomokv" --net-io epoll "\$@"
WRAPPER
chmod +x "$root/tomokv-epoll"
status="$root/status.tsv"
: >"$status"
for engine in uring epoll; do
  binary="$PWD/build/tomokv"
  [ "$engine" != epoll ] || binary="$root/tomokv-epoll"
  for geometry in split armed-fused; do
    out="$root/$engine-$geometry"
    if [ -e "$out" ]; then echo "refusing existing result $out" >&2; exit 2; fi
    export GATE_DIFFER_GEOMETRY="$geometry" GATE_DIFFER_OUT="$out"
    start=$SECONDS
    taskset -c 73-79 bash tests/differ_gate.sh "$binary" 24820 24821 64-71 6:2 >"$out.log" 2>&1
    rc=$?
    printf '%s\t%s\t%s\t%ss\n' "$engine" "$geometry" "$rc" "$((SECONDS - start))" >>"$status"
  done
done
cat "$status"
