#!/usr/bin/env python3
"""Directed cross-owner scripting battery. Usage: xscript.py HOST PORT [stage0]."""

import socket
import sys


HOST, PORT = sys.argv[1], int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "all"
FAIL = 0


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        marker = line[:1]
        if marker == b"+":
            return line[1:-2]
        if marker == b"-":
            return RespError(line[1:-2].decode(errors="replace"))
        if marker == b":":
            return int(line[1:-2])
        if marker == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            value = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return value
        if marker == b"*":
            count = int(line[1:-2])
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("unsupported RESP marker %r" % marker)

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()


def note(label, passed, detail=""):
    global FAIL
    print(("  ok   " if passed else "  FAIL ") + label +
          ((" " + detail) if detail else ""), flush=True)
    if not passed:
        FAIL += 1


def same_owner_pair(client):
    buckets = {}
    for index in range(4096):
        key = "xscript:watch:%d" % index
        owner = client.cmd("DEBUG", "SHARD", key)
        if not isinstance(owner, int):
            raise AssertionError("DEBUG SHARD is required, got %r" % (owner,))
        bucket = buckets.setdefault(owner, [])
        bucket.append(key)
        if len(bucket) == 2:
            return owner, bucket
    raise AssertionError("no same-owner key pair in 4096 candidates")


def watch_declared_keys_only():
    watcher, writer = Resp(), Resp()
    try:
        owner, (declared, argument) = same_owner_pair(writer)
        writer.cmd("DEL", declared, argument)

        quiet_ok = watcher.cmd("WATCH", argument) == b"OK"
        quiet_ok &= writer.cmd(
            "EVAL", "return redis.call('SET',KEYS[1],ARGV[1])",
            "1", declared, "value", argument) == b"OK"
        quiet_ok &= watcher.cmd("MULTI") == b"OK"
        quiet_ok &= watcher.cmd("GET", argument) == b"QUEUED"
        quiet = watcher.cmd("EXEC")
        quiet_ok &= quiet == [None]

        fired_ok = watcher.cmd("WATCH", declared) == b"OK"
        fired_ok &= writer.cmd(
            "EVAL", "return redis.call('SET',KEYS[1],ARGV[1])",
            "1", declared, "changed", argument) == b"OK"
        fired_ok &= watcher.cmd("MULTI") == b"OK"
        fired_ok &= watcher.cmd("GET", declared) == b"QUEUED"
        fired = watcher.cmd("EXEC")
        fired_ok &= fired is None

        note("WATCH ignores script ARGV on the same owner", quiet_ok,
             "owner=%d reply=%r" % (owner, quiet))
        note("WATCH detector fires for the script's declared key", fired_ok,
             "owner=%d reply=%r" % (owner, fired))
    finally:
        watcher.close()
        writer.close()


watch_declared_keys_only()

if MODE not in ("stage0", "all"):
    raise SystemExit("unknown xscript battery mode %r" % MODE)
if FAIL:
    raise SystemExit("%d xscript checks failed" % FAIL)
print("XSCRIPT %s directed battery passed" % MODE, flush=True)
