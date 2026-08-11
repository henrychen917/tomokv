#!/usr/bin/env python3
# DEL-vs-MSET atomicity discriminator (broadened epoch). Writer A MSETs all N keys with a rotating
# tag; writer B DELs all N keys; reader pipelines MGET + EXISTS over the same keys.
# With tomokv-atomic ON the invariants are:
#   MGET snapshot: values are ALL-nil or ALL-one-tag (a mix of tags OR a mix of nil/values = torn)
#   EXISTS count: 0 or N, never in between (torn count = partial delete/write visible)
# Usage: delmset_torn.py PORT SECS NKEYS
import socket, sys, threading, time
PORT=int(sys.argv[1]); SECS=float(sys.argv[2]) if len(sys.argv)>2 else 6; N=int(sys.argv[3]) if len(sys.argv)>3 else 8
KEYS=['dmt:%d'%i for i in range(N)]
def conn():
    s=socket.create_connection(('127.0.0.1',PORT),timeout=10); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1); return s,s.makefile('rb')
def enc(*a):
    o=[b'*%d\r\n'%len(a)]
    for x in a:
        b=x if isinstance(x,bytes) else str(x).encode(); o.append(b'$%d\r\n'%len(b)+b+b'\r\n')
    return b''.join(o)
def rr(f):
    ln=f.readline(); t=ln[:1]
    if t==b'$':
        n=int(ln[1:]); return None if n<0 else f.read(n+2)[:-2]
    if t==b'*':
        n=int(ln[1:]); return None if n<0 else [rr(f) for _ in range(n)]
    return ln[1:].strip()
stop=threading.Event()
def wA():
    C=conn(); r=0
    while not stop.is_set():
        tag=b'A%d'%r; r+=1
        C[0].sendall(enc('MSET',*[x for k in KEYS for x in (k,tag)])); rr(C[1])
def wB():
    C=conn(); d=enc('DEL',*KEYS)
    while not stop.is_set():
        C[0].sendall(d); rr(C[1])
mget_torn=[0]; ex_torn=[0]; reads=[0]
def reader():
    C=conn(); pkt=enc('MGET',*KEYS)+enc('EXISTS',*KEYS)
    while not stop.is_set():
        C[0].sendall(pkt)
        vals=rr(C[1]); ex=rr(C[1]); reads[0]+=1
        tags=set(v for v in vals if v is not None)
        nil=sum(1 for v in vals if v is None)
        if len(tags)>1 or (0<nil<N): mget_torn[0]+=1     # mixed tags OR partial presence
        exn=int(ex)
        if exn not in (0,N): ex_torn[0]+=1
ts=[threading.Thread(target=wA),threading.Thread(target=wB),threading.Thread(target=reader)]
C=conn(); C[0].sendall(enc('MSET',*[x for k in KEYS for x in (k,b'init')])); rr(C[1])
for t in ts: t.start()
time.sleep(SECS); stop.set()
for t in ts: t.join()
print("reads=%d  mget_torn=%d (%.3f%%)  exists_torn=%d (%.3f%%)"%(
    reads[0], mget_torn[0], 100.0*mget_torn[0]/max(1,reads[0]),
    ex_torn[0], 100.0*ex_torn[0]/max(1,reads[0])))
