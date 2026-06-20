import socket,sys
import os,sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import keys as K
T=int(sys.argv[1]); N=int(sys.argv[2])
keys=K.keys_for_worker(T,N)
open("/tmp/hot.txt","w").write("\n".join(keys))
s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb")
def send(*a):
    f.write(("*%d\r\n"%len(a)).encode())
    for x in a: x=str(x).encode(); f.write(b"$%d\r\n"%len(x)); f.write(x); f.write(b"\r\n")
    f.flush()
buf=bytearray()
for k in keys:
    kk=k.encode(); v=("hv_"+k).encode()
    buf+=b"*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n"%(len(kk),kk,len(v),v)
f.write(buf); f.flush()
ok=0
for k in keys:
    if f.readline().startswith(b"+"): ok+=1
print("placed %d/%d keys on worker %d"%(ok,len(keys),T))
