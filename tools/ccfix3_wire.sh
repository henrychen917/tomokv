#!/bin/bash
# Focused CC11/12/13/18 proof. Reuse the gate's exact listener ownership helpers;
# this is deliberately not a differential-matrix receipt or an extra gate row.
set -eu
cd "$(dirname "$0")/.."
export GATE_LOAD_CORES=${GATE_LOAD_CORES:-120-127}
export GATE_DIFFER_OUT=${GATE_DIFFER_OUT:-$PWD/build/ccfix3/wire-${GATE_DIFFER_GEOMETRY:-split}}
export REDIS74_ROOT=${REDIS74_ROOT:-/home/user/Projects/redis}
export GATE_DIFFER_ORACLE_CORES=${GATE_DIFFER_ORACLE_CORES:-120}
# Import setup and boot_owned/stop_owned/cleanup verbatim, before the matrix runner.
# Abort if the harness boundary changes rather than silently running the full matrix.
source <(python3 - <<'PY'
from pathlib import Path
s = Path('tests/differ_gate.sh').read_text()
boundary = 'if ! [[ "$TARGET_PORT" =~'
assert s.count(boundary) == 1
print(s[:s.index(boundary)])
PY
) "${1:-$PWD/build/ccfix3/POST/tomokv}" "${2:-17989}" "${3:-17990}" 112-119 6:2
mkdir -p "$OUT/oracle"
CCFIX_ACLFILE="$(realpath "$OUT")/ccfix.acl"
printf 'user default on nopass ~* &* +@all\n' > "$CCFIX_ACLFILE"
boot_owned 'Redis 7.4.10 oracle' "$ORACLE_PORT" "$ORACLE_CORES" "$OUT/oracle.log" \
    "$ORACLE_BIN" --bind 127.0.0.1 --port "$ORACLE_PORT" --protected-mode no \
    --dir "$OUT/oracle" --dbfilename dump.rdb --appendonly no --save '' \
    --enable-debug-command yes --aclfile "$CCFIX_ACLFILE"
ORACLE_PID=$BOOT_PID
"$REDIS_CLI" -p "$ORACLE_PORT" INFO server > "$OUT/oracle-identity.txt"
grep -q '^redis_version:7\.4\.10' "$OUT/oracle-identity.txt"
for ATOMIC in 0 1; do
    mkdir -p "$OUT/target-$ATOMIC"
    boot_owned "target atomic=$ATOMIC" "$TARGET_PORT" "$TARGET_CORES" "$OUT/target-$ATOMIC.log" \
        "$TARGET_BIN" --port "$TARGET_PORT" --bind 127.0.0.1 --shards 16 \
        "${TARGET_SHAPE[@]}" --databases 16 --atomic "$ATOMIC" --save '' \
        --dir "$OUT/target-$ATOMIC" --enable-debug-command yes --aclfile "$CCFIX_ACLFILE"
    TARGET_PID=$BOOT_PID
    for SEED in 7 19; do
        LEG_LOG="$OUT/ccfix-a$ATOMIC-s$SEED.txt"
        GATE_DIFFER_COVERAGE="$LEG_LOG.coverage.json" \
            taskset -c "$LOAD_CORES" timeout 120 python3 tests/differ.py \
            127.0.0.1 "$TARGET_PORT" 127.0.0.1 "$ORACLE_PORT" ccfix "$SEED" \
            > "$LEG_LOG" 2>&1
        test -s "$LEG_LOG.coverage.json"
        tail -n 1 "$LEG_LOG"
    done
    stop_owned target "$TARGET_PID" "$TARGET_PORT"
    TARGET_PID=0
done
stop_owned oracle "$ORACLE_PID" "$ORACLE_PORT"
ORACLE_PID=0
echo "PASS ccfix3 focused differential: $TARGET_GEOMETRY, atomic=0/1, seeds=7/19 (not a gate receipt)"
