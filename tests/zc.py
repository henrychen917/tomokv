#!/usr/bin/env python3
# Borrow-lifetime torture: a slow reader holds a zc send in flight while the value is
# overwritten and DELed under it. The reader must receive the ORIGINAL bytes, intact.
import socket, sys, os, time
HOST, PORT = sys.argv[1], int(sys.argv[2])
def conn(rcvbuf=None):
    s = socket.create_connection((HOST, PORT), timeout=60)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    if rcvbuf: s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    return s
def cmd(*a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str): x = x.encode()
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o
def readn(f, n):
    d = b""
    while len(d) < n:
        c = f.read(n - len(d))
        if not c: raise EOFError
        d += c
    return d
FAIL = 0
w = conn(); wf = w.makefile("rb")
for rnd in range(20):
    val = os.urandom(2 * 1024 * 1024)
    w.sendall(cmd("SET", "zk", val)); assert wf.readline().startswith(b"+OK")
    r = conn(rcvbuf=131072); rf = r.makefile("rb")
    r.sendall(cmd("GET", "zk"))
    hdr = rf.readline()                      # $4194304
    assert hdr == b"$%d\r\n" % len(val), hdr
    part = readn(rf, 64 * 1024)              # take a bite, then stall the socket
    time.sleep(0.05)
    # mutate under the in-flight borrow: overwrite twice, delete, reinsert small
    w.sendall(cmd("SET", "zk", os.urandom(2 * 1024 * 1024))); wf.readline()
    w.sendall(cmd("SET", "zk", b"tiny"));  wf.readline()
    w.sendall(cmd("DEL", "zk"));           wf.readline()
    w.sendall(cmd("SET", "zk", b"after")); wf.readline()
    rest = readn(rf, len(val) - len(part)); readn(rf, 2)
    if part + rest != val:
        print("  FAIL round %d: borrowed bytes corrupted" % rnd); FAIL += 1
    r.close()
w.sendall(cmd("GET", "zk"))
ln = wf.readline(); body = readn(wf, 5 + 2)
if not (ln == b"$5\r\n" and body[:5] == b"after"):
    print("  FAIL final value"); FAIL += 1
w.close()
print("ZC-TORTURE " + ("PASS" if FAIL == 0 else "FAIL %d" % FAIL))
sys.exit(1 if FAIL else 0)
