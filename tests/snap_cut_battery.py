import socket, sys, time, random
PORT = int(sys.argv[1]); MODE = sys.argv[2]   # save | verify
def conn(p=None):
    s = socket.create_connection(("127.0.0.1", p or PORT), timeout=20); return s, s.makefile("rb")
def enc(a):
    o=b"*%d\r\n"%len(a)
    for x in a:
        x=x.encode() if isinstance(x,str) else x
        o+=b"$%d\r\n"%len(x)+x+b"\r\n"
    return o
def rr(f):
    line=f.readline()
    if not line: raise EOFError
    t=line[:1]
    if t in b"+-:": return line.strip()
    if t==b"$":
        n=int(line[1:-2]); return None if n==-1 else f.read(n+2)[:-2]
    n=int(line[1:-2]); return [rr(f) for _ in range(n)]
s, f = conn()
def cmd(*a): s.sendall(enc(list(a))); return rr(f)
def info_field(name):
    t = cmd("INFO")
    for ln in t.split(b"\r\n"):
        if ln.startswith(name.encode()+b":"): return ln.split(b":",1)[1]
    return None
rng = random.Random(11)
KEYS = [("pk:%d"%i, "val-%d-%s"%(i, "x"*rng.randrange(0,200))) for i in range(6000)]
TTLK = [("tk:%d"%i, "tval%d"%i) for i in range(500)]
if MODE == "save":
    B=400
    for i in range(0, len(KEYS), B):
        s.sendall(b"".join(enc(["SET",k,v]) for k,v in KEYS[i:i+B]))
        for _ in range(min(B,len(KEYS)-i)): rr(f)
    for k,v in TTLK:
        s.sendall(enc(["SET",k,v,"EX","5000"]))
    for _ in TTLK: rr(f)
    # short-TTL keys that expire BEFORE the cut: must be absent from dump
    for i in range(50):
        s.sendall(enc(["SET","gone:%d"%i,"g","PX","150"]))
    for _ in range(50): rr(f)
    time.sleep(0.5)
    print("BGSAVE:", cmd("BGSAVE"))
    # mutations begin only after the BGSAVE reply => ALL are post-cut. The dump must show none.
    m, fm = conn()
    def mc(*a): m.sendall(enc(list(a))); return rr(fm)
    for i in range(0, 6000, 2): mc("SET", "pk:%d"%i, "MUTATED-%d"%i)
    for i in range(100): mc("DEL", "pk:%d"%(i*3+1))
    for i in range(800): mc("SET", "post:%d"%i, "newkey%d"%i)
    t0=time.time()
    while info_field("rdb_bgsave_in_progress") != b"0" and time.time()-t0 < 90: time.sleep(0.2)
    print("bgsave done in %.1fs (mutation storm raced the capture)" % (time.time()-t0))
    print("last_save_time:", info_field("last_save_time"))
elif MODE == "verify_cut":
    # the dump is the state at the cut: every original pk value, no MUTATED, no post:*, no gone:*
    bad=0; first=None
    for k, v in KEYS:
        got = cmd("GET", k)
        if got != v.encode():
            bad+=1
            if first is None: first=(k, v[:24], got[:24] if got else got)
    ttl_ok = sum(1 for k,_ in TTLK[:50] if (lambda t: t!=b":-2" and int(t[1:])>4000)(cmd("TTL",k)))
    post = sum(1 for i in range(800) if cmd("GET","post:%d"%i) is not None)
    gone = sum(1 for i in range(50) if cmd("GET","gone:%d"%i) is not None)
    print("cut verify: mismatch=%d (first=%s) ttl=%d/50 post-cut-leaked=%d pre-cut-expired=%d"
          % (bad, first, ttl_ok, post, gone))
    ok = bad==0 and ttl_ok==50 and post==0 and gone==0
    print("VERIFY_CUT", "PASS" if ok else "FAIL")
    if ok: print("SAVE-on-loaded:", cmd("SAVE"))
    sys.exit(0 if ok else 1)
elif MODE == "verify_save":
    bad = sum(1 for k,v in KEYS[::137] if cmd("GET",k) != v.encode())
    print("VERIFY_SAVE", "PASS" if bad==0 else "FAIL (%d)"%bad)
    sys.exit(0 if bad else 1)
