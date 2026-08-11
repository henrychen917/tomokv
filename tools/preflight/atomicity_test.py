#!/usr/bin/env python3
# Cross-shard MSET atomicity discriminator. Two writers hammer the SAME key set with distinct tags
# (writer A sets every key to "AAAA...", writer B to "BBBB..."); a reader continuously MGETs.
# Expected, by design:
#   base (no atomicity):    final state can be MIXED (some A, some B) + reader sees torn snapshots
#   writer-side intent lock: final state all-same (writes don't interleave) BUT reader can still tear
#   epoch drain-fence:       final all-same AND reader never tears (workers fenced during the write)
# Usage: atomicity_test.py PORT SECONDS NKEYS
import socket,sys,threading,time
PORT=int(sys.argv[1]); SECS=float(sys.argv[2]) if len(sys.argv)>2 else 4; NK=int(sys.argv[3]) if len(sys.argv)>3 else 8
KEYS=['atomk:%d'%i for i in range(NK)]
def conn():
    s=socket.create_connection(('127.0.0.1',PORT)); s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1); return s,s.makefile('rb')
def enc(*a): return b'*%d\r\n'%len(a)+b''.join(b'$%d\r\n'%len(x if isinstance(x,bytes) else str(x).encode())+(x if isinstance(x,bytes) else str(x).encode())+b'\r\n' for x in a)
def rr(f):
    ln=f.readline(); t=ln[:1]
    if t==b'$':
        n=int(ln[1:]); return None if n<0 else f.read(n+2)[:-2]
    if t==b'*':
        n=int(ln[1:]); return None if n<0 else [rr(f) for _ in range(n)]
    return ln[1:].strip()
stop=threading.Event()
def writer(tag):
    C=conn(); val=(tag*8).encode()
    args=['MSET']
    for k in KEYS: args += [k,val]
    pkt=enc(*args)
    while not stop.is_set():
        C[0].sendall(pkt); rr(C[1])
tear=[0]; reads=[0]
def reader():
    C=conn(); mg=enc('MGET',*KEYS)
    while not stop.is_set():
        C[0].sendall(mg); vals=rr(C[1]); reads[0]+=1
        tags=set(v[:1] for v in vals if v)
        if len(tags)>1: tear[0]+=1     # saw a mix of A and B in one MGET snapshot => torn read
C=conn()
for k in KEYS: cmdp=enc('SET',k,b'init'); C[0].sendall(cmdp); rr(C[1])
ts=[threading.Thread(target=writer,args=('A',)),threading.Thread(target=writer,args=('B',)),threading.Thread(target=reader)]
for t in ts: t.start()
time.sleep(SECS); stop.set()
for t in ts: t.join()
# final consistency: after writers stop, the last committed MSET should have left ALL keys one tag
final=rr((lambda c:(c[0].sendall(enc('MGET',*KEYS)),c[1])[1])(C))
ftags=set(v[:1] for v in final if v)
print("reads=%d  torn_reads=%d (%.3f%%)  final_state=%s  final_tags=%s"%(
    reads[0],tear[0], 100.0*tear[0]/max(1,reads[0]),
    "ALL-SAME (write-atomic)" if len(ftags)==1 else "MIXED (writes interleaved!)",
    sorted(t.decode() for t in ftags)))
