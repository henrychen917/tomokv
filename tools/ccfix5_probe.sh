#!/bin/bash
# Import the gate's exact armed-fused boot and listener ownership helpers.
set -eu
cd "$(dirname "$0")/.."
export GATE_LOAD_CORES=120-127
export GATE_DIFFER_GEOMETRY=armed-fused
export GATE_DIFFER_OUT="$PWD/build/ccfix5/probe-${2:?arm name}"
source <(python3 - <<'PY'
from pathlib import Path
s = Path('tests/differ_gate.sh').read_text()
boundary = 'if ! [[ "$TARGET_PORT" =~'
assert s.count(boundary) == 1
print(s[:s.index(boundary)])
PY
) "${1:?binary}" 18179 18180 112-119 6:2
for REPEAT in 1 2 3; do
  for ATOMIC in 0 1; do
    DIR="$OUT/r$REPEAT-a$ATOMIC"
    mkdir -p "$DIR"
    boot_owned "target r$REPEAT atomic=$ATOMIC" "$TARGET_PORT" "$TARGET_CORES" "$DIR/server.log" \
      "$TARGET_BIN" --port "$TARGET_PORT" --bind 127.0.0.1 --shards 16 \
      "${TARGET_SHAPE[@]}" --databases 16 --atomic "$ATOMIC" --save '' --dir "$DIR" \
      --enable-debug-command yes
    TARGET_PID=$BOOT_PID
    taskset -c "$LOAD_CORES" python3 tools/ccfix5_probe.py "$TARGET_PORT" > "$DIR/probe.jsonl" 2>&1
    stop_owned target "$TARGET_PID" "$TARGET_PORT"
    TARGET_PID=0
  done
done
