import socket,sys,time
keys=[l.strip() for l in open("/tmp/hot.txt") if l.strip()]
dur=float(sys.argv[1]); s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb")
n=len(keys); i=0; ops=0; B=256; t0=time.time()
def rd():
    l=f.readline()
    if l[:1]==b'$':
        m=int(l[1:])
        if m>=0: f.read(m); f.read(2)
while time.time()-t0<dur:
    buf=bytearray()
    for _ in range(B):
        k=keys[i%n].encode(); i+=1
        buf+=b"*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n"%(len(k),k)
    f.write(buf); f.flush()
    for _ in range(B): rd()
    ops+=B
print("%.0f"%(ops/(time.time()-t0)))
