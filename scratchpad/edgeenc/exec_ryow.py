"""Minimal reproducers for the EXEC read-your-own-write loss.

BOOT THE TARGET WITH --atomic 1.  At --atomic 0 every row here reports 0, which is the negative
control, NOT a fix -- the probe prints the target's live `atomic` setting so a run can never be
mistaken for the other mode.  See NOTES-EDGEENC.md section 4.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resp import Conn, encode

HOST = "127.0.0.1"
TP, OP_ = int(sys.argv[1]), int(sys.argv[2])
TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 200
t, o = Conn(HOST, TP), Conn(HOST, OP_)
MODE = t.cmd("CONFIG", "GET", "atomic")
MODE = MODE[1].decode() if isinstance(MODE, list) and len(MODE) == 2 else "?"
print("target %s:%d is running --atomic %s   (every row below is 0 at --atomic 0)"
      % (HOST, TP, MODE))


def pipe(conn, ops):
    conn.sock.sendall(b"".join(encode(*x) for x in ops))
    return [conn.read() for _ in ops]


def seqrun(conn, ops):
    return [conn.cmd(*x) for x in ops]


def build_msetmget(tag, trial, nkeys=5):
    keys = ["%s%d_%d" % (tag, trial, i) for i in range(nkeys)]
    pairs = [x for i, k in enumerate(keys) for x in (k, chr(97 + i))]
    return [["DEL"] + keys, ["MULTI"], ["MSET"] + pairs, ["MGET"] + keys, ["EXEC"],
            ["MGET"] + keys, ["DEL"] + keys]


def build_setget(tag, trial):
    k = "%s%d" % (tag, trial)
    return [["DEL", k], ["MULTI"], ["SET", k, "v"], ["GET", k], ["EXEC"], ["GET", k],
            ["DEL", k]]


def build_group_then_setget(tag, trial):
    k = "%s%d" % (tag, trial)
    return [["DEL", k, k + "@x"], ["MULTI"], ["SET", k, "v"], ["GET", k], ["EXEC"],
            ["GET", k], ["DEL", k]]


def build_msetmget_nodel(tag, trial, nkeys=5):
    keys = ["%s%d_%d" % (tag, trial, i) for i in range(nkeys)]
    pairs = [x for i, k in enumerate(keys) for x in (k, chr(97 + i))]
    return [["MULTI"], ["MSET"] + pairs, ["MGET"] + keys, ["EXEC"], ["MGET"] + keys]


def build_msetmget2(tag, trial):
    return build_msetmget(tag, trial, 2)


CASES = [
    ("R0 MULTI{MSET5,MGET5} nodel pipelined", build_msetmget_nodel, pipe),
    ("R0 MULTI{MSET5,MGET5} nodel sequential", build_msetmget_nodel, seqrun),
    ("R1b MULTI{MSET2,MGET2}    pipelined", build_msetmget2, pipe),
    ("R1 MULTI{MSET5,MGET5}     pipelined", build_msetmget, pipe),
    ("R1 MULTI{MSET5,MGET5}     sequential", build_msetmget, seqrun),
    ("R2 MULTI{SET,GET}         pipelined", build_setget, pipe),
    ("R2 MULTI{SET,GET}         sequential", build_setget, seqrun),
    ("R3 DEL2;MULTI{SET,GET}    pipelined", build_group_then_setget, pipe),
    ("R3 DEL2;MULTI{SET,GET}    sequential", build_group_then_setget, seqrun),
]

for label, build, runner in CASES:
    bad, sample = 0, None
    tag = "".join(c for c in label if c.isalnum())[:8]
    for trial in range(TRIALS):
        ops = build(tag, trial)
        a, b = runner(t, ops), runner(o, ops)
        if a != b:
            bad += 1
            if sample is None:
                sample = [(i, ops[i][0], a[i], b[i]) for i in range(len(ops)) if a[i] != b[i]]
    print("%-42s bad=%4d/%d" % (label, bad, TRIALS))
    if sample:
        for row in sample[:3]:
            print("      op#%d %s target=%r oracle=%r" % row)
