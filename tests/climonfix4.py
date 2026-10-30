#!/usr/bin/env python3
"""CLIENT/PAUSE/MONITOR compatibility receipts, using the unchanged harness5 repros."""
import argparse
import contextlib
import json
import re
import select
import subprocess
import time
from pathlib import Path

from _lib import Conn, RespError, encode
from redis_tcl import sha, stop

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("PAUSE-BLOCKED-COUNT", "PAUSE-CLIENT-EXEMPT", "PAUSE-MAY-REPLICATE",
         "PAUSE-SCRIPT-FLAGS", "MONITOR-SCRIPT-CMDS", "RESET-CLEARS-LIBNAME",
         "RESET-MONITOR-ECHO", "CLIENT-LIST-CMD-NAME", "CONNECTED-CLIENTS-LAG")
FIXED = tuple(root for root in ROOTS if root not in ("PAUSE-CLIENT-EXEMPT", "CONNECTED-CLIENTS-LAG"))


def directed(host, port, root):
    """A fresh gate boot per root; assertion failures are never converted to skips."""
    clients = []
    def new():
        c = Conn(host, port, timeout=3, buffering=0)
        clients.append(c)
        return c
    def fields(c, *args):
        return dict(item.split(b"=", 1) for item in c.cmd("CLIENT", *args).split())
    def info(c, field):
        return int(re.search(rb"\b" + field.encode() + rb":(\d+)", c.cmd("INFO", "clients"))[1])
    def until(fn):
        for _ in range(200):
            if fn():
                return
            time.sleep(.01)
        raise AssertionError("required state never opened")
    def held(c):
        assert read(c, .05) == {"timeout": True}, "command escaped PAUSE WRITE"
    try:
        a = new()
        if root == "PAUSE-BLOCKED-COUNT":
            b = new()
            bid = b.cmd("CLIENT", "ID")
            assert a.cmd("CLIENT", "PAUSE", 10000, "WRITE") == b"OK"
            b.send("SET", "paused", "value")
            until(lambda: info(a, "blocked_clients") == 1)
            line = fields(a, "LIST", "ID", bid)
            assert b"b" in line[b"flags"], line
            assert line[b"cmd"] == b"set", line
            assert a.cmd("CLIENT", "UNBLOCK", bid) == 0
            held(b)
            assert a.cmd("CLIENT", "UNPAUSE") == b"OK"
            assert b.read() == b"OK"
            until(lambda: info(a, "blocked_clients") == 0)
            assert b"b" not in fields(a, "LIST", "ID", bid)[b"flags"]
            assert a.cmd("CLIENT", "PAUSE", 10000, "WRITE") == b"OK"
            b.send("SET", "paused", "again")
            until(lambda: info(a, "blocked_clients") == 1)
            assert a.cmd("CLIENT", "KILL", "ID", bid) == 1
            assert info(a, "blocked_clients") == 0, "killed postponed client remains blocked"
            assert a.cmd("CLIENT", "UNPAUSE") == b"OK"
        elif root == "PAUSE-MAY-REPLICATE":
            assert a.cmd("PFADD", "hll", "x") == 1
            b, c = new(), new()
            assert a.cmd("CLIENT", "PAUSE", 10000, "WRITE") == b"OK"
            b.send("PFCOUNT", "hll")
            c.send("PUBLISH", "channel", "message")
            until(lambda: info(a, "blocked_clients") == 2)
            held(b); held(c)
            assert a.cmd("CLIENT", "UNPAUSE") == b"OK"
            assert b.read() == 1 and c.read() == 0
        elif root == "PAUSE-SCRIPT-FLAGS":
            source = "#!lua flags=no-writes\nreturn 42"
            digest = a.cmd("SCRIPT", "LOAD", source)
            assert a.cmd("FUNCTION", "LOAD", "#!lua name=cm4\nredis.register_function{function_name='cm4', callback=function() return 42 end, flags={'no-writes'}}") == b"cm4"
            b = new()
            assert a.cmd("CLIENT", "PAUSE", 10000, "WRITE") == b"OK"
            for command in (("EVAL", source, 0), ("EVALSHA", digest, 0),
                            ("FCALL", "cm4", 0), ("EVAL_RO", "return 42", 0),
                            ("FCALL_RO", "cm4", 0)):
                b.send(*command)
                assert read(b, 1) == 42, command
            assert b.cmd("MULTI") == b"OK"
            assert b.cmd("EVAL", source, 0) == b"QUEUED"
            assert b.cmd("FCALL", "cm4", 0) == b"QUEUED"
            b.send("EXEC")
            assert read(b, 1) == [42, 42]
            assert info(a, "blocked_clients") == 0
            # The flag must not grant permission to write.
            rejected = b.cmd("EVAL", "#!lua flags=no-writes\nreturn redis.call('set',KEYS[1],'bad')", 1, "guard")
            assert isinstance(rejected, RespError) and "read-only" in str(rejected), rejected
            assert a.cmd("GET", "guard") is None
            assert a.cmd("CLIENT", "UNPAUSE") == b"OK"
            for _ in range(2):
                assert b.cmd("EVAL", "return redis.call('set',KEYS[1],ARGV[1])", 1, "guard", "allowed") == b"OK"
                assert b.cmd("EVAL", "#!lua flags=no-writes\nreturn redis.call('get',KEYS[1])", 1, "guard") == b"allowed"
        elif root == "MONITOR-SCRIPT-CMDS":
            # wave11: runtime library globals and the protected EVAL VM persist
            # independently. Register before MONITOR so the records below are exact.
            library = "#!lua name=wave11_monitor\n" + (
                "local suffix = string.upper('ok'); "
                "redis.register_function{function_name='wave11_monitor', "
                "callback=function(keys,args) "
                "return {redis.call('get',keys[1]), suffix, math.floor(2.9)} "
                "end, flags={'no-writes'}}")
            assert a.cmd("FUNCTION", "LOAD", library) == b"wave11_monitor"
            m = new()
            assert m.cmd("MONITOR") == b"OK"
            script = "redis.call('set',KEYS[1],ARGV[1]); return redis.call('get',KEYS[1])"
            assert a.cmd("EVAL", script, 1, "mon", 'v"\\\n') == b'v"\\\n'
            lines = [read(m, 1) for _ in range(3)]
            assert all(isinstance(line, str) for line in lines), lines
            assert '] "EVAL" ' in lines[0], lines
            assert '[0 lua] "set" "mon" "v\\"\\\\\\n"' in lines[1], lines
            assert '[0 lua] "get" "mon"' in lines[2], lines
            # Later pipelined commands must follow the script's nested records.
            # This checks log ordering without imposing an execution barrier.
            a.raw(encode("EVAL", script, 1, "mon", "next") + encode("PING"))
            assert a.read() == b"next" and a.read() == b"PONG"
            lines = [read(m, 1) for _ in range(4)]
            assert all(isinstance(line, str) for line in lines), lines
            assert '] "EVAL" ' in lines[0] and '[0 lua] "set"' in lines[1], lines
            assert '[0 lua] "get"' in lines[2] and '] "PING"' in lines[3], lines
            assert a.cmd("MULTI") == b"OK"
            assert a.cmd("EVAL", script, 1, "mon", "first") == b"QUEUED"
            assert a.cmd("PING") == b"QUEUED"
            assert a.cmd("EVAL", script, 1, "mon", "second") == b"QUEUED"
            assert '] "MULTI"' in read(m, 1)
            assert read(m, .05) == {"timeout": True}, "MONITOR logged a queued command before EXEC"
            assert a.cmd("EXEC") == [b"first", b"PONG", b"second"]
            lines = [read(m, 1) for _ in range(8)]
            expected = ['] "EVAL"', '[0 lua] "set"', '[0 lua] "get"', '] "PING"',
                        '] "EVAL"', '[0 lua] "set"', '[0 lua] "get"', '] "EXEC"']
            assert all(isinstance(line, str) and part in line for line, part in zip(lines, expected)), lines
            assert a.cmd("MULTI") == b"OK"
            assert a.cmd("EVAL", "return 42", 0) == b"QUEUED"
            assert a.cmd("EXEC") == [42]
            lines = [read(m, 1) for _ in range(3)]
            assert all(part in line for line, part in zip(lines, ['] "MULTI"', '] "EVAL"', '] "EXEC"'])), lines
            assert a.cmd("MULTI") == b"OK"
            assert a.cmd("EVAL", script, 1, "mon", "discarded") == b"QUEUED"
            assert a.cmd("DISCARD") == b"OK"
            assert '] "MULTI"' in read(m, 1) and '] "DISCARD"' in read(m, 1)
            assert read(m, .05) == {"timeout": True}, "MONITOR logged a discarded command"
            assert a.cmd("MULTI") == b"OK"
            assert a.cmd("EVAL", script, 1, "mon", "aborted") == b"QUEUED"
            assert isinstance(a.cmd("not-a-command"), RespError)
            assert isinstance(a.cmd("EXEC"), RespError)
            assert '] "MULTI"' in read(m, 1) and '] "EXEC"' in read(m, 1)
            assert read(m, .05) == {"timeout": True}, "MONITOR logged an aborted command"
            # Retirement now consumes the final EXEC reply. Cover both null
            # encodings, with a witnessed WATCH conflict before queueing.
            b = new()
            for protocol in (2, 3):
                assert isinstance(a.cmd("HELLO", protocol), list)
                assert '] "HELLO"' in read(m, 1)
                assert a.cmd("WATCH", "mon") == b"OK"
                assert '] "WATCH"' in read(m, 1)
                assert b.cmd("SET", "mon", "conflict") == b"OK"
                assert '] "SET"' in read(m, 1)
                assert a.cmd("MULTI") == b"OK"
                assert '] "MULTI"' in read(m, 1)
                assert a.cmd("EVAL", script, 1, "mon", "watch-aborted") == b"QUEUED"
                assert a.cmd("EXEC") is None
                line = read(m, 1)
                assert isinstance(line, str) and '] "EXEC"' in line, (protocol, line)
                assert read(m, .05) == {"timeout": True}, "MONITOR logged a WATCH-aborted child"
            # Warm both persistent interpreters, including their no-writes
            # closures, and retain nested/function/pipeline ordering after flush.
            for epoch in range(2):
                a.raw(encode("FCALL", "wave11_monitor", 1, "mon") +
                      encode("EVAL", "#!lua flags=no-writes\nreturn redis.call('get',KEYS[1])", 1, "mon") +
                      encode("PING"))
                assert a.read() == [b"conflict", b"OK", 2]
                assert a.read() == b"conflict" and a.read() == b"PONG"
                lines = [read(m, 1) for _ in range(5)]
                parts = ['] "FCALL"', '[0 lua] "get"', '] "EVAL"', '[0 lua] "get"', '] "PING"']
                assert all(isinstance(line, str) and part in line for line, part in zip(lines, parts)), lines
                assert a.cmd("SCRIPT", "FLUSH") == b"OK"
                assert '] "SCRIPT"' in read(m, 1)
            assert a.cmd("FUNCTION", "FLUSH") == b"OK"
            assert '] "FUNCTION"' in read(m, 1)
            assert a.cmd("EVAL", "#!lua flags=no-writes\nreturn redis.call('get',KEYS[1])", 1, "mon") == b"conflict"
            assert '] "EVAL"' in read(m, 1) and '[0 lua] "get"' in read(m, 1)
        elif root == "RESET-CLEARS-LIBNAME":
            assert a.cmd("CLIENT", "SETINFO", "lib-name", "redis.py") == b"OK"
            assert a.cmd("CLIENT", "SETINFO", "lib-ver", "1.0") == b"OK"
            assert a.cmd("CLIENT", "SETNAME", "old") == b"OK"
            assert a.cmd("RESET") == b"RESET"
            row = fields(a, "INFO")
            assert row[b"lib-name"] == b"redis.py" and row[b"lib-ver"] == b"1.0", row
            assert row[b"name"] == b""
        elif root == "RESET-MONITOR-ECHO":
            assert a.cmd("MONITOR") == b"OK"
            a.send("RESET")
            assert read(a, 1) == "RESET", "RESET echoed to its former monitor"
            assert a.cmd("PING") == b"PONG"
        elif root == "CLIENT-LIST-CMD-NAME":
            assert fields(a, "INFO")[b"cmd"] == b"client|info"
            assert a.cmd("PING") == b"PONG"
            current = fields(a, "LIST")
            assert current[b"cmd"] == b"client|list" and current[b"qbuf"] == b"26", current
            aid = a.cmd("CLIENT", "ID")
            assert fields(a, "LIST", "ID", aid)[b"cmd"] == b"client|list"
            b = new()
            for _ in range(70):
                assert a.cmd("CLIENT", "SETNAME", "name") == b"OK"
            assert fields(b, "LIST", "ID", aid)[b"cmd"] == b"client|setname"
            assert a.cmd("PING") == b"PONG"
            assert fields(b, "LIST", "ID", aid)[b"cmd"] == b"ping"
            assert a.cmd("CONFIG", "GET", "maxclients")
            assert fields(b, "LIST", "ID", aid)[b"cmd"] == b"config|get"
        elif root == "CONNECTED-CLIENTS-LAG":
            for _ in range(3):
                assert new().cmd("PING") == b"PONG"
            # Readiness probes from the boot helper must be fully gone first.
            until(lambda: info(a, "connected_clients") == 4)
            assert a.cmd("CONFIG", "SET", "maxclients", 2) == b"OK"
            assert a.cmd("CLIENT", "KILL", "SKIPME", "YES") == 3
            assert info(a, "connected_clients") == 1
            assert new().cmd("PING") == b"PONG", "killed clients still consume maxclients"
        else:
            raise AssertionError(root)
        print("PASS", root, flush=True)
    finally:
        for c in clients:
            c.close()


def wire(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, RespError):
        return {"error": str(value)}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def read(c, timeout=2):
    # Do not poison Python's file object by timing out inside read(). The
    # unbuffered RESP reader consumes exactly one frame, including MONITOR lines.
    if not select.select([c.sock], [], [], timeout)[0]:
        return {"timeout": True}
    c.sock.settimeout(2)
    return wire(c.read())


@contextlib.contextmanager
def server(args, binary, mode, folder, databases=16):
    folder.mkdir(parents=True, exist_ok=True)
    argv = ["taskset", "-c", args.cores, str(binary), "--port", str(args.port),
            "--bind", "127.0.0.1", "--save", "", "--appendonly", "no", "--dir", str(folder),
            "--enable-debug-command", "yes"]
    if mode != "redis":
        argv += ["--thread-mode", mode, "--shards", "16", "--databases", str(databases),
                 "--net-io", args.engine]
        if mode == "2s":
            argv += ["--ratio", args.ratio]
    clients = {}
    def conn(name):
        if name not in clients:
            clients[name] = Conn("127.0.0.1", args.port, timeout=3, buffering=0)
        return clients[name]
    with (folder / "server.log").open("w") as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError(f"server exited: {folder / 'server.log'}")
                try:
                    probe = Conn("127.0.0.1", args.port, timeout=1, buffering=0)
                    assert probe.cmd("PING") == b"PONG"
                    probe.close()
                    break
                except OSError:
                    time.sleep(.025)
            else:
                raise RuntimeError("boot deadline")
            yield conn, argv
        finally:
            for c in clients.values():
                c.close()
            stop(process)


def repro(args, binary, mode, root, case):
    transcript = []
    with server(args, binary, mode, args.output / root / mode) as (conn, argv):
        for step in case["steps"]:
            row = dict(step)
            if "sleep" in step:
                time.sleep(step["sleep"])
            else:
                c = conn(step["c"])
                if "send" in step:
                    c.send(*step["send"])
                if "raw" in step:
                    c.raw(step["raw"].encode())
                if step.get("read", 1):
                    value = read(c, step.get("timeout", 2))
                    row["raw_reply"] = value
                    if isinstance(value, str):
                        for pattern, replacement in step.get("normalize", []):
                            value = re.sub(pattern, replacement, value)
                        # MONITOR has a volatile timestamp/address, but its DB,
                        # source (lua/client), command bytes and order are exact.
                        value = re.sub(r"^\d+\.\d+ \[(\d+) 127\.0\.0\.1:\d+\]", r"<time> [\1 <client>]", value)
                        value = re.sub(r"^\d+\.\d+ \[(\d+) lua\]", r"<time> [\1 lua]", value)
                    row["reply"] = value
            transcript.append(row)
    return {"argv": argv, "binary_sha256": sha(binary), "transcript": transcript}


def projection(result):
    return [x["reply"] for x in result["transcript"] if "reply" in x and x.get("compare", True)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path)
    p.add_argument("--case", choices=FIXED)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--oracle", type=Path, default=Path("/home/user/Projects/redis74/src/redis-server"))
    p.add_argument("--cores", default="16-23")
    p.add_argument("--port", type=int, default=20200)
    p.add_argument("--ratio", default="6:2")
    p.add_argument("--engine", choices=("uring", "epoll"), default="uring")
    p.add_argument("--output", type=Path)
    p.add_argument("--root", action="append", choices=ROOTS)
    args = p.parse_args()
    if args.case:
        directed(args.host, args.port, args.case)
        return
    if not args.binary or not args.output:
        p.error("reproductions require --binary and --output")
    args.binary = args.binary.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    source = json.loads((ROOT / "docs/harness5/redis-tcl-repros.json").read_text())["cases"]
    results = {}
    for root in args.root or ROOTS:
        results[root] = {}
        for mode in ("redis", "2s", "1s"):
            result = repro(args, args.oracle if mode == "redis" else args.binary, mode, root, source[root])
            results[root][mode] = result
            if mode != "redis":
                result["verdict"] = "MATCH" if projection(result) == projection(results[root]["redis"]) else "DIFFERENT"
                print(root, mode, result["verdict"], flush=True)
            (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
