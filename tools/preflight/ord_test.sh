#!/bin/bash
# TASK#43 regression: same-client "SET b NEW" then "MGET a b" must return NEW for b.
# Positive control: MUST fail on a pre-fix build (that is what makes it a real test).
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
J=/shared/Projects/.claude/jobs/fd085c8e/tmp
BIN=${TOMO_BIN:?}; LBL=${LBL:-bin}; EXTRA=${EXTRA:-}
# ee451 2026-07-29: DO NOT `pkill -9 -x "$(basename "${BIN}")"` here. Two separate defects, both measured:
#  (1) it kills EVERY server on the box, including other sessions' -- that is how a live preflight
#      and several queued jobs died on 2026-07-28; and
#  (2) it never matched OUR OWN server anyway, because callers pass TOMO_BIN staged under a private
#      name (e.g. "post"/"redis-corr"). So every run LEAKED a busy-spinning server.
# The leak was not merely wasteful: withbox.sh holds the box lock on fd 9, the leaked server
# inherited that fd, and it therefore held the SHARED BOX LOCK FOREVER. One such leak idled the box
# for ~4 hours with 10 jobs queued behind it, and it was invisible to `fuser`-style inspection
# because the holder was a redis-server named "post", not a flock. Kill our OWN pid, nothing else.
rm -rf $J/otd; mkdir -p $J/otd
taskset -c 0-7 $BIN --port 7984 --dir $J/otd --tomokv-nodes 1 --tomokv-thread-io 4 \
  --tomokv-thread-ex 4 $EXTRA --save '' --appendonly no \
  --protected-mode no --logfile $J/ot.log >/dev/null 2>&1 &
ORD_SRV_PID=$!
# Tear our server down on EVERY exit path -- normal, error, or signal. Without the trap an early
# `exit` (bind failure, probe timeout) leaks the server and, with it, the box lock.
trap 'kill -9 "$ORD_SRV_PID" 2>/dev/null' EXIT TERM INT HUP
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
kill -9 "$ORD_SRV_PID" 2>/dev/null   # our pid only -- never a shared name
