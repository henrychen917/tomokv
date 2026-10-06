#!/bin/bash
# Boot ONLY the Redis oracle, using differ_gate.sh's unchanged guarded boot/identity/cleanup.
# TomoKV runs as the serverless RESP fixture. No TomoKV listener or gate matrix is started.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$PWD/build/cd13b/oracle-$(date +%s)-$$"
mkdir -p "$OUT"
TARGET_PID=0
TARGET_PORT=0
ORACLE_PID=0
BOOT_PID=0
ORACLE_PORT=${CD13B_ORACLE_PORT:-8197}
ORACLE_CORES=120-127
LOAD_CORES=112-127
ORACLE_BIN=${GATE_DIFFER_ORACLE_BIN:-/home/user/Projects/redis74/src/redis-server}
REDIS_CLI=${GATE_DIFFER_REDIS_CLI:-/home/user/Projects/redis74/src/redis-cli}
ORACLE_ALIGNMENT=()
# Reuse the harness verbatim. Extraction deliberately fails if its boundaries change.
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
source = Path("tests/differ_gate.sh").read_text()
for marker in ('say(){', 'if ! [[ "$TARGET_PORT"', 'run_matrix(){\n', 'for ATOMIC in "${ATOMICS[@]}"; do'):
    assert source.count(marker) == 1, marker
out = Path(sys.argv[1])
(out / "functions.sh").write_text(source[source.index('say(){'):source.index('if ! [[ "$TARGET_PORT"')])
start = source.index('run_matrix(){\n') + len('run_matrix(){\n')
(out / "boot.sh").write_text(source[start:source.index('for ATOMIC in "${ATOMICS[@]}"; do')])
PY
source "$OUT/functions.sh"
source "$OUT/boot.sh"
taskset -c 112-127 python3 tests/cd13b_checks.py run --oracle-port "$ORACLE_PORT" "$@"
