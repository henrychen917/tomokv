#!/usr/bin/env python3
"""CC4.5/17: library glob discovery and FUNCTION memory flag semantics."""
from compat3_lib import equal, run
from _lib import Conn, RespError, cross_owner_pair, info

CROSS_KEYS = []
TARGET_ENDPOINT = None

def prepare(args):
    global TARGET_ENDPOINT
    TARGET_ENDPOINT = (args.host, args.port)
    if args.case != "flags":
        return
    c = Conn(args.host, args.port, buffering=0)
    try:
        a, b, ao, bo = cross_owner_pair(c, "compat3:cross")
        assert ao != bo
        CROSS_KEYS[:] = [a, b]
        print(f"CROSS keys={CROSS_KEYS!r} owners={ao},{bo}", flush=True)
    finally:
        c.close()


def libraries(reply):
    if isinstance(reply, RespError):
        return reply
    return sorted(reply, key=lambda row: dict(zip(row[::2], row[1::2]))[b"library_name"])


def probe(c, case):
    equal(c.cmd("FUNCTION", "FLUSH"), b"OK", "fresh registry")
    if case == "glob":
        for index, name in enumerate(("cc4lib", "cc4alt", "CC4lib", "other")):
            source = f"#!lua name={name}\nredis.register_function(\"libfn{index}\", function() return 1 end)"
            equal(c.cmd("FUNCTION", "LOAD", source), name.encode(), "library load")
        patterns = ("cc4lib", "cc4*", "*", "cc4???", "[cC][cC]4lib", "[^o]*", "none*", "", "cc4\\lib", "cc4*\x00tail")
        return {str((pattern, code)): libraries(c.cmd("FUNCTION", "LIST", "LIBRARYNAME", pattern,
                                                        *(["WITHCODE"] if code else [])))
                for pattern in patterns for code in (False, True)}
    source = "#!lua name=flags\n"
    for name, flags, body in (
        ("plain", [], "return redis.call(\"SET\", keys[1], args[1])"),
        ("allowed", ["allow-oom"], "return redis.call(\"SET\", keys[1], args[1])"),
        ("allowed_error", ["allow-oom"], "redis.call(\"SET\", keys[1], args[1]); error(\"after-write\")"),
        ("read", ["no-writes"], "return redis.call(\"GET\", keys[1])"),
        ("readonly_write", ["no-writes", "allow-oom"], "return redis.pcall(\"SET\", keys[1], args[1]).err"),
        ("stale", ["allow-stale"], "return redis.call(\"SET\", keys[1], args[1])"),
        ("stale_allowed", ["allow-stale", "allow-oom"], "return redis.call(\"SET\", keys[1], args[1])"),
        ("constant", [], "return 42"),
        ("plain_cross", [], "redis.call(\"SET\",keys[1],args[1]); return redis.call(\"SET\",keys[2],args[1])"),
        ("allowed_cross", ["allow-oom"], "redis.call(\"SET\",keys[1],args[1]); return redis.call(\"SET\",keys[2],args[1])"),
        ("error_cross", ["allow-oom"], "redis.call(\"SET\",keys[1],args[1]); redis.call(\"SET\",keys[2],args[1]); error(\"after-write\")"),
    ):
        flags_lua = ",".join(repr(f) for f in flags)
        source += f"redis.register_function{{function_name=\"{name}\",flags={{{flags_lua}}},callback=function(keys,args) {body} end}}\n"
    equal(c.cmd("FUNCTION", "LOAD", source), b"flags", "load flags")
    equal(c.cmd("SET", "k", "before"), b"OK", "seed")
    equal(c.cmd("FCALL", "allowed", 1, "k", "control"), b"OK", "before cap")
    for key in CROSS_KEYS:
        equal(c.cmd("SET", key, "before"), b"OK", "cross seed")
    equal(c.cmd("CONFIG", "SET", "maxmemory-policy", "noeviction"), b"OK", "policy")
    equal(c.cmd("CONFIG", "SET", "maxmemory", 1), b"OK", "cap")
    out = {"direct": c.cmd("SET", "k", "denied")}
    assert isinstance(out["direct"], RespError) and out["direct"].message.startswith(b"OOM "), out
    for name in ("plain", "allowed", "read", "readonly_write", "stale", "stale_allowed", "constant"):
        out[name] = c.cmd("FCALL", name, 1, "k", name)
        out[name + ":value"] = c.cmd("GET", "k")
    for name in ("plain", "allowed", "stale", "read", "readonly_write"):
        out["ro:" + name] = c.cmd("FCALL_RO", name, 1, "k", "ro")
    # Both endpoints must leave completed writes intact on a later Lua error.
    failed = c.cmd("FCALL", "allowed_error", 1, "k", "partial")
    assert isinstance(failed, RespError), failed
    out["error-effect"] = c.cmd("GET", "k")
    stats = info(c)
    target = (c.host, c.port) == TARGET_ENDPOINT
    if target:
        assert "script_apply_owner_tasks" in stats, "target must expose its APPLY witness"
    before_apply = int(stats["script_apply_owner_tasks"]) if target else 0
    for name in ("plain_cross", "allowed_cross", "error_cross"):
        reply = c.cmd("FCALL", name, 2, *CROSS_KEYS, name)
        if name == "error_cross":
            assert isinstance(reply, RespError), reply
        else:
            out[name] = reply
        out[name + ":values"] = [c.cmd("GET", key) for key in CROSS_KEYS]
    if target:
        after = int(info(c)["script_apply_owner_tasks"])
        print(f"CROSS apply-owner tasks {before_apply}->{after}", flush=True)
        assert after >= before_apply + 4, "both owners must apply both successful/partial callbacks"
    out["cap-restored"] = c.cmd("SET", "k", "must-still-fail")
    out["cap"] = c.cmd("CONFIG", "GET", "maxmemory")
    equal(c.cmd("CONFIG", "SET", "maxmemory", 0), b"OK", "remove cap")
    out["ordinary-after"] = c.cmd("SET", "k", "after")
    # wave5: FUNCTION admission must survive txnorder2's EXEC owner fragments.
    # Both owners are selected above; use exact replies and final data, including
    # the callback's completed writes before a later Lua error.
    for cap in (0, 1):
        equal(c.cmd("CONFIG", "SET", "maxmemory", cap), b"OK", "EXEC cap")
        equal(c.cmd("MULTI"), b"OK", "EXEC function begin")
        for name in ("allowed_cross", "error_cross"):
            equal(c.cmd("FCALL", name, 2, *CROSS_KEYS, "exec:" + name), b"QUEUED",
                  "EXEC admitted function queued")
        equal(c.cmd("GET", CROSS_KEYS[0]), b"QUEUED", "EXEC read queued")
        result = c.cmd("EXEC")
        assert isinstance(result, list) and len(result) == 3, result
        equal(result[0], b"OK", "EXEC allow-oom callback")
        assert isinstance(result[1], RespError), result
        equal(result[2], b"exec:error_cross", "EXEC partial callback RYOW")
        out[f"exec:{cap}"] = [result[0], isinstance(result[1], RespError), result[2],
                               *[c.cmd("GET", key) for key in CROSS_KEYS]]
        if cap:
            denied = c.cmd("SET", "k", "still-over-cap")
            assert isinstance(denied, RespError) and denied.message.startswith(b"OOM "), denied
    equal(c.cmd("CONFIG", "SET", "maxmemory", 0), b"OK", "restore after EXEC")
    return out


if __name__ == "__main__":
    run(probe, ("glob", "flags"), prepare)
