#!/usr/bin/env python3
"""SO4.2: one-second idle clocks for every Redis maxmemory policy."""
import time
from compat3_lib import equal, run
from _lib import RespError

POLICIES = ("noeviction", "allkeys-random", "volatile-random", "volatile-ttl",
            "allkeys-lru", "volatile-lru", "allkeys-lfu", "volatile-lfu")
LFU_ERROR = ("ERR An LFU maxmemory policy is selected, idle time not tracked. Please note that "
             "when switching between policies at runtime LRU and LFU data will take some time to adjust.")


def aged(c, key):
    # Opening the idle window is a requirement. Fresh-state retries are bounded;
    # a missing clock never becomes a skipped assertion or a wider tolerance.
    age = None
    for attempt in range(3):
        c.cmd("DEL", key)
        equal(c.cmd("SET", key, "value"), b"OK", "fresh idle key")
        if c.cmd("OBJECT", "IDLETIME", key) != 0: continue
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            age = c.cmd("OBJECT", "IDLETIME", key)
            if age == 1: return
            if not isinstance(age, int) or age > 1: break
            time.sleep(.025)
    raise AssertionError(("one-second idle window never opened", key, age))


def resets(c, command):
    for attempt in range(3):
        if attempt: aged(c, "idle:k")
        c.cmd(*command)
        if c.cmd("OBJECT", "IDLETIME", "idle:k") == 0: return
    raise AssertionError(("read did not reset three fresh aged keys", command))


def probe(c, _case):
    out = {}
    for policy in POLICIES:
        c.cmd("CONFIG", "SET", "maxmemory", 0)
        c.cmd("FLUSHALL")
        equal(c.cmd("CONFIG", "SET", "maxmemory-policy", policy), b"OK", "policy")
        equal(c.cmd("CONFIG", "SET", "maxmemory", 1 << 30), b"OK", "arm cap")
        c.cmd("SET", "idle:k", "value")
        if policy.endswith("lfu"):
            reply = c.cmd("OBJECT", "IDLETIME", "idle:k")
            assert isinstance(reply, RespError), (policy, reply)
            equal(str(reply), LFU_ERROR, "LFU error for a present key")
            equal(c.cmd("OBJECT", "IDLETIME", "missing"), None, "LFU missing key")
            equal(c.cmd("OBJECT", "FREQ", "missing"), None, "LFU FREQ missing")
            out[policy] = LFU_ERROR
            continue
        equal(c.cmd("OBJECT", "IDLETIME", "missing"), None, "missing key")
        aged(c, "idle:k")
        for command in [("EXISTS", "idle:k"), ("EXISTS", "idle:k", "missing"),
                        ("TYPE", "idle:k"), ("TTL", "idle:k"), ("PTTL", "idle:k"),
                        ("EXPIRETIME", "idle:k"), ("PEXPIRETIME", "idle:k"),
                        ("OBJECT", "ENCODING", "idle:k"), ("OBJECT", "REFCOUNT", "idle:k"),
                        ("SCAN", 0, "TYPE", "string")]:
            c.cmd(*command)
            age = c.cmd("OBJECT", "IDLETIME", "idle:k")
            assert isinstance(age, int) and age >= 1, (policy, command, age)
        equal(c.cmd("CLIENT", "NO-TOUCH", "ON"), b"OK", "no-touch on")
        c.cmd("GET", "idle:k")
        assert c.cmd("OBJECT", "IDLETIME", "idle:k") >= 1, policy
        c.cmd("SET", "idle:k", "other")
        assert c.cmd("OBJECT", "IDLETIME", "idle:k") >= 1, (policy, "no-touch SET")
        equal(c.cmd("CLIENT", "NO-TOUCH", "OFF"), b"OK", "no-touch off")
        resets(c, ("GET", "idle:k"))
        aged(c, "idle:k")
        resets(c, ("MGET", "idle:k", "missing"))
        equal(c.cmd("OBJECT", "FREQ", "missing"), None, "FREQ missing before policy check")
        out[policy] = {"new": 0, "aged": 1, "notouch": True, "get": 0, "mget": 0, "missing": None}
    return out

if __name__ == "__main__":
    run(probe, ["idle"])
