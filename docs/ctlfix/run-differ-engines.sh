#!/bin/bash
# Two independent correctness queues; no measurement or timing claim.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
engine=${1:?uring or epoll}
case "$engine" in
  uring)
    # Let the already-running split matrix finish normally before retiring its
    # paused sequential outer loop. No server or differential leg is interrupted.
    python3 - <<'WAIT'
from pathlib import Path
import json, os, re, signal, time
out=Path('docs/ctlfix');receipt=out/'differ-scheduling.json'
d=json.loads(receipt.read_text());pid=d['retired_outer_loop']
log=out/'differ-final-uring-split.log'
while True:
    text=log.read_text()
    children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
    exited=all(Path(f'/proc/{child}/stat').read_text().rsplit(')',1)[1].split()[0]=='Z'
               for child in children)
    summaries=[line for line in text.splitlines() if line.startswith('DIFFER GATE:')]
    if summaries and exited:break
    time.sleep(2)
os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
result=int(int(re.search(r'fail=(\d+)',summaries[-1])[1])!=0)
(out/'differ-final-uring-split.rc').write_text(str(result)+'\n')
d['original_split_finished_normally']=True
d['original_split_result_from_complete_summary']=result
receipt.write_text(json.dumps(d,indent=2)+'\n')
print('uring split finished; retired only its paused outer queue',flush=True)
WAIT
    server_cores=48-55; load_cores=56-63; first_min=35861; first_max=35877
    geometries=armed-fused
    ;;
  epoll)
    server_cores=56-63; load_cores=48-55; first_min=35881; first_max=35897
    geometries='split armed-fused'
    ;;
  *) exit 2;;
esac
for geometry in $geometries; do
  label="differ-final-$engine-$geometry"
  first=$(python3 - "docs/ctlfix/$label-ports.json" "$first_min" "$first_max" \
      "$server_cores" "$load_cores" <<'PORTS'
import json, socket, sys
from pathlib import Path
for first in range(int(sys.argv[2]),int(sys.argv[3])+1,2):
    sockets=[]
    try:
        for port in range(first,first+3):
            sock=socket.socket();sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('127.0.0.1',port))
        Path(sys.argv[1]).write_text(json.dumps(dict(target=first,oracle=first+1,
            control=first+2,server_cores=sys.argv[4],load_cores=sys.argv[5],
            precondition='All three binds succeeded before the matrix'))+'\n')
        print(first);break
    except OSError:pass
    finally:
        for sock in sockets:sock.close()
else:raise SystemExit('No free three-port slot within the engine reservation')
PORTS
  ) || exit 1
  mkdir -p "docs/ctlfix/$label"
  GATE_LOAD_CORES="$load_cores" GATE_DIFFER_ORACLE_CORES="$server_cores" \
    GATE_DIFFER_NET_IO="$engine" GATE_DIFFER_GEOMETRY="$geometry" \
    GATE_DIFFER_OUT="$ROOT/docs/ctlfix/$label" \
    tests/differ_gate.sh "$ROOT/build/tomokv" "$first" "$((first+1))" "$server_cores" 6:2 \
    >"docs/ctlfix/$label.log" 2>&1
  result=$?
  echo "$result" >"docs/ctlfix/$label.rc"
  printf '%s rc=%s\n' "$label" "$result"
done
echo finished > "docs/ctlfix/differ-$engine.done"
