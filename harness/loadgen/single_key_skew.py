import socket, sys, time, threading

PORT = 7800
def conn():
    s = socket.create_connection(("127.0.0.1", PORT)); return s, s.makefile("rwb")
def send(f, *a):
    f.write(("*%d\r\n" % len(a)).encode())
    for x in a:
        x = str(x).encode(); f.write(b"$%d\r\n" % len(x)); f.write(x); f.write(b"\r\n")
def readreply(f):
    line = f.readline(); t = line[:1]
    if t in (b'+', b'-', b':'): return line[1:].strip()
    if t == b'$':
        n = int(line[1:])
        if n < 0: return None
        d = f.read(n); f.read(2); return d
    if t == b'*':
        n = int(line[1:]); return [readreply(f) for _ in range(n)]
    return line

# seed a handful of distinct hot keys (each on whatever worker owns it)
HOT = ["hotA", "hotB", "hotC"]
s, f = conn()
for k in HOT: send(f, "SET", k, "x"*2048)
f.flush()
for k in HOT: readreply(f)
s.close()

stop = False
def hammer(key):
    s2, f2 = conn()
    B = 512
    while not stop:
        for _ in range(B): send(f2, "GET", key)
        f2.flush()
        for _ in range(B): readreply(f2)
    s2.close()

# many connections all hammering the SAME small set of keys -> heavy skew onto a few workers
threads = [threading.Thread(target=hammer, args=(HOT[i % len(HOT)],)) for i in range(6)]
for t in threads: t.start()
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 15)
stop = True
for t in threads: t.join()
print("hammer done")
