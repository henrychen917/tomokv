#!/bin/bash
# One GEO leg using differ_gate.sh's guarded boot, oracle identity and cleanup.
# Run from this worktree root after the selected gate jobs have finished.
set -euo pipefail
OUT="$PWD/build/cd13b3/geo"
test ! -e "$OUT"
mkdir -p "$OUT"
TARGET_BIN="$PWD/build/tomokv"
TARGET_PORT=18340
ORACLE_PORT=18341
TARGET_CORES=112-119
ORACLE_CORES=120-123
LOAD_CORES=124-127
TARGET_PID=0
ORACLE_PID=0
BOOT_PID=0
ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
ORACLE_ALIGNMENT=()

# Reuse the harness verbatim, refusing changed extraction boundaries.
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

TARGET_DIR="$OUT/target"
mkdir -p "$TARGET_DIR"
boot_owned "target split atomic=1" "$TARGET_PORT" "$TARGET_CORES" "$OUT/target.log" \
    "$TARGET_BIN" --port "$TARGET_PORT" --bind 127.0.0.1 --shards 16 \
    --ratio 6:2 --databases 16 --atomic 1 --save '' --dir "$TARGET_DIR" \
    --enable-debug-command yes
TARGET_PID=$BOOT_PID
LEG="$OUT/geo-resp3"
GATE_DIFFER_COVERAGE="$LEG.coverage.json" \
    taskset -c "$LOAD_CORES" timeout 180 python3 tests/differ.py \
    127.0.0.1 "$TARGET_PORT" 127.0.0.1 "$ORACLE_PORT" geo 7 -3 > "$LEG.log" 2>&1
test -s "$LEG.coverage.json"
cat "$LEG.log"
stop_owned target "$TARGET_PID" "$TARGET_PORT"
TARGET_PID=0
stop_owned oracle "$ORACLE_PID" "$ORACLE_PORT"
ORACLE_PID=0
