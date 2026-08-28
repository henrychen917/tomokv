import socket, sys
PORT=int(sys.argv[1]); N=int(sys.argv[2]) if len(sys.argv)>2 else 16384
def enc(*a):
    out=b"*%d\r\n"%len(a)
    for x in a:
        b=x.encode() if isinstance(x,str) else x
        out+=b"$%d\r\n"%len(b)+b+b"\r\n"
    return out
big=b"A"*N
# setup connection
c=socket.create_connection(("127.0.0.1",PORT)); c.settimeout(10)
c.sendall(enc("HELLO","3")); 
import time; time.sleep(0.3); c.recv(65536)
c.sendall(enc("SET","big",big)); time.sleep(0.2); c.recv(65536)
c.sendall(enc("SUBSCRIBE","ch")); time.sleep(0.3); c.recv(65536)
# THE PROBE: publish (delivers to self) and GET the borrowed value in ONE write
c.sendall(enc("PUBLISH","ch","hello")+enc("GET","big"))
time.sleep(0.8)
data=b""
c.settimeout(2)
try:
    while True:
        b=c.recv(1<<20)
        if not b: break
        data+=b
except socket.timeout: pass
# find the GET bulk header and verify the next N bytes are the value
idx=data.find(b"$%d\r\n"%N)
if idx<0:
    print("  NO BULK HEADER FOUND -- raw head:", data[:120]); sys.exit(1)
body=data[idx+len(b"$%d\r\n"%N):idx+len(b"$%d\r\n"%N)+N]
ok = body==big
print(f"  bulk header at offset {idx}")
print(f"  {N} bytes after header are the value: {ok}")
if not ok:
    print(f"  INTERLEAVED instead: {body[:100]!r}")
    print("  >>> TORN: a push frame is spliced between the bulk header and the body")
else:
    print("  >>> intact")
