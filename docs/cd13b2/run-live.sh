#!/bin/bash
# Narrow cd13b2 proof: reuse the landed harness's guarded boot, identity and cleanup.
# Run from this worktree root. No gate matrix, seed-history writes or measurements.
set -euo pipefail
OUT="$PWD/build/cd13b2/live"
test ! -e "$OUT"
mkdir -p "$OUT"
TARGET_BIN="$PWD/build/tomokv"
TARGET_PORT=8198
ORACLE_PORT=8199
TARGET_CORES=112-119
ORACLE_CORES=120-123
LOAD_CORES=124-127
TARGET_PID=0
ORACLE_PID=0
BOOT_PID=0
ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
ORACLE_ALIGNMENT=()

# As in tests/cd13b_oracle.sh, fail if the harness extraction boundaries change.
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
source = Path("tests/differ_gate.sh").read_text()
markers = ('say(){', 'if ! [[ "$TARGET_PORT"', 'run_matrix(){\n',
           'for ATOMIC in "${ATOMICS[@]}"; do')
for marker in markers:
    assert source.count(marker) == 1, marker
out = Path(sys.argv[1])
(out / "functions.sh").write_text(source[source.index(markers[0]):source.index(markers[1])])
start = source.index(markers[2]) + len(markers[2])
(out / "oracle-boot.sh").write_text(source[start:source.index(markers[3])])
PY
source "$OUT/functions.sh"
source "$OUT/oracle-boot.sh"
test "$REDIS_VERSION" = 7.4.10
sha256sum "$TARGET_BIN" "$ORACLE_BIN"

for geometry in split armed-fused; do
    case "$geometry" in
        split) TARGET_SHAPE=(--ratio 6:2);;
        armed-fused) TARGET_SHAPE=(--thread-mode fused --read-local 1);;
    esac
    TARGET_DIR="$OUT/$geometry"
    mkdir -p "$TARGET_DIR"
    boot_owned "target $geometry atomic=1" "$TARGET_PORT" "$TARGET_CORES" "$TARGET_DIR/server.log" \
        "$TARGET_BIN" --port "$TARGET_PORT" --bind 127.0.0.1 --shards 16 \
        "${TARGET_SHAPE[@]}" --databases 16 --atomic 1 --save '' --dir "$TARGET_DIR" \
        --enable-debug-command yes
    TARGET_PID=$BOOT_PID
    for protocol in 2 3; do
        RESP_FLAGS=()
        if [ "$protocol" -eq 3 ]; then RESP_FLAGS=(-3); fi
        for suite in cmdmeta geo; do
            LEG="$OUT/$geometry-$suite-resp$protocol"
            GATE_DIFFER_COVERAGE="$LEG.coverage.json" \
                taskset -c "$LOAD_CORES" timeout 180 python3 tests/differ.py \
                127.0.0.1 "$TARGET_PORT" 127.0.0.1 "$ORACLE_PORT" \
                "$suite" 7 "${RESP_FLAGS[@]}" > "$LEG.log" 2>&1
            test -s "$LEG.coverage.json"
            say "$geometry $suite RESP$protocol" "$(tail -n 1 "$LEG.log")"
        done
    done
    stop_owned "target $geometry" "$TARGET_PID" "$TARGET_PORT"
    TARGET_PID=0
done
stop_owned oracle "$ORACLE_PID" "$ORACLE_PORT"
ORACLE_PID=0
