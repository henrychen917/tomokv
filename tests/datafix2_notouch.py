#!/usr/bin/env python3
"""CD4.7: Redis LOOKUP_NOTOUCH commands, with a touching positive control."""
from compat3_lib import equal, run


def probe(c, _case):
    equal(c.cmd("CONFIG", "SET", "maxmemory-policy", "allkeys-lfu"), b"OK", "LFU")
    equal(c.cmd("CONFIG", "SET", "maxmemory", 1 << 30), b"OK", "enable metadata")
    out = {}
    commands = [("EXISTS", "k"), ("EXISTS", "k", "other"),
                ("TTL", "k"), ("PTTL", "k"), ("EXPIRETIME", "k"),
                ("PEXPIRETIME", "k"), ("TYPE", "k"),
                ("OBJECT", "ENCODING", "k"), ("OBJECT", "REFCOUNT", "k"),
                ("OBJECT", "FREQ", "k"), ("SCAN", 0, "TYPE", "string")]
    for command in commands:
        c.cmd("DEL", "k", "other")
        equal(c.cmd("SET", "k", "value"), b"OK", "seed")
        equal(c.cmd("SET", "other", "value"), b"OK", "other seed")
        before = c.cmd("OBJECT", "FREQ", "k")
        equal(before, 5, "initial LFU")
        for _ in range(32):
            c.cmd(*command)
        after = c.cmd("OBJECT", "FREQ", "k")
        out[str(command)] = (before, after)
        equal(after, before, "no touch " + str(command))
        c.cmd("MULTI")
        for _ in range(32): equal(c.cmd(*command), b"QUEUED", "queued no-touch")
        reply = c.cmd("EXEC")
        assert isinstance(reply, list) and len(reply) == 32, reply
        after_exec = c.cmd("OBJECT", "FREQ", "k")
        equal(after_exec, before, "EXEC no touch " + str(command))
        out["EXEC " + str(command)] = after_exec
    for name in ("GET", "TOUCH"):
        c.cmd("DEL", "k")
        c.cmd("SET", "k", "value")
        c.cmd(name, "k")
        equal(c.cmd("OBJECT", "FREQ", "k"), 6, name + " must touch (first LFU increment certain)")
        out[name] = 6
    return out

if __name__ == "__main__":
    run(probe, ["notouch"])
