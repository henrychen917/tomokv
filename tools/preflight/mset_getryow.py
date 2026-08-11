#!/usr/bin/env python3
# I7 check: atomic MSET then PLAIN GETs (not MGET) on one conn must see the new values (linearizable
# reply + plain-read resolve). Usage: mset_getryow.py PORT ROUNDS NKEYS
import socket,sys
PORT=int(sys.argv[1]); R=int(sys.argv[2]); N=int(sys.argv[3])
KEYS=['pg:%d'%i for i in range(N)]
s=socket.create_connection(('127.0.0.1',PORT),timeout=10); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1); f=s.makefile('rb')
def enc(*a):
    o=[b'*%d\r\n'%len(a)]
    for x in a:
        b=x if isinstance(x,bytes) else str(x).encode(); o.append(b'$%d\r\n'%len(b)+b+b'\r\n')
    return b''.join(o)
def rr():
    ln=f.readline(); t=ln[:1]
    if t==b'$':
        n=int(ln[1:]); return None if n<0 else f.read(n+2)[:-2]
    return ln[1:].strip()
bad=0
for r in range(R):
    tag=('T%d'%r).encode()
    pkt=enc('MSET',*[x for k in KEYS for x in (k,tag)])+b''.join(enc('GET',k) for k in KEYS)
    s.sendall(pkt); rr()
    for _ in range(N):
        if rr()!=tag: bad+=1
print("plainGET_RYOW rounds=%d violations=%d (%.4f%%)"%(R,bad,100.0*bad/max(1,R*N)))
