import socket,sys
import os,sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import keys as K
ks=K.keys_for_worker(2,5000,W=8); open("/tmp/hot.txt","w").write("\n".join(ks))
s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb"); v=("x"*256).encode(); buf=bytearray()
for k in ks:
    kk=k.encode(); buf+=b"*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n"%(len(kk),kk,len(v),v)
f.write(buf); f.flush()
ok=sum(1 for _ in ks if f.readline().startswith(b"+")); print("placed %d keys on worker 2 (256B)"%ok)
