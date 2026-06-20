import socket,sys,time
keys=[l.strip() for l in open("/tmp/hot.txt") if l.strip()]
dur=float(sys.argv[1]); s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb")
n=len(keys); i=0; B=64; t0=time.time()
while time.time()-t0<dur:
    buf=bytearray()
    for _ in range(B):
        k=keys[i%n].encode(); i+=1; buf+=b"*2\r\n$8\r\nBITCOUNT\r\n$%d\r\n%s\r\n"%(len(k),k)
    f.write(buf); f.flush()
    for _ in range(B): f.readline()
