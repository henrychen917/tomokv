#!/usr/bin/env python3
"""Which source does redis accumulate FIRST?  Every weight is 0, so each source contributes
+-0 whose sign is the sign of its stored score.  AGGREGATE MAX/MIN keep the incumbent on a tie,
so the printed sign of member 'm' names the source processed first."""
import socket, sys

def conn(p):
    s = socket.create_connection(("127.0.0.1", p), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")

def enc(a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str): x = x.encode()
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o

def rd(f):
    l = f.readline(); t = l[:1]
    if t in b"+-:,_#(": return l
    if t in (b"$", b"=", b"!"):
        n = int(l[1:-2]); return None if n == -1 else f.read(n + 2)[:-2]
    if t in (b"*", b"~", b">"):
        n = int(l[1:-2]); return None if n == -1 else [rd(f) for _ in range(n)]
    raise RuntimeError(l)

T = conn(7021); O = conn(7022)

def q(side, cmd):
    s, f = side; s.sendall(enc(cmd)); return rd(f)

def mscore(side, cmd):
    reply = q(side, cmd)
    if not isinstance(reply, list): return reply
    for i in range(0, len(reply), 2):
        if reply[i] == b"m": return reply[i + 1]
    return b"<absent>"

def mkzset(side, key, card, negative):
    q(side, ["DEL", key])
    q(side, ["ZADD", key, "-5" if negative else "5", "m"])
    for i in range(2, card + 1):
        q(side, ["ZADD", key, "1", f"{key}f{i}"])

def mkset(side, key, card, _neg):
    q(side, ["DEL", key])
    q(side, ["SADD", key, "m"])
    for i in range(2, card + 1):
        q(side, ["SADD", key, f"{key}f{i}"])

CASES = []
def case(label, build, cmd):
    CASES.append((label, build, cmd))

# (name, cardinality, negative-score)
def B(*specs):
    def build(side):
        for name, card, neg in specs:
            mkzset(side, name, card, neg)
    return build

case("card 1(+) vs 4(-)   argv=[P1,N4]", B(("P1",1,False),("N4",4,True)),
     ["ZUNION","2","P1","N4","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 1(+) vs 4(-)   argv=[N4,P1]", B(("P1",1,False),("N4",4,True)),
     ["ZUNION","2","N4","P1","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 1(-) vs 4(+)   argv=[N1,P4]", B(("N1",1,True),("P4",4,False)),
     ["ZUNION","2","N1","P4","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 1(-) vs 4(+)   argv=[P4,N1]", B(("N1",1,True),("P4",4,False)),
     ["ZUNION","2","P4","N1","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 5(-),1(+),3(-) argv=[N5,P1,N3]", B(("N5",5,True),("P1",1,False),("N3",3,True)),
     ["ZUNION","3","N5","P1","N3","WEIGHTS","0","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 5(+),1(-),3(+) argv=[P5,N1,P3]", B(("P5",5,False),("N1",1,True),("P3",3,False)),
     ["ZUNION","3","P5","N1","P3","WEIGHTS","0","0","0","AGGREGATE","MAX","WITHSCORES"])
case("card 5(+),1(-),3(+) argv=[P3,P5,N1]", B(("P5",5,False),("N1",1,True),("P3",3,False)),
     ["ZUNION","3","P3","P5","N1","WEIGHTS","0","0","0","AGGREGATE","MAX","WITHSCORES"])
case("equal card 3(-) 3(+) argv=[Na,Pb]", B(("Na",3,True),("Pb",3,False)),
     ["ZUNION","2","Na","Pb","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("equal card 3(+) 3(-) argv=[Pb,Na]", B(("Na",3,True),("Pb",3,False)),
     ["ZUNION","2","Pb","Na","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("equal card 1(-) 1(+) argv=[Na,Pb]", B(("Na",1,True),("Pb",1,False)),
     ["ZUNION","2","Na","Pb","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("equal card 1(+) 1(-) argv=[Pb,Na]", B(("Na",1,True),("Pb",1,False)),
     ["ZUNION","2","Pb","Na","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("MIN card 1(+) vs 4(-) argv=[N4,P1]", B(("P1",1,False),("N4",4,True)),
     ["ZUNION","2","N4","P1","WEIGHTS","0","0","AGGREGATE","MIN","WITHSCORES"])
case("ZINTER card 5(-) vs 1(+) argv=[N5,P1]", B(("N5",5,True),("P1",1,False)),
     ["ZINTER","2","N5","P1","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("ZINTER card 5(+) vs 1(-) argv=[P5,N1]", B(("P5",5,False),("N1",1,True)),
     ["ZINTER","2","P5","N1","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("ZDIFF  card 5(-) vs 1  argv=[N5,other]", B(("N5",5,True),("O1",1,False)),
     ["ZDIFF","2","N5","Oz","WITHSCORES"])

# a SET source (implicit 1.0, always positive) mixed with a bigger negative zset
def build_mixed(side):
    mkzset(side, "N5", 5, True)
    mkset(side, "S1", 1, False)
case("SET card1 vs zset card5(-) argv=[N5,S1]", build_mixed,
     ["ZUNION","2","N5","S1","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])
case("SET card1 vs zset card5(-) argv=[S1,N5]", build_mixed,
     ["ZUNION","2","S1","N5","WEIGHTS","0","0","AGGREGATE","MAX","WITHSCORES"])

print("%-46s | %-10s | %-10s | %s" % ("probe (sign names the FIRST-accumulated source)",
                                      "tomokv", "redis 7.4", ""))
print("-" * 92)
bad = 0
for label, build, cmd in CASES:
    for side in (T, O):
        q(side, ["FLUSHALL"]); build(side)
    a, b = mscore(T, cmd), mscore(O, cmd)
    if a != b: bad += 1
    print("%-46s | %-10s | %-10s | %s" % (label, a, b, "" if a == b else "DIFF"))
print("\n%d/%d cells diverge" % (bad, len(CASES)))
