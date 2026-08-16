#!/bin/bash
# TASK#43 regression: same-client "SET b NEW" then "MGET a b" must return NEW for b.
# Positive control: MUST fail on a pre-fix build (that is what makes it a real test).
set -u
J=/tmp/tomo_pfjob
BIN=${TOMO_BIN:?}; LBL=${LBL:-bin}; EXTRA=${EXTRA:-}
PORT=${PORT_OVERRIDE:-5984}
ORD_SRV_PID=""
ORD_CLIENT_PID=""
ORD_STAGED_BIN=""
reap_ord_group(){
  local pid=${1:-} n=0
  [ -n "$pid" ] || return 0
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM -- "$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 30 ]; do
    sleep .1
    n=$((n+1))
  done
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL -- "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
cleanup_ord(){
  if [ -n "${ORD_CLIENT_PID:-}" ]; then
    reap_ord_group "$ORD_CLIENT_PID"
    ORD_CLIENT_PID=""
  fi
  if [ -n "${ORD_SRV_PID:-}" ]; then
    reap_ord_group "$ORD_SRV_PID"
    ORD_SRV_PID=""
  fi
  [ -z "${ORD_STAGED_BIN:-}" ] || rm -f -- "$ORD_STAGED_BIN"
}
# Tear our server down on EVERY exit path -- normal, error, or signal. Without the trap an early
# `exit` (bind failure, probe timeout) leaks the server and, with it, the box lock.
trap cleanup_ord EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

# PORT_OVERRIDE means the caller already owns the server. correctness_suite uses this mode so its
# ordering probe actually shares the server receiving the concurrent memtier load.
if [ -z "${PORT_OVERRIDE:-}" ]; then
  if [ "${BOXLOCKED:-0}" != 1 ]; then
    echo "$LBL: BOOTFAIL (standalone server requires BOXLOCKED=1 withbox.sh)"
    exit 2
  fi
  OTD=$(mktemp -d "$J/ord_test.XXXXXX") || exit 2
  ORD_STAGED_BIN=$OTD/ord-server-$BASHPID
  if ! cp -- "$BIN" "$ORD_STAGED_BIN" || ! chmod 700 "$ORD_STAGED_BIN"; then
    echo "$LBL: BOOTFAIL (could not stage candidate)"
    exit 2
  fi
  setsid taskset -c 0-7 "$ORD_STAGED_BIN" --bind 127.0.0.1 --port "$PORT" \
    --dir "$OTD" --tomokv-nodes 1 --tomokv-thread-io 4 \
    --tomokv-thread-ex 4 $EXTRA --save '' --appendonly no \
    --daemonize no --protected-mode no --logfile "$OTD/server.log" \
    >"$OTD/server.launch.log" 2>&1 &
  ORD_SRV_PID=$!
  setsid timeout --foreground --signal=TERM --kill-after=2 20s \
    taskset -c 16-23 python3 - "$PORT" "$ORD_SRV_PID" >"$OTD/boot.out" 2>&1 <<'PY' &
import os, re, socket, sys, time
port, wanted = int(sys.argv[1]), int(sys.argv[2])
request = b"*2\r\n$4\r\nINFO\r\n$6\r\nserver\r\n"
deadline = time.monotonic() + 18
while time.monotonic() < deadline:
    try:
        os.kill(wanted, 0)
    except OSError:
        raise SystemExit("captured server exited before readiness")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.75) as sock:
            sock.settimeout(.75)
            sock.sendall(request)
            data = b""
            while b"\r\nprocess_id:" not in data and len(data) < (1 << 20):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
            match = re.search(rb"(?:^|\r\n)process_id:(\d+)\r\n", data)
            if match:
                actual = int(match.group(1))
                if actual != wanted:
                    raise SystemExit(
                        f"port owned by pid={actual}, captured pid={wanted}"
                    )
                print(f"READY process_id={actual}")
                raise SystemExit(0)
    except (ConnectionError, OSError, socket.timeout):
        pass
    time.sleep(.1)
raise SystemExit("readiness deadline expired")
PY
  ORD_CLIENT_PID=$!
  wait "$ORD_CLIENT_PID"
  BOOT_RC=$?
  ORD_CLIENT_PID=""
  if [ "$BOOT_RC" -ne 0 ]; then
    echo "$LBL: BOOTFAIL ($(tr '\n' ' ' <"$OTD/boot.out"))"
    exit 1
  fi
fi

ORD_RC=0
setsid timeout --foreground --signal=TERM --kill-after=5 \
  "${ORD_TIMEOUT:-120}s" taskset -c 16-23 python3 - "$LBL" "$PORT" <<'PY' &
import socket,re,sys
lbl=sys.argv[1]
port=int(sys.argv[2])
try: s=socket.create_connection(("127.0.0.1",port), timeout=5); s.settimeout(25)
except Exception as e: print(f"{lbl}: BOOTFAIL"); raise SystemExit(1)
def cmd(*a):
    o=f"*{len(a)}\r\n".encode()
    for x in a: b=x.encode(); o+=b"$%d\r\n%s\r\n"%(len(b),b)
    return o
N=6000
s.sendall(b"".join(cmd("SET",f"ak:{i}","A")+cmd("SET",f"bk:{i}","OLD") for i in range(N)))
r=b""
while r.count(b"+OK")<2*N: r+=s.recv(1<<20)
s.sendall(b"".join(cmd("SET",f"bk:{i}","NEW")+cmd("MGET",f"ak:{i}",f"bk:{i}") for i in range(N)))
d=b""
while d.count(b"*2\r\n")<N:
    c=s.recv(1<<20)
    if not c: break
    d+=c
chk=stale=0
for p in d.split(b"+OK\r\n")[1:]:
    m=re.match(rb"\*2\r\n\$1\r\nA\r\n\$(\d+)\r\n([A-Z]+)\r\n",p)
    if m:
        chk+=1
        if m.group(2)!=b"NEW": stale+=1
# A malformed/truncated reply that matches fewer than N elements is just as
# wrong as a stale value; never let a positive subset certify the row.
ok = chk == N and stale == 0
print(f"{lbl}: checked={chk} stale={stale} => {'PASS' if ok else 'FAIL(ordering)'}")
raise SystemExit(0 if ok else 1)
PY
ORD_CLIENT_PID=$!
wait "$ORD_CLIENT_PID" || ORD_RC=$?
ORD_CLIENT_PID=""
cleanup_ord   # our pid only -- never a shared name
exit "$ORD_RC"
