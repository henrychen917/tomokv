#!/usr/bin/env python3
# MSETNX all-or-nothing discriminator (broadened epoch).
# Phase 1 (concurrent): two writers hammer MSETNX over the SAME N keys with distinct tags; a resetter
#   atomically DELs all N to re-arm; a reader MGETs continuously. Invariant (atomic ON): every MGET
#   snapshot is ALL-nil or ALL-one-tag — a mix means a torn MSETNX (partial conditional write) or a
#   torn DEL. Also count writer successes (reply 1) as a liveness signal (must be > 0).
# Phase 2 (serial semantics): DEL all -> MSETNX(tagX) must reply 1 and set ALL; MSETNX(tagY) must
#   reply 0 and change NOTHING; DEL one key -> MSETNX(tagY) must still reply 0 (one key remains).
# Usage: msetnx_race.py PORT SECS NKEYS
import socket, sys, threading, time
PORT=int(sys.argv[1]); SECS=float(sys.argv[2]) if len(sys.argv)>2 else 6; N=int(sys.argv[3]) if len(sys.argv)>3 else 8
KEYS=['mnx:%d'%i for i in range(N)]
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
stop=threading.Event(); wins=[0,0]
def writer(i, tagc):
    C=conn(); r=0
    while not stop.is_set():
        tag=b'%s%d'%(tagc,r); r+=1
        C[0].sendall(enc('MSETNX',*[x for k in KEYS for x in (k,tag)]))
        if rr(C[1])==b'1': wins[i]+=1
def resetter():
    C=conn(); d=enc('DEL',*KEYS)
    while not stop.is_set():
        C[0].sendall(d); rr(C[1]); time.sleep(0.002)
torn=[0]; reads=[0]
def reader():
    C=conn(); pkt=enc('MGET',*KEYS)
    while not stop.is_set():
        C[0].sendall(pkt); vals=rr(C[1]); reads[0]+=1
        tags=set(v for v in vals if v is not None); nil=sum(1 for v in vals if v is None)
        if len(tags)>1 or (0<nil<N): torn[0]+=1
ts=[threading.Thread(target=writer,args=(0,b'P')),threading.Thread(target=writer,args=(1,b'Q')),
    threading.Thread(target=resetter),threading.Thread(target=reader)]
for t in ts: t.start()
time.sleep(SECS); stop.set()
for t in ts: t.join()
# Phase 2: serial semantics
C=conn()
def cmd(*a): C[0].sendall(enc(*a)); return rr(C[1])
cmd('DEL',*KEYS)
ok1 = cmd('MSETNX',*[x for k in KEYS for x in (k,b'X')])
allX = all(v==b'X' for v in cmd('MGET',*KEYS))
ok0 = cmd('MSETNX',*[x for k in KEYS for x in (k,b'Y')])
stillX = all(v==b'X' for v in cmd('MGET',*KEYS))
cmd('DEL',KEYS[0])
ok0b = cmd('MSETNX',*[x for k in KEYS for x in (k,b'Y')])
k0_still_nil = cmd('MGET',KEYS[0])[0] is None
serial_ok = (ok1==b'1' and allX and ok0==b'0' and stillX and ok0b==b'0' and k0_still_nil)
print("reads=%d  torn=%d (%.3f%%)  wins=P:%d Q:%d  serial=%s"%(
    reads[0], torn[0], 100.0*torn[0]/max(1,reads[0]), wins[0], wins[1],
    "OK" if serial_ok else "FAIL(1:%s allX:%s 0:%s keep:%s 0b:%s nil0:%s)"%(ok1,allX,ok0,stillX,ok0b,k0_still_nil)))
