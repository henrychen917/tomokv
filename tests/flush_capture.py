import socket, sys, time
PORT=int(sys.argv[1]); MODE=sys.argv[2]
s=socket.create_connection(("127.0.0.1",PORT),timeout=30); f=s.makefile("rb")
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
def info(fld):
    for ln in cmd("INFO").split(b"\r\n"):
        if ln.startswith(fld.encode()+b":"): return ln.split(b":",1)[1]
N=100000; V="x"*950
if MODE=="run":
    for i in range(0,N,500):
        s.sendall(b"".join(enc(["SET","fk:%d"%j,V]) for j in range(i,i+500)))
        for _ in range(500): rr()
    print("BGSAVE:", cmd("BGSAVE"))
    print("FLUSHALL mid-capture:", cmd("FLUSHALL"))   # immediately, while capture runs
    print("DBSIZE post-flush:", cmd("DBSIZE"))
    t0=time.time()
    while info("rdb_bgsave_in_progress")!=b"0" and time.time()-t0<120: time.sleep(0.1)
    print("capture done %.1fs; preimages=%s" % (time.time()-t0, info("snapshot_preimages").decode()))
    print("live still empty:", cmd("DBSIZE"), cmd("PING"))
elif MODE=="verify":
    bad = sum(1 for j in range(0,N,997) if cmd("GET","fk:%d"%j) != V.encode())
    d = cmd("DBSIZE")
    print("loaded dump: dbsize=%s sampled-bad=%d" % (d, bad))
    print("FLUSH-CAPTURE", "PASS" if bad==0 and d==b":%d"%N else "FAIL")
    sys.exit(1 if bad or d!=b":%d"%N else 0)
