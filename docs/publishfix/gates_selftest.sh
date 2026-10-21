#!/bin/bash
# Keep the selftest's one ephemeral listener within this lane's port reservation.
# All test assertions and the TIME_WAIT negative control remain unchanged.
set -eu
cd "$(dirname "$0")/../.."
OUT=$PWD/build/publishfix/gates-selftest
mkdir -p "$OUT/site" "$OUT/tmp"
cat > "$OUT/site/sitecustomize.py" <<'PY'
import socket
_bind = socket.socket.bind
def lane_bind(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        if address[1] == 0:
            address = (address[0], 25890, *address[2:])
        assert 25800 <= address[1] <= 25899, address
    return _bind(self, address)
socket.socket.bind = lane_bind
PY
TMPDIR="$OUT/tmp" PYTHONPATH="$OUT/site" \
  taskset -c 104-111 python3 tests/gates_test.py > "$OUT/result.log" 2>&1
