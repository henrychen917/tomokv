#!/usr/bin/env python3
"""CC4.3/6/25/27 assertions, adapted from round-4 cmd-complex probes.

Owns exactly one listener. Gate callers must stop their preboot first. Each case
has a 55-second bound, including boot/cleanup. --single-state is the separate,
still-open CC4.6 design witness; it is not silently treated as a passing reset
check. No redis-py or fixed binary, affinity, port, or runtime directory.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time


class Error(str):
    pass


class Map(list):
    pass


def plain(value):
    if isinstance(value, Error):
        return {"error": str(value)}
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, tuple):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def encode(args):
    args = [a if isinstance(a, bytes) else str(a).encode() for a in args]
    return b"*%d\r\n" % len(args) + b"".join(
        b"$%d\r\n" % len(a) + a + b"\r\n" for a in args)


class Conn:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), 2)
        self.sock.settimeout(15)
        self.file = self.sock.makefile("rb")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise EOFError(repr(line))
        tag, value = line[:1], line[1:-2]
        if tag == b"+":
            return value
        if tag == b"-":
            return Error(value.decode())
        if tag == b":":
            return int(value)
        if tag in (b"$", b"="):
            size = int(value)
            if size < 0:
                return None
            data = self.file.read(size)
            assert len(data) == size and self.file.read(2) == b"\r\n"
            return data
        if tag in (b"*", b"~"):
            return None if int(value) < 0 else [self.read() for _ in range(int(value))]
        if tag == b"%":
            return Map((self.read(), self.read()) for _ in range(int(value)))
        if tag == b"_":
            return None
        if tag == b"#":
            return value == b"t"
        if tag == b",":
            return float(value)
        raise ValueError((tag, value))

    def cmd(self, *args):
        self.sock.sendall(encode(args))
        return self.read()

    def pipe(self, commands):
        self.sock.sendall(b"".join(encode(c) for c in commands))
        return [self.read() for _ in commands]


def listening(port):
    check = subprocess.run(["ss", "-ltnH", "sport", "=", str(port)],
                           capture_output=True, text=True, check=True)
    return check.stdout.strip()


@contextlib.contextmanager
def server(args):
    assert not listening(args.port), f"port {args.port} occupied"
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{args.case}-{args.mode}-", dir=root)).resolve()
    cmd = ["taskset", "-c", args.cores, str(Path(args.binary).resolve()),
           "--bind", "127.0.0.1", "--port", str(args.port), "--save", "",
           "--appendonly", "no", "--dir", str(directory)]
    if args.engine == "tomo":
        cmd += ["--shards", "16", "--thread-mode", args.mode, "--read-local", str(args.read_local),
                "--flip-auto", "0", "--atomic", str(args.atomic),
                "--enable-debug-command", "yes"]
        if args.mode == "2s":
            cmd += ["--ratio", "6:2"]
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        print(json.dumps({"start": cmd, "pid": process.pid}), flush=True)
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError((directory / "server.log").read_text())
                try:
                    with Conn(args.port) as c:
                        assert c.cmd("PING") == b"PONG"
                    break
                except (ConnectionRefusedError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)
            yield args.port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                    raise AssertionError("owned server needed SIGKILL")
            assert not listening(args.port), f"owned port {args.port} did not close"
            print(json.dumps({"stop": process.pid, "exit": process.returncode,
                              "port_closed": True}), flush=True)
            assert process.returncode == 0, (directory / "server.log").read_text()


class Checks:
    def __init__(self):
        self.failed = 0
        self.total = 0

    def equal(self, label, actual, expected):
        self.total += 1
        ok = type(actual) is type(expected) and actual == expected
        self.failed += not ok
        print(json.dumps({"check": label, "pass": ok, "actual": plain(actual),
                          "expected": plain(expected)}, sort_keys=True), flush=True)


def readonly_error(source):
    sha = hashlib.sha1(source.encode()).hexdigest()
    # Redis's C-library errors omit luaL_where; direct VM writes retain it.
    where = "" if source.startswith(("rawset(", "setmetatable(", "table.insert(")) else "user_script:1: "
    return Error(f"ERR {where}Attempt to modify a readonly table script: {sha}, on @user_script:1.")


def sandbox(port, args, check):
    key = "cc4:sandbox"
    read = "return redis.call('GET',KEYS[1])"
    mutation = "redis.call=function(...) return 'changed' end; return 'armed'"
    with Conn(port) as c:
        check.equal("seed", c.cmd("SET", key, "real"), b"OK")
        check.equal("control", c.cmd("EVAL", read, 1, key), b"real")
        check.equal("redis.call is readonly", c.cmd("EVAL", mutation, 1, key), readonly_error(mutation))
    with Conn(port) as c:
        check.equal("other client script GET", c.cmd("EVAL", read, 1, key), b"real")
        check.equal("direct GET", c.cmd("GET", key), b"real")
        check.equal("SCRIPT FLUSH", c.cmd("SCRIPT", "FLUSH"), b"OK")
        check.equal("after flush", c.cmd("EVAL", read, 1, key), b"real")
        # Existing fields, new fields, raw API writes, library mutators and the
        # reachable metatables must all be covered by the same readonly flag.
        attempts = ["_G.tonumber=1", "_G.cc4new=1", "rawset(_G,'cc4new',1)",
                    "rawset(redis,'call',1)", "setmetatable(redis,{})",
                    "string.byte=1", "math.abs=1", "table.insert=1",
                    "table.insert(redis,1)", "getmetatable('').__index.byte=1",
                    "getmetatable('').__index={}", "getmetatable(_G).__index=1"]
        for source in attempts:
            check.equal(source, c.cmd("EVAL", source, 1, key), readonly_error(source))
            check.equal("flush after mutation", c.cmd("SCRIPT", "FLUSH"), b"OK")
        for name in ("getfenv", "setfenv"):
            source = "return type(" + name + ")"
            sha = hashlib.sha1(source.encode()).hexdigest()
            expected = Error(f"ERR user_script:1: Script attempted to access nonexistent global variable '{name}' script: {sha}, on @user_script:1.")
            check.equal("no environment replacement API: " + name, c.cmd("EVAL", source, 1, key), expected)
        check.equal("ordinary mutable tables", c.cmd("EVAL",
                    "local t={}; t.x=7; table.insert(t,8); return {t.x,t[1],string.byte('a'),math.abs(-3)}", 1, key),
                    [7, 8, 97, 3])
        code = "#!lua name=cc4readonly\nredis.register_function('cc4readonly',function() redis.call=1 end)"
        check.equal("function load", c.cmd("FUNCTION", "LOAD", code), b"cc4readonly")
        error = Error("ERR user_function:2: Attempt to modify a readonly table script: cc4readonly, on @user_function:2.")
        check.equal("function sandbox readonly", c.cmd("FCALL", "cc4readonly", 1, key), error)
        check.equal("function cannot poison EVAL", c.cmd("EVAL", read, 1, key), b"real")


def functions(port, args, check):
    code = "#!lua name=cc4lib\nlocal n=0; redis.register_function('cc4counter',function(keys,args) n=n+1; return n end)"
    other = "#!lua name=cc4other\nredis.register_function('cc4other',function() return 42 end)"
    key = "cc4:same"
    with Conn(port) as c:
        check.equal("load", c.cmd("FUNCTION", "LOAD", code), b"cc4lib")
        check.equal("same key 1,2,3", [c.cmd("FCALL", "cc4counter", 1, key) for _ in range(3)], [1, 2, 3])
        check.equal("script flush", c.cmd("SCRIPT", "FLUSH"), b"OK")
        check.equal("after SCRIPT FLUSH", c.cmd("FCALL", "cc4counter", 1, key), 4)
        check.equal("unrelated load", c.cmd("FUNCTION", "LOAD", other), b"cc4other")
        check.equal("after unrelated LOAD", c.cmd("FCALL", "cc4counter", 1, key), 5)
        spread = [c.cmd("FCALL", "cc4counter", 1, f"cc4:route:{i}") for i in range(16)]
        print(json.dumps({"design_witness": "CC4.6 state across 16 keys", "actual": plain(spread),
                          "redis_expected": list(range(6, 22))}), flush=True)
        if args.single_state or args.engine == "redis":
            check.equal("single library state", spread, list(range(6, 22)))
        # Replacing the counter resets only that library, even with identical
        # source. Establish a fresh exact count after the separate design probe.
        check.equal("replace same source", c.cmd("FUNCTION", "LOAD", "REPLACE", code), b"cc4lib")
        check.equal("replace resets own closure", c.cmd("FCALL", "cc4counter", 1, key), 1)
        c.cmd("FUNCTION", "DELETE", "cc4other")
        check.equal("unrelated DELETE preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 2)
        c.cmd("FUNCTION", "LOAD", other)
        check.equal("unrelated reload preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 3)
        check.equal("duplicate LOAD rejected", c.cmd("FUNCTION", "LOAD", other), Error("ERR Library 'cc4other' already exists"))
        check.equal("failed LOAD preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 4)
        check.equal("unrelated REPLACE", c.cmd("FUNCTION", "LOAD", "REPLACE", other), b"cc4other")
        check.equal("unrelated REPLACE preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 5)
        # Source-only dumps replace state only for libraries present in the dump.
        c.cmd("FUNCTION", "DELETE", "cc4lib")
        payload = c.cmd("FUNCTION", "DUMP")
        c.cmd("FUNCTION", "LOAD", code)
        check.equal("delete/reload resets closure", c.cmd("FCALL", "cc4counter", 1, key), 1)
        check.equal("restore unrelated REPLACE", c.cmd("FUNCTION", "RESTORE", payload, "REPLACE"), b"OK")
        check.equal("unrelated RESTORE preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 2)
        c.cmd("FUNCTION", "DELETE", "cc4other")
        check.equal("restore unrelated APPEND", c.cmd("FUNCTION", "RESTORE", payload, "APPEND"), b"OK")
        check.equal("APPEND preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 3)
        check.equal("restore collision", c.cmd("FUNCTION", "RESTORE", payload), Error("ERR Library cc4other already exists"))
        check.equal("failed RESTORE preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 4)
        # A failed replacement may have registered a callback before throwing.
        bad = "#!lua name=cc4lib\nredis.register_function('cc4counter',function() return -1 end); error('stop')"
        check.equal("failed replacement refused", isinstance(c.cmd("FUNCTION", "LOAD", "REPLACE", bad), Error), True)
        check.equal("failed replacement preserves closure", c.cmd("FCALL", "cc4counter", 1, key), 5)
        check.equal("FUNCTION FLUSH", c.cmd("FUNCTION", "FLUSH"), b"OK")
        check.equal("flushed function absent", c.cmd("FCALL", "cc4counter", 1, key), Error("ERR Function not found"))
        c.cmd("FUNCTION", "LOAD", code)
        check.equal("reload after flush starts fresh", c.cmd("FCALL", "cc4counter", 1, key), 1)


def scalar_count(value):
    if isinstance(value, (list, tuple)):
        return sum(scalar_count(v) for v in value)
    return 1


def replies(port, args, check):
    bodies = {
        "array": "local t='v'; for d=1,DEPTH do local n={}; for i=1,10 do n[i]=t end; t=n end; return t",
        "map": "local t='v'; for d=1,DEPTH do local n={}; for i=1,10 do n['k'..i]=t end; t={map=n} end; return t",
        "set": "local t={set={v=true}}; for d=1,DEPTH do local n={}; for i=1,10 do n[{set=t.set}]=true end; t={set=n} end; return t",
    }
    bound = Error("ERR Error running script: script reply has too many elements")
    with Conn(port) as c:
        for resp in (2, 3):
            c.cmd("HELLO", resp)
            for kind, body in bodies.items():
                for depth in (4, 5):
                    source = body.replace("DEPTH", str(depth))
                    got = c.cmd("EVAL", source, 0)
                    label = f"RESP{resp} {kind} depth {depth}"
                    if depth == 5 and args.engine == "tomo":
                        # Report the shape/count without dumping a megabyte on failure.
                        actual = got if isinstance(got, Error) else f"{type(got).__name__}: {scalar_count(got)} scalars"
                        check.equal(label, actual, bound)
                    else:
                        expected = sum(10**i for i in range(1, depth + 1)) + 10**depth if kind == "map" else 10**depth
                        check.equal(label, scalar_count(got), expected)
                    check.equal("PING after conversion", c.cmd("PING"), b"PONG")
            source = bodies["map"].replace("DEPTH", "5")
            code = "#!lua name=cc4reply\nredis.register_function('cc4reply',function() " + source + " end)"
            c.cmd("FUNCTION", "LOAD", "REPLACE", code)
            got = c.cmd("FCALL", "cc4reply", 0)
            if args.engine == "tomo":
                actual = got if isinstance(got, Error) else f"{type(got).__name__}: {scalar_count(got)} scalars"
                check.equal(f"RESP{resp} FCALL map bound", actual, bound)
            else:
                check.equal("oracle FCALL map", scalar_count(got), 211110)
            check.equal("PING after FCALL conversion", c.cmd("PING"), b"PONG")
            # Shared-budget boundary, including arrays' existing terminating scan.
            # 99 repeated aggregates plus a final array charge exactly 100000;
            # one more scalar must fail. Maps charge both key and value.
            for kind in bodies:
                width, tail = (498, 1195) if kind == "map" else (997, 1096)
                for extra in (0, 1):
                    wrap = "t" if kind == "array" else "{" + kind + "=t}"
                    source = (f"local t={{}}; for i=1,{width} do t[i]='v' end; t={wrap}; "
                              f"local u={{}}; for i=1,{tail + extra} do u[i]='v' end; "
                              "local r={}; for i=1,99 do r[i]=t end; r[100]=u; return r")
                    got = c.cmd("EVAL", source, 0)
                    label = f"RESP{resp} {kind} budget {100000 + extra}"
                    if extra and args.engine == "tomo":
                        actual = got if isinstance(got, Error) else f"{type(got).__name__}: {scalar_count(got)} scalars"
                        check.equal(label, actual, bound)
                    else:
                        check.equal(label, scalar_count(got), 99799 + extra)
                    check.equal("PING after boundary", c.cmd("PING"), b"PONG")


def dump(port, args, check):
    with Conn(port) as c:
        for start in range(0, 4096, 64):
            codes = [f"#!lua name=l{i}\nredis.register_function('f{i}',function() return 1 end)" for i in range(start, start + 64)]
            loaded = c.pipe([["FUNCTION", "LOAD", code] for code in codes])
            assert loaded == [f"l{i}".encode() for i in range(start, start + 64)], plain(loaded)
        check.equal("4096 libraries loaded", len(c.cmd("FUNCTION", "LIST")), 4096)
        payload = c.cmd("FUNCTION", "DUMP")
        print(json.dumps({"libraries": 4096, "dump_bytes": len(payload)}), flush=True)
        check.equal("restore 4096", c.cmd("FUNCTION", "RESTORE", payload, "FLUSH"), b"OK")
        code = "#!lua name=l4096\nredis.register_function('f4096',function() return 1 end)"
        check.equal("load 4097", c.cmd("FUNCTION", "LOAD", code), b"l4096")
        payload = c.cmd("FUNCTION", "DUMP")
        print(json.dumps({"libraries": 4097, "dump_bytes": len(payload)}), flush=True)
        check.equal("restore 4097", c.cmd("FUNCTION", "RESTORE", payload, "FLUSH"), b"OK")
        check.equal("all libraries retained", len(c.cmd("FUNCTION", "LIST")), 4097)
        failures = []
        for start in range(0, 4097, 64):
            names = [f"f{i}" for i in range(start, min(start + 64, 4097))]
            values = c.pipe([["FCALL", name, 1, "cc4:dump"] for name in names])
            failures += [(n, v) for n, v in zip(names, values) if v != 1]
        check.equal("all 4097 functions callable", failures, [])
        corrupt = bytearray(payload)
        corrupt[20] ^= 1
        check.equal("checksum still checked", c.cmd("FUNCTION", "RESTORE", bytes(corrupt), "FLUSH"),
                    Error("ERR DUMP payload version or checksum are wrong"))
        check.equal("PING after restore", c.cmd("PING"), b"PONG")


CASES = {"sandbox": sandbox, "functions": functions, "replies": replies, "dump": dump}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", choices=CASES)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--cores", required=True)
    ap.add_argument("--mode", choices=("1s", "2s"), required=True)
    ap.add_argument("--engine", choices=("tomo", "redis"), default="tomo")
    ap.add_argument("--atomic", type=int, choices=(0, 1), default=0)
    ap.add_argument("--read-local", type=int, choices=(0, 1), default=0)
    ap.add_argument("--single-state", action="store_true")
    ap.add_argument("--output", default="build/scriptfix/runtime")
    args = ap.parse_args()
    check = Checks()
    def timeout(*_):
        raise TimeoutError("scriptfix row exceeded 55 seconds")
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(55)
    started = time.monotonic()
    with server(args) as port:
        CASES[args.case](port, args, check)
    signal.alarm(0)
    print(json.dumps({"case": args.case, "mode": args.mode, "checks": check.total,
                      "failures": check.failed, "seconds": round(time.monotonic() - started, 3)}), flush=True)
    return int(check.failed != 0)


if __name__ == "__main__":
    raise SystemExit(main())
