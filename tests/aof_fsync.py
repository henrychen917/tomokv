#!/usr/bin/env python3
"""AOF sync-policy and durability-window gate.

Usage:
  tests/aof_fsync.py HOST PORT populate STATE.json POLICY COUNT
  tests/aof_fsync.py HOST PORT verify   STATE.json POLICY COUNT
"""

import json
import socket
import sys
import time


if len(sys.argv) != 7 or sys.argv[3] not in ("populate", "verify"):
    raise SystemExit(
        "usage: tests/aof_fsync.py HOST PORT populate|verify STATE.json "
        "always|everysec|no COUNT")

HOST, PORT = sys.argv[1], int(sys.argv[2])
MODE, STATE_PATH, POLICY, COUNT = sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
if POLICY not in ("always", "everysec", "no") or COUNT <= 0:
    raise SystemExit("invalid policy or count")


def encode(args):
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
        self.stream = self.sock.makefile("rb")

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind == b"+": return line[1:-2]
        if kind == b"-": raise RuntimeError(line[1:-2].decode(errors="replace"))
        if kind == b":": return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1: return None
            value = self.stream.read(size)
            if self.stream.read(2) != b"\r\n": raise AssertionError("bad bulk trailer")
            return value
        if kind == b"*":
            count = int(line[1:-2])
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("invalid RESP reply %r" % line[:40])

    def cmd(self, *args):
        self.sock.sendall(encode(args))
        return self.read()

    def pipeline(self, commands):
        self.sock.sendall(b"".join(encode(command) for command in commands))
        return [self.read() for _ in commands]


def info(client):
    body = client.cmd("INFO", "Persistence").decode()
    values = {}
    for line in body.splitlines():
        if not line.startswith("aof_") or ":" not in line: continue
        key, value = line.split(":", 1)
        if value.isdigit(): values[key] = int(value)
    return values


def key(index):
    return "aof-sync:%06d" % index


def value(index):
    prefix = ("value-%06d:" % index).encode()
    return prefix + bytes([65 + index % 26]) * (128 - len(prefix))


client = Resp()
if client.cmd("CONFIG", "GET", "appendfsync") != [b"appendfsync", POLICY.encode()]:
    raise AssertionError("appendfsync surface differs")

if MODE == "populate":
    if client.cmd("FLUSHALL") != b"OK": raise AssertionError("FLUSHALL failed")
    before = info(client)
    for start in range(0, COUNT, 32):
        commands = [("SET", key(index), value(index))
                    for index in range(start, min(COUNT, start + 32))]
        replies = client.pipeline(commands)
        if replies != [b"OK"] * len(commands):
            raise AssertionError("write batch differs at %d" % start)

    if POLICY == "everysec":
        # The base is now older than one policy interval. The later large value remains inside
        # the current durability window and is the only value the shell gate shortens.
        time.sleep(1.25)
    after = info(client)
    if POLICY == "no":
        if after.get("aof_fsyncs", -1) != 0:
            raise AssertionError("no policy submitted a data-sync: %r" % after)
        if after.get("aof_send_gate_waits", -1) != 0:
            raise AssertionError("no policy entered the reply gate: %r" % after)
    else:
        if after.get("aof_fsyncs", 0) <= before.get("aof_fsyncs", 0):
            raise AssertionError("data-sync counter did not advance: %r" % after)
        if after.get("aof_send_gate_waits", 0) <= 0:
            raise AssertionError("reply gate counter did not advance: %r" % after)

    state = {"count": COUNT, "policy": POLICY, "window_tail": POLICY == "everysec"}
    with open(STATE_PATH, "w", encoding="utf-8") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.write("\n")
    if POLICY == "everysec":
        if client.cmd("SET", "aof:durability-window-tail", b"W" * 70000) != b"OK":
            raise AssertionError("durability-window tail write failed")
    print("AOF SYNC POPULATE PASS: policy=%s keys=%d syncs=%d waits=%d" % (
        POLICY, COUNT, after.get("aof_fsyncs", 0), after.get("aof_send_gate_waits", 0)))
else:
    with open(STATE_PATH, "r", encoding="utf-8") as stream:
        state = json.load(stream)
    if state != {"count": COUNT, "policy": POLICY, "window_tail": POLICY == "everysec"}:
        raise AssertionError("state metadata differs: %r" % state)
    for start in range(0, COUNT, 32):
        indices = range(start, min(COUNT, start + 32))
        replies = client.cmd("MGET", *[key(index) for index in indices])
        expected = [value(index) for index in indices]
        if replies != expected:
            raise AssertionError("recovered batch differs at %d" % start)
    if POLICY == "everysec" and client.cmd("GET", "aof:durability-window-tail") is not None:
        raise AssertionError("shortened durability-window tail was replayed")
    stats = info(client)
    if stats.get("aof_replayed_records", 0) < COUNT:
        raise AssertionError("replay counter is too small: %r" % stats)
    print("AOF SYNC RECOVERY PASS: policy=%s keys=%d replayed=%d" % (
        POLICY, COUNT, stats["aof_replayed_records"]))
