#!/usr/bin/env python3
"""CD4.14: expired_subkeys counts actual deadline removals and RESETSTAT resets it."""
import time
from compat3_lib import equal, run
from _lib import info


def probe(c, _case):
    def counter():
        stats = info(c, "stats")
        assert "expired_subkeys" in stats, "INFO stats lacks expired_subkeys"
        return int(stats["expired_subkeys"])
    def arm(key, fields):
        limit = time.monotonic() + 5
        while time.monotonic() < limit:
            c.cmd("DEL", key)
            c.cmd("HSET", key, *sum(([f, "v"] for f in fields), []), "stable", "v")
            result = c.cmd("HPEXPIRE", key, 200, "FIELDS", len(fields), *fields)
            equal(result, [1] * len(fields), "arm fields")
            remaining = c.cmd("HPTTL", key, "FIELDS", len(fields), *fields)
            if all(0 < ttl <= 200 for ttl in remaining):
                time.sleep(.25)
                return
        raise AssertionError("live field expiry window never opened")
    c.cmd("DEBUG", "SET-ACTIVE-EXPIRE", 0)
    out = {}
    try:
        c.cmd("CONFIG", "RESETSTAT")
        out["initial"] = counter();equal(out["initial"], 0, "reset")
        c.cmd("HSET", "h", "a", "1", "b", "2", "c", "3")
        equal(c.cmd("HPEXPIREAT", "h", 1, "FIELDS", 3, "a", "b", "missing"), [2,2,-2], "immediate")
        out["immediate"] = counter();equal(out["immediate"], 2, "past deadline removes two")
        c.cmd("HDEL", "h", "c")
        equal(counter(), 2, "explicit HDEL is not expiry")
        c.cmd("HSET", "h", "a", "1")
        c.cmd("HEXPIRE", "h", 60, "FIELDS", 1, "a")
        c.cmd("DEL", "h")
        equal(counter(), 2, "key DEL is not subkey expiry")
        arm("lazy", ["a"])
        equal(c.cmd("HGET", "lazy", "a"), None, "lazy read")
        out["lazy"] = counter();equal(out["lazy"], 3, "lazy removal")
        c.cmd("CONFIG", "RESETSTAT")
        out["reset"] = counter();equal(out["reset"], 0, "RESETSTAT after expiry")
        arm("active", ["a", "b"])
        c.cmd("DEBUG", "SET-ACTIVE-EXPIRE", 1)
        limit = time.monotonic() + 5
        while counter() != 2 and time.monotonic() < limit: time.sleep(.01)
        out["active"] = counter();equal(out["active"], 2, "active cycle removed both")
    finally:
        c.cmd("DEBUG", "SET-ACTIVE-EXPIRE", 1)
    return out

if __name__ == "__main__":
    run(probe, ["subkeys"])
