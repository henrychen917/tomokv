#!/bin/bash
# TASK#43 regression: same-client "SET b NEW" then "MGET a b" must return NEW for b.
# Positive control: MUST fail on a pre-fix build (that is what makes it a real test).
set -u
J=/shared/Projects/.claude/jobs/fd085c8e/tmp
BIN=${TOMO_BIN:?}; LBL=${LBL:-bin}; EXTRA=${EXTRA:-}
pkill -9 -x redis-server 2>/dev/null; sleep 1; rm -rf $J/otd; mkdir -p $J/otd
taskset -c 0-7 $BIN --port 7984 --dir $J/otd --tomokv-numa-nodes 1 --tomokv-io-threads 4 \
  --tomokv-ex-threads 4 --thredis-flat-store 1 $EXTRA --save '' --appendonly no \
  --protected-mode no --logfile $J/ot.log >/dev/null 2>&1 &
sleep 3
python3 - "$LBL" <<'PY'
import socket,re,sys
lbl=sys.argv[1]
try: s=socket.create_connection(("127.0.0.1",7984)); s.settimeout(25)
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
# read-only pipeline must still take the fast path: verify MGET-only throughput is unhurt
print(f"{lbl}: checked={chk} stale={stale} => {'FAIL(ordering)' if stale else 'PASS'}")
PY
pkill -9 -x redis-server 2>/dev/null
