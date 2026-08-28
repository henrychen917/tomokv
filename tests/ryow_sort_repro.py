import socket, random, sys
PORT=int(sys.argv[1])
def enc(*a):
    out=b"*%d\r\n"%len(a)
    for x in a:
        b=x.encode() if isinstance(x,str) else x
        out+=b"$%d\r\n"%len(b)+b+b"\r\n"
    return out
s=socket.create_connection(("127.0.0.1",PORT)); s.settimeout(15); buf=b""
def rd():
    global buf
    while b"\r\n" not in buf: buf+=s.recv(65536)
    i=buf.index(b"\r\n"); line=buf[:i]; buf=buf[i+2:]
    t=line[:1]
    if t in b"+-:": return line
    if t==b"$":
        n=int(line[1:])
        if n<0: return None
        while len(buf)<n+2: buf+=s.recv(65536)
        v=buf[:n]; buf=buf[n+2:]; return v
    if t==b"*":
        n=int(line[1:]); return [rd() for _ in range(n)]
def cmd(*a): s.sendall(enc(*a)); return rd()
rng=random.Random(5); bad=0
for trial in range(20):
    els=[str(i) for i in range(10)]
    old={e: rng.randint(0,99) for e in els}; new={e: rng.randint(0,99) for e in els}
    cmd("DEL","s:mr"); cmd("RPUSH","s:mr",*els)
    setup=[]
    for e in els: setup += ["s:mrw_%s"%e, str(old[e])]
    cmd("MSET",*setup)
    want=[e.encode() for e in sorted(els,key=lambda e:(new[e],e.encode()))]
    pairs=[]
    for e in els: pairs += ["s:mrw_%s"%e, str(new[e])]
    cmd("MULTI"); cmd("MSET",*pairs); cmd("SORT","s:mr","BY","s:mrw_*")
    if cmd("EXEC")[1]!=want: bad+=1
print(f"{bad}/20 mismatched")
