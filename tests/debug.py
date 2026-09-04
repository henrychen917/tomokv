#!/usr/bin/env python3
"""Directed boot-gated DEBUG and snapshot reload test. Usage: tests/debug.py HOST PORT"""

import os
import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])


class RespError(Exception):
    pass


def frame(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()

    def read(self):
        kind = self.file.read(1)
        if not kind:
            raise EOFError("server closed")
        line = self.file.readline()
        value = line[:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            data = self.file.read(size)
            assert self.file.read(2) == b"\r\n"
            return data
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("unknown RESP prefix %r" % kind)


def expect(actual, wanted, label):
    if isinstance(wanted, str) and isinstance(actual, RespError):
        actual = str(actual)
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


def info_value(client, name, section="stats"):
    body = client.command("INFO", section)
    marker = (name + ":").encode()
    return int(body.split(marker, 1)[1].split(b"\r\n", 1)[0])


client = Conn()
mode = client.command("CONFIG", "GET", "enable-debug-command")
if mode not in ([b"enable-debug-command", b"yes"],
                [b"enable-debug-command", b"local"]):
    raise AssertionError("DEBUG test was not purpose-booted; toggle reply=%r" % (mode,))
expect(client.command("CONFIG", "SET", "enable-debug-command", "no"),
       "ERR parameter is immutable at runtime", "boot-only config")
expect(client.command("DEBUG", "SLEEP", "0"), b"OK", "DEBUG SLEEP")

# A positive sleep must park this connection, not its IO owner. Find a second connection on the
# same owner so this would deterministically stall on the former synchronous implementation. The
# pipelined PING also proves that younger frames remain behind the sleeping ROB slot.
owner = client.command("DEBUG", "IO-THREAD")
sleep_client = None
extra_clients = []
for _ in range(128):
    candidate = Conn()
    if candidate.command("DEBUG", "IO-THREAD") == owner:
        sleep_client = candidate
        break
    extra_clients.append(candidate)
if sleep_client is None:
    raise AssertionError("could not place DEBUG SLEEP probe on IO owner %r" % (owner,))
for candidate in extra_clients:
    candidate.file.close()
    candidate.sock.close()

blocked_before = info_value(client, "blocked_clients", "clients")
started = time.monotonic()
sleep_client.sock.sendall(frame("DEBUG", "SLEEP", ".5") + frame("PING"))
progress_deadline = started + .30
while time.monotonic() < progress_deadline:
    if info_value(client, "blocked_clients", "clients") >= blocked_before + 1:
        break
else:
    raise AssertionError("same-owner connection did not make progress while DEBUG SLEEP parked")
expect(client.command("PING"), b"PONG", "same-owner progress during DEBUG SLEEP")
expect(sleep_client.read(), b"OK", "deferred DEBUG SLEEP reply")
if time.monotonic() - started < .40:
    raise AssertionError("DEBUG SLEEP deadline fired too early")
expect(sleep_client.read(), b"PONG", "pipelined PING stayed behind DEBUG SLEEP")
if info_value(client, "blocked_clients", "clients") != blocked_before:
    raise AssertionError("DEBUG SLEEP did not restore blocked_clients")

# A disconnect owns cancellation of its timer and blocked-client accounting.
cancel_client = Conn()
cancel_before = info_value(client, "blocked_clients", "clients")
cancel_client.sock.sendall(frame("DEBUG", "SLEEP", ".5"))
cancel_arm_deadline = time.monotonic() + .30
while (info_value(client, "blocked_clients", "clients") < cancel_before + 1 and
       time.monotonic() < cancel_arm_deadline):
    time.sleep(.005)
if info_value(client, "blocked_clients", "clients") < cancel_before + 1:
    raise AssertionError("disconnect probe never parked")
cancel_client.file.close()
cancel_client.sock.close()
cancel_deadline = time.monotonic() + .30
while (info_value(client, "blocked_clients", "clients") != cancel_before and
       time.monotonic() < cancel_deadline):
    time.sleep(.005)
if info_value(client, "blocked_clients", "clients") != cancel_before:
    raise AssertionError("disconnect did not cancel DEBUG SLEEP")

# The live client timeout supplies the ceiling; timeout=0 retains a one-second safety ceiling.
timeout_reply = client.command("CONFIG", "GET", "timeout")
sleep_cap = max(1, int(timeout_reply[1]))
expect(client.command("DEBUG", "SLEEP", str(sleep_cap + 1)),
       "ERR value is not a valid float", "DEBUG SLEEP timeout-derived ceiling")
expect(client.command("MULTI"), b"OK", "MULTI before DEBUG SLEEP")
expect(client.command("DEBUG", "SLEEP", ".01"), b"QUEUED", "queue DEBUG SLEEP")
# The rejection is the engine's generic one: MULTI execution has no kind for DEBUG SLEEP, so the
# cross-reply assembler answers before any DEBUG handler runs. What this row pins is that the
# transaction still gets an error element for it rather than an IO thread sleeping inside EXEC.
sleep_exec = client.command("EXEC")
if (not isinstance(sleep_exec, list) or len(sleep_exec) != 1 or
        not isinstance(sleep_exec[0], RespError) or
        str(sleep_exec[0]) != "ERR command is not supported by MULTI execution"):
    raise AssertionError("DEBUG SLEEP inside EXEC was not rejected: %r" % (sleep_exec,))
sleep_client.file.close()
sleep_client.sock.close()

expect(client.command("DEBUG", "LOADAOF"),
       "ERR appendonly is disabled", "DEBUG LOADAOF appendonly-off guard")
expect(client.command("DEBUG", "JMAP"),
       "ERR unknown subcommand or wrong number of arguments for 'debug' command",
       "DEBUG JMAP intentionally absent")

# DEBUG SHARDS preserves input order and reports the live owner, not a sid-derived guess. This
# purpose-boot has no concurrent FLIP; the command intentionally does not promise cross-row
# coherence if placement changes while a batch is being read.
signals = client.command("DEBUG", "LBSIGNALS")
if not isinstance(signals, bytes):
    raise AssertionError("DEBUG LBSIGNALS geometry reply: %r" % (signals,))
shard_owners = {}
for line in signals.splitlines():
    fields = line.split()
    if fields and fields[0] == b"shard":
        if len(fields) < 3:
            raise AssertionError("short LBSIGNALS shard row: %r" % (line,))
        shard_owners[int(fields[1])] = int(fields[2])
if not shard_owners:
    raise AssertionError("DEBUG LBSIGNALS reported no shard ownership rows")
geometry_keys = [b"debug:shards:a", b"debug:shards:b", b"debug:shards:a",
                 b"debug:shards:c"]
geometry = client.command("DEBUG", "SHARDS", *geometry_keys)
if not isinstance(geometry, list) or len(geometry) != len(geometry_keys):
    raise AssertionError("DEBUG SHARDS outer reply: %r" % (geometry,))
for index, (key, pair) in enumerate(zip(geometry_keys, geometry)):
    if (not isinstance(pair, list) or len(pair) != 2 or
            not isinstance(pair[0], int) or not isinstance(pair[1], int)):
        raise AssertionError("DEBUG SHARDS row %d: %r" % (index, pair))
    sid = client.command("DEBUG", "SHARD", key)
    expect(pair, [sid, shard_owners[sid]], "DEBUG SHARDS row %d" % index)

# This is deliberately non-vacuous: assert both toggle replies, then prove the expired counter is
# stationary while off and advances after the second toggle.
expect(client.command("DEBUG", "SET-ACTIVE-EXPIRE", "0"), b"OK", "expire toggle off reply")
expired_before = info_value(client, "expired_keys")
key = ("debug:expire:%d" % os.getpid()).encode()
expect(client.command("SET", key, "value", "PX", "100"), b"OK", "expiring SET")
time.sleep(0.35)
expect(info_value(client, "expired_keys"), expired_before, "active expiry stayed off")
expect(client.command("DEBUG", "SET-ACTIVE-EXPIRE", "1"), b"OK", "expire toggle on reply")
deadline = time.monotonic() + 3
while info_value(client, "expired_keys") == expired_before and time.monotonic() < deadline:
    time.sleep(0.02)
if info_value(client, "expired_keys") <= expired_before:
    raise AssertionError("active expiry did not fire after asserted enable reply")

for atomic in (0, 1):
    expect(client.command("CONFIG", "SET", "atomic", str(atomic)), b"OK",
           "atomic=%d" % atomic)
    expect(client.command("FLUSHDB"), b"OK", "flush atomic=%d" % atomic)
    prefix = "debug:reload:%d:" % atomic
    expected = {}
    for index in range(96):
        name = (prefix + "s:%d" % index).encode()
        value = ("value-%d-" % index).encode() + b"x" * (index * 23)
        expect(client.command("SET", name, value), b"OK", "populate string")
        expected[name] = value
    expect(client.command("HSET", prefix + "hash", "a", "1", "b", "2"), 2, "hash")
    expect(client.command("RPUSH", prefix + "list", "x", "y", "z"), 3, "list")
    expect(client.command("SADD", prefix + "set", "m", "n"), 2, "set")
    expect(client.command("ZADD", prefix + "zset", "1", "one", "2", "two"), 2, "zset")
    before = client.command("DBSIZE", "NOW")
    expect(client.command("DEBUG", "RELOAD"), b"OK", "reload atomic=%d" % atomic)
    expect(client.command("DBSIZE", "NOW"), before, "dbsize round trip atomic=%d" % atomic)
    for name, value in expected.items():
        expect(client.command("GET", name), value, "string round trip")
    expect(client.command("HGETALL", prefix + "hash"), [b"a", b"1", b"b", b"2"], "hash round trip")
    expect(client.command("LRANGE", prefix + "list", "0", "-1"), [b"x", b"y", b"z"], "list round trip")
    expect(set(client.command("SMEMBERS", prefix + "set")), {b"m", b"n"}, "set round trip")
    expect(client.command("ZRANGE", prefix + "zset", "0", "-1", "WITHSCORES"),
           [b"one", b"1", b"two", b"2"], "zset round trip")

client.file.close()
client.sock.close()
print("debug: PASS (connection-timer sleep, toggle fired, batched shard ownership, LOADAOF off guard, "
      "mixed snapshot RELOAD atomic=0/1)")
