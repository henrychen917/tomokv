#!/bin/bash
# Standard complete differential matrices. No focused suite/seed overrides.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
while [ ! -f docs/ctlfix/listener-proof.done ]; do sleep 2; done
for engine in uring epoll; do
  for geometry in split armed-fused; do
    label="differ-final-$engine-$geometry"
    first=$(python3 - "docs/ctlfix/$label-ports.json" <<'PORTS'
import json, socket, sys
from pathlib import Path
for first in range(35861, 35898, 2):
    sockets = []
    try:
        for port in range(first, first + 3):
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
        Path(sys.argv[1]).write_text(json.dumps(dict(target=first, oracle=first+1,
            control=first+2, precondition='All three binds succeeded before the matrix'))+'\n')
        print(first)
        break
    except OSError:
        pass
    finally:
        for sock in sockets:
            sock.close()
else:
    raise SystemExit('No free three-port slot within 35861-35899')
PORTS
    ) || exit 1
    mkdir -p "docs/ctlfix/$label"
    GATE_LOAD_CORES=56-63 GATE_DIFFER_ORACLE_CORES=48-55 \
      GATE_DIFFER_NET_IO="$engine" GATE_DIFFER_GEOMETRY="$geometry" \
      GATE_DIFFER_OUT="$ROOT/docs/ctlfix/$label" \
      tests/differ_gate.sh "$ROOT/build/tomokv" "$first" "$((first+1))" 48-55 6:2 \
      >"docs/ctlfix/$label.log" 2>&1
    result=$?
    echo "$result" >"docs/ctlfix/$label.rc"
    printf '%s rc=%s\n' "$label" "$result"
  done
done
echo finished > docs/ctlfix/differ-proof.done
