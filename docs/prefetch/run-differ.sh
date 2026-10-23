#!/bin/bash
# Correctness only: complete standard-seed matrices, both engines and geometries.
set -eu
cd "$(dirname "$0")/../.."
root=$PWD
mkdir -p build/prefetch/differ
for engine in uring epoll; do
  # differ_gate has no engine argument. An exec-only argv wrapper keeps its
  # owned-server PID, CPU/port guards, suite inventory, and seeds unchanged.
  wrapper="$root/build/prefetch/differ/tomokv-$engine"
  printf '#!/bin/bash\nexec "%s/build/tomokv" --net-io %s "$@"\n' "$root" "$engine" > "$wrapper"
  chmod +x "$wrapper"
  for geometry in split armed-fused; do
    out="$root/build/prefetch/differ/$engine-$geometry"
    mkdir -p "$out"
    rc=0
    GATE_LOAD_CORES=89-95 GATE_DIFFER_ORACLE_CORES=80-87 \
      REDIS74_ROOT=/tmp/claude-1000/redis74 \
      GATE_RUN_ID=prefetch-standard-post GATE_DIFFER_GEOMETRY="$geometry" GATE_DIFFER_OUT="$out" \
      taskset -c 89-95 tests/differ_gate.sh "$wrapper" 23800 23801 80-87 6:2 \
      > "$out/run.log" 2>&1 || rc=$?
    printf '%s\n' "$rc" > "$out/exit-code"
  done
done
