#!/bin/bash
# Time-dilated LRU discrimination: hot set touched AFTER a >=1-tick (256s) dwell must outlive
# untouched same-age cold keys under pressure.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${GATE_PORT:-7897}
CORES=${GATE_CORES:-4-5}
BINARY=${TOMOKV_BIN:-$ROOT/build/tomokv}

(exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null \
    && { echo "LRU-SLOW BOOT-FAIL: port $PORT already accepting"; exit 1; }
taskset -c "$CORES" "$BINARY" --port "$PORT" --bind 127.0.0.1 --shards 16 --ratio 1:1 \
    >/dev/null 2>&1 &
for _ in $(seq 50); do
    (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break
    sleep 0.2
done
SRV_PID=$(ss -lntpH "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
[ -n "$SRV_PID" ] && [ "$(printf '%s\n' "$SRV_PID" | wc -l)" -eq 1 ] \
    || { echo "LRU-SLOW BOOT-FAIL: listener identity missing/split"; exit 1; }
SRV_EXE=$(readlink -f "/proc/$SRV_PID/exe" 2>/dev/null)
[ "$SRV_EXE" = "$(readlink -f "$BINARY")" ] \
    || { echo "LRU-SLOW IDENTITY-FAIL: pid=$SRV_PID exe=${SRV_EXE:-none}"; exit 1; }

RC=0
python3 - "$PORT" <<'PYEOF' || RC=$?
import socket, sys, time
port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=20); f = s.makefile("rb")
def enc(a):
    o=b"*%d\r\n"%len(a)
    for x in a:
        x=x.encode() if isinstance(x,str) else x
        o+=b"$%d\r\n"%len(x)+x+b"\r\n"
    return o
def rr():
    line=f.readline(); t=line[:1]
    if t in b"+-:": return line.strip()
    if t==b"$":
        n=int(line[1:-2]); return None if n==-1 else f.read(n+2)[:-2]
    n=int(line[1:-2]); return [rr() for _ in range(n)]
def cmd(*a): s.sendall(enc(list(a))); return rr()
def fill(p,n,start=0):
    for i in range(start,start+n,500):
        s.sendall(b"".join(enc(["SET","%s:%d"%(p,j),"v"*100]) for j in range(i,min(i+500,start+n))))
        for _ in range(min(500,start+n-i)):
            r=rr()
cmd("CONFIG","SET","maxmemory","1048576"); cmd("CONFIG","SET","maxmemory-policy","allkeys-lru")
fill("hot",50); fill("cold",4000)
time.sleep(300)              # cross >= 1 LRU clock tick (256s resolution)
for i in range(50): cmd("GET","hot:%d"%i)   # re-touch hot AFTER the dwell
fill("press",8000)           # pressure: evictions must prefer the stale cohort
hot  = sum(1 for i in range(50) if cmd("EXISTS","hot:%d"%i)==b":1")
cold = sum(1 for i in range(0,4000,80) if cmd("EXISTS","cold:%d"%i)==b":1")
verdict = "PASS" if hot > cold else "FAIL"
print("LRU-SLOW %s: hot=%d/50 cold=%d/50 (dwell 300s > 256s tick)" % (verdict, hot, cold))
sys.exit(0 if verdict == "PASS" else 1)
PYEOF
kill -TERM "$SRV_PID" 2>/dev/null || RC=1
for _ in $(seq 100); do
    ss -lntpH "sport = :$PORT" 2>/dev/null | grep -q 'pid=' || break
    sleep 0.1
done
ss -lntpH "sport = :$PORT" 2>/dev/null | grep -q 'pid=' && RC=1
wait "$SRV_PID" 2>/dev/null || true
exit "$RC"
