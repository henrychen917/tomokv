#!/bin/bash
# Time-dilated LRU discrimination: hot set touched AFTER a >=1-tick (256s) dwell must outlive
# untouched same-age cold keys under pressure.
cd /home/user/Projects/tomokv-cpp-evict
taskset -c 4-5 build/tomokv --port 7897 --bind 127.0.0.1 --shards 16 --ratio 1:1 >/dev/null 2>&1 &
TS=$!; sleep 1.5
python3 - <<'PYEOF'
import socket, time
s = socket.create_connection(("127.0.0.1", 7897), timeout=20); f = s.makefile("rb")
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
PYEOF
kill -TERM $TS 2>/dev/null
