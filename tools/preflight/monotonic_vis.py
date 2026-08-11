#!/usr/bin/env python3
# Does MSET2 ever become visible before MSET1 (same client, same keys)? Writers pipeline a STREAM of
# MSETs stamping all N keys with a strictly-increasing counter (deep pipeline => many in-flight at
# once, so completion order maximally diverges from dispatch order — the hardest case for R1).
# Readers continuously MGET; a violation = the observed counter DECREASED (visibility rolled back =>
# a later-issued MSET jumped ahead of an earlier one) OR a torn snapshot (keys show >1 counter).
# Usage: monotonic_vis.py PORT SECS NKEYS NWRITERS
import socket,sys,threading,time
PORT=int(sys.argv[1]); SECS=float(sys.argv[2]) if len(sys.argv)>2 else 6
N=int(sys.argv[3]) if len(sys.argv)>3 else 8; NW=int(sys.argv[4]) if len(sys.argv)>4 else 1
KEYS=['mv:%d'%i for i in range(N)]; PIPE=32
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
# each writer owns a disjoint high-bit range so its counters are globally monotone per-writer; the
# reader tracks per-writer last-seen (a key's value = "<writer>:<counter>").
def writer(wid):
    C=conn(); ctr=0
    while not stop.is_set():
        pkt=b'';
        for _ in range(PIPE):
            tag=b'%d:%d'%(wid,ctr); ctr+=1
            pkt+=enc('MSET',*[x for k in KEYS for x in (k,tag)])
        C[0].sendall(pkt)
        for _ in range(PIPE): rr(C[1])
back=[0]; torn=[0]; reads=[0]
def reader():
    C=conn(); mg=enc('MGET',*KEYS); last={}
    while not stop.is_set():
        C[0].sendall(mg); vals=rr(C[1]); reads[0]+=1
        tags=set(v for v in vals if v is not None)
        if len(tags)>1: torn[0]+=1; continue
        if not tags: continue
        v=tags.pop().decode(); w,c=v.split(':'); c=int(c)
        if w in last and c<last[w]: back[0]+=1   # visibility rolled BACKWARD for this writer
        last[w]=max(last.get(w,-1),c)
# seed
C=conn(); C[0].sendall(enc('MSET',*[x for k in KEYS for x in (k,b'0:0')])); rr(C[1])
ts=[threading.Thread(target=writer,args=(w,)) for w in range(NW)]+[threading.Thread(target=reader) for _ in range(2)]
for t in ts: t.start()
time.sleep(SECS); stop.set()
for t in ts: t.join()
print("reads=%d  visibility_rollbacks=%d (%.4f%%)  torn=%d (%.4f%%)"%(
    reads[0], back[0], 100.0*back[0]/max(1,reads[0]), torn[0], 100.0*torn[0]/max(1,reads[0])))
