#!/usr/bin/env python3
"""CD4.15: exact Redis raw transitions, including writes that change no bits."""
from compat3_lib import equal, run


def probe(c, _case):
    out = {}
    commands = [("APPEND", "k", ""), ("APPEND", "k", "z"),
                ("SETRANGE", "k", 0, ""), ("SETRANGE", "k", 0, "a"),
                ("SETBIT", "k", 0, 0), ("SETBIT", "k", 0, 1),
                ("BITFIELD", "k", "GET", "u8", 0),
                ("BITFIELD", "k", "SET", "u8", 0, 97),
                ("BITFIELD", "k", "OVERFLOW", "FAIL", "INCRBY", "u8", 0, 999)]
    for value in (None, "", "a", "5", "x" * 200):
        for command in commands:
            c.cmd("DEL", "k")
            if value is not None: equal(c.cmd("SET", "k", value), b"OK", "seed")
            result = c.cmd(*command)
            encoding = c.cmd("OBJECT", "ENCODING", "k")
            # Logical TTL replacement must keep the raw representation.
            c.cmd("PEXPIRE", "k", 60000)
            after_expire = c.cmd("OBJECT", "ENCODING", "k")
            c.cmd("PERSIST", "k")
            after_persist = c.cmd("OBJECT", "ENCODING", "k")
            out[str((value, command))] = [result, encoding, after_expire, after_persist, c.cmd("GET", "k")]
    c.cmd("SET", "k", "a")
    c.cmd("MULTI");c.cmd("APPEND", "k", "");c.cmd("OBJECT", "ENCODING", "k")
    out["EXEC"] = c.cmd("EXEC")
    equal(out["EXEC"], [1, b"raw"], "EXEC observes encoding mutation")
    return out

if __name__ == "__main__":
    run(probe, ["encoding"])
