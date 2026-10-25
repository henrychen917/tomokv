#!/bin/bash
# Rerun the unchanged complete gate job after preceding churn has stopped.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
while [ ! -f docs/ctlfix/proof-chain.done ]; do sleep 2; done
for arm in post pre; do
  binary="$ROOT/build/tomokv"
  [ "$arm" != pre ] || binary="$ROOT/build/tomokv-PRE"
  label="listener-$arm-final"
  # Unlike a LISTEN-only probe, bind also detects conflicting client TIME_WAIT
  # sockets in this lane's allocated range. No connection or listener is opened.
  first=$(python3 - "$ROOT/docs/ctlfix/$label-ports.json" <<'PY'
import json, socket, sys
from pathlib import Path
for first in range(35841, 35898, 2):
    sockets = []
    try:
        for port in range(first, first + 3):
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
        Path(sys.argv[1]).write_text(json.dumps(dict(ports=list(range(first, first+3)),
            precondition='TCP and TLS bind succeeded before invoking the whole gate job'))+'\n')
        print(first)
        break
    except OSError:
        pass
    finally:
        for sock in sockets:
            sock.close()
else:
    raise SystemExit('No free three-port slot within 35841-35899')
PY
  ) || exit 1
  GATE_ONLY_JOBS=fliplisten GATE_LEDGER="$ROOT/docs/ctlfix/$label" \
    tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 \
      --ports "$first-$((first+2))" --candidate-binary "$binary" \
      >"docs/ctlfix/$label.log" 2>&1
  echo "$?" >"docs/ctlfix/$label.rc"
  python3 tools/ctlfix_artifacts.py archive "docs/ctlfix/$label.log"
done
echo finished > docs/ctlfix/listener-proof.done
