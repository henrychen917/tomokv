#!/usr/bin/env python3
"""Raw-socket byte comparison of every CODED reply against real Redis 7.4.

The differ gate covers this at scale; this is the small, readable version that names the exact
bytes for each ReplyCode, in RESP2 and RESP3, and asserts a coded reply is followed by exactly one
more reply (the double-reply failure mode).
"""
import socket, subprocess, sys, time

def conn(port, resp3=False):
    s = socket.create_connection(("127.0.0.1", port)); s.settimeout(5)
    if resp3: s.sendall(b"*2\r\n$5\r\nHELLO\r\n$1\r\n3\r\n"); time.sleep(0.2); s.recv(65536)
    return s

def enc(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        b = x.encode() if isinstance(x, str) else x
        out += b"$%d\r\n%s\r\n" % (len(b), b)
    return out

def roundtrip(s, cmds):
    s.sendall(b"".join(enc(*c) for c in cmds))
    time.sleep(0.35)
    buf = b""
    s.setblocking(False)
    try:
        while True:
            d = s.recv(65536)
            if not d: break
            buf += d
    except BlockingIOError: pass
    s.setblocking(True)
    return buf

CASES = [
    ("+OK   (SET)",        [("SET","wc:a","v")]),
    ("+OK   (MSET)",       [("MSET","wc:b","1","wc:c","2")]),
    ("$-1   (GET miss)",   [("GET","wc:missing")]),
    ("+PONG (PING)",       [("PING",)]),
    (":N    (DEL 1)",      [("DEL","wc:a")]),
    (":N    (DEL 8)",      [("DEL","wc:b","wc:c","wc:d","wc:e","wc:f","wc:g","wc:h","wc:i")]),
    (":N    (EXISTS)",     [("EXISTS","wc:zz")]),
    (":N    (SETNX)",      [("SETNX","wc:nx","1")]),
    (":N    (INCR)",       [("INCR","wc:ctr")]),
    (":N    (INCRBY big)", [("INCRBY","wc:big","9000000000")]),
    (":N    (LPUSH)",      [("LPUSH","wc:l","x","y","z")]),
    (":N    (SADD)",       [("SADD","wc:s","p","q")]),
    (":N    (EXPIRE)",     [("EXPIRE","wc:l","100")]),
    (":N    (PERSIST)",    [("PERSIST","wc:l")]),
    ("$0    (empty str)",  [("SET","wc:e",""),("GET","wc:e")]),
    ("*-1   (null array)", [("BLPOP","wc:noexist","0.05")]),
    ("coded then ECHO",    [("SET","wc:z","1"),("ECHO","SENTINEL")]),
    ("coded then error",   [("SET","wc:z","1"),("EXPIRE","wc:z","notanint")]),
    ("pipelined 5 codes",  [("SET","wc:p","1"),("DEL","wc:p"),("PING",),("GET","wc:gone"),("INCR","wc:ctr")]),
]

def run(port, resp3):
    out = []
    for name, cmds in CASES:
        s = conn(port, resp3)
        s.sendall(enc("FLUSHALL")); time.sleep(0.2); s.recv(65536)
        out.append((name, roundtrip(s, cmds)))
        s.close()
    return out

if __name__ == "__main__":
    tp, op = int(sys.argv[1]), int(sys.argv[2])
    bad = 0
    for resp3 in (False, True):
        t = run(tp, resp3); o = run(op, resp3)
        for (n, tb), (_, ob) in zip(t, o):
            tag = "RESP3" if resp3 else "RESP2"
            if tb == ob:
                print("  ok   %-5s %-22s %r" % (tag, n, tb[:60]))
            else:
                bad += 1
                print("  DIFF %-5s %-22s tomokv=%r redis=%r" % (tag, n, tb[:80], ob[:80]))
    print("wirecheck: %d differences" % bad)
    sys.exit(1 if bad else 0)
