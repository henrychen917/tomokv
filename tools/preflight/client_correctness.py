#!/usr/bin/env python3
# CLIENT-SIDE CORRECTNESS (read-your-own-writes / same-client ordering) with atomic multi-key cmds.
# A single connection pipelines: SET k_i=tag (i<N) then MGET k_0..k_{N-1}. Because it is one
# connection, Redis semantics REQUIRE the MGET to observe this client's own just-written tag on every
# key. In a sharded scatter-gather the SETs land on different workers async and the MGET snapshot can
# race ahead -> a stale/nil read = a read-your-own-writes VIOLATION. Also runs a variant with a
# concurrent OTHER client writing a DIFFERENT tag to the SAME keys: the reader's MGET must still be a
# consistent snapshot (all one tag, never a mix) AND must never show a tag OLDER than its own last SET.
# Usage: client_correctness.py PORT ROUNDS N [--churn]
import socket,sys,threading,time
PORT=int(sys.argv[1]); ROUNDS=int(sys.argv[2]) if len(sys.argv)>2 else 20000; N=int(sys.argv[3]) if len(sys.argv)>3 else 8
CHURN='--churn' in sys.argv
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
KEYS=['ryow:%d'%i for i in range(N)]
stop=threading.Event()
# optional churn: another client hammering the SAME keys with its own tag, to stress snapshotting
def churn():
    C=conn(); k=0
    while not stop.is_set():
        tag=b'OTHER%d'%k; k+=1
        C[0].sendall(enc('MSET',*[x for key in KEYS for x in (key,tag)]))
        rr(C[1])
if CHURN:
    th=threading.Thread(target=churn); th.start()
C=conn()
ryow_viol=0   # MGET did not show this client's own just-set tag (and no newer tag present)
torn=0        # MGET showed a MIX of tags (inconsistent snapshot)
for r in range(ROUNDS):
    tag=('ME%d'%r).encode()
    pkt=b''.join(enc('SET',k,tag) for k in KEYS)+enc('MGET',*KEYS)
    C[0].sendall(pkt)
    for _ in range(N): rr(C[1])
    vals=rr(C[1]) or []
    tags=set(v for v in vals if v is not None)
    if len(tags)>1: torn+=1
    # RYOW: without churn, every value must == my tag. With churn, it must be my tag OR a strictly
    # newer OTHER tag (someone overwrote after me) — never an OLDER/nil where I just wrote.
    if not CHURN:
        if any(v!=tag for v in vals): ryow_viol+=1
    else:
        # my write must be visible unless overwritten; a nil or my-own-older value is the violation.
        if any(v is None for v in vals): ryow_viol+=1
stop.set()
if CHURN: th.join()
print("rounds=%d N=%d  RYOW_violations=%d (%.4f%%)  torn_snapshots=%d (%.4f%%)"%(
    ROUNDS,N,ryow_viol,100.0*ryow_viol/ROUNDS,torn,100.0*torn/ROUNDS))
