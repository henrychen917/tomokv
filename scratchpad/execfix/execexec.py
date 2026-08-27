"""Second pass: does the losing transaction have to span MORE THAN ONE shard?"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resp import Conn, encode

HOST = "127.0.0.1"
TP, OP_ = int(sys.argv[1]), int(sys.argv[2])
TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 80
V96 = "value-" + "y" * 90
V95 = "z" * 95
V97 = "z" * 97


def fresh():
    a, b = Conn(HOST, TP), Conn(HOST, OP_)
    for c, name in ((a, "target"), (b, "oracle")):
        if c.cmd("PING") != b"PONG":
            raise SystemExit("%s not answering PING" % name)
    return a, b


t, o = fresh()
# The oracle is long-lived across runs while a freshly booted target is empty; residue there makes
# every key-creating op diff from op 0.  Clean both.
t.cmd("FLUSHALL"), o.cmd("FLUSHALL")


def run(conn, ops):
    conn.sock.sendall(b"".join(encode(*x) for x in ops))
    return [conn.read() for _ in ops]


def probe(k):
    return [["LLEN", k], ["LRANGE", k, "0", "-1"]]


def shapes(k, k2):
    return {
        "T1{k} T2{k}":
            [["MULTI"], ["RPUSH", k, V96, V95], ["EXEC"],
             ["MULTI"], ["RPUSH", k, "hello", V97], ["EXEC"]] + probe(k),
        "T1{k2,k} T2{k}":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, V96, V95], ["EXEC"],
             ["MULTI"], ["RPUSH", k, "hello", V97], ["EXEC"]] + probe(k),
        "T1{k,k2} T2{k}":
            [["MULTI"], ["RPUSH", k, V96, V95], ["LTRIM", k2, "-2", "-1"], ["EXEC"],
             ["MULTI"], ["RPUSH", k, "hello", V97], ["EXEC"]] + probe(k),
        "T1{k2,k} T2{k2,k}":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, V96, V95], ["EXEC"],
             ["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, "hello", V97], ["EXEC"]] + probe(k),
        "T1{k2,k} only":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, V96, V95], ["EXEC"]] + probe(k),
        "T1{k2,k} T2{k} short values":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, "a", "b"], ["EXEC"],
             ["MULTI"], ["RPUSH", k, "c", "d"], ["EXEC"]] + probe(k),
        "T1{k2,k} T2{k} single elem":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, "a"], ["EXEC"],
             ["MULTI"], ["RPUSH", k, "b"], ["EXEC"]] + probe(k),
        "T1{k2,k} T2{k} SET/GET":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["SET", k, "a"], ["EXEC"],
             ["MULTI"], ["APPEND", k, "b"], ["EXEC"], ["GET", k]],
        "T1{k2,k} T2{k} hash":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["HSET", k, "f1", "a"], ["EXEC"],
             ["MULTI"], ["HSET", k, "f2", "b"], ["EXEC"], ["HLEN", k]],
        "T1{k2,k} T2{k} bare write after":
            [["MULTI"], ["LTRIM", k2, "-2", "-1"], ["RPUSH", k, "a"], ["EXEC"],
             ["RPUSH", k, "b"]] + probe(k),
    }


names = list(shapes("x", "y").keys())
counts = {n: 0 for n in names}
firsts = {}
for trial in range(TRIALS):
    for name in names:
        tag = "".join(ch for ch in name if ch.isalnum())[:10]
        k, k2 = "e2%s_%d" % (tag, trial), "e2%s_%d_o" % (tag, trial)
        ops = [["DEL", k], ["DEL", k2]] + shapes(k, k2)[name]
        a, b = run(t, ops), run(o, ops)
        if a != b:
            counts[name] += 1
            if name not in firsts:
                firsts[name] = [(i, ops[i][0], a[i], b[i]) for i in range(len(ops)) if a[i] != b[i]]
for name in names:
    print("%-34s lost %3d/%d %s" % (name, counts[name], TRIALS,
                                    ("  e.g. " + repr(firsts[name][:1])[:130]) if name in firsts else ""))
