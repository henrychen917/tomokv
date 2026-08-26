#!/usr/bin/env python3
"""Directed owner-waiter tests for blocking list and sorted-set commands."""

import socket
import sys
import threading
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
FAIL = 0


def note(name, ok, extra=""):
    global FAIL
    print(("  ok   " if ok else "  FAIL ") + name + (" " + extra if extra else ""),
          flush=True)
    if not ok:
        FAIL += 1


def frame(*args):
    encoded = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(encoded) +
            b"".join(b"$%d\r\n" % len(arg) + arg + b"\r\n" for arg in encoded))


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind, value = line[:1], line[1:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            raise RuntimeError(value.decode(errors="replace"))
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return data
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise ValueError("bad RESP type %r" % line[:20])

    def cmd(self, *args):
        self.send(*args)
        return self.read()


def info_value(client, section, name):
    body = client.cmd("INFO", section)
    return int(body.split((name + ":").encode(), 1)[1].split(b"\r\n", 1)[0])


def wait_value(client, section, name, wanted, timeout=3.0):
    deadline = time.monotonic() + timeout
    value = -1
    while time.monotonic() < deadline:
        value = info_value(client, section, name)
        if value == wanted:
            return True
        time.sleep(0.01)
    return value == wanted


def start_wait(command):
    client = Resp()
    result = []
    errors = []

    def run():
        try:
            result.append(client.cmd(*command))
        except Exception as exc:  # surfaced by the parent assertion
            errors.append(str(exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return client, thread, result, errors


admin = Resp()
admin.cmd("CONFIG", "SET", "maxmemory", "0")
admin.cmd("CONFIG", "SET", "atomic", "1")
admin.cmd("FLUSHDB")

# Immediate argument-order priority and both list edges.
admin.cmd("RPUSH", "block:first", "f")
admin.cmd("RPUSH", "block:second", "s")
note("BLPOP follows argument-order priority",
     admin.cmd("BLPOP", "block:first", "block:second", "1") ==
     [b"block:first", b"f"])
note("BRPOP pops the right edge",
     admin.cmd("BRPOP", "block:second", "1") == [b"block:second", b"s"])

# One multi-element write must satisfy the FIFO one context at a time without stranding data.
fifo = []
base = info_value(admin, "CLIENTS", "blocked_clients")
for index in range(5):
    client, thread, result, errors = start_wait(("BLPOP", "block:fifo", "3"))
    fifo.append((client, thread, result, errors))
    if not wait_value(admin, "CLIENTS", "blocked_clients", base + index + 1):
        break
admin.cmd("RPUSH", "block:fifo", *["v%d" % i for i in range(5)])
for _, thread, _, _ in fifo:
    thread.join(3)
fifo_values = [result[0][1] if result and not errors else None
               for _, _, result, errors in fifo]
note("per-key waiter delivery is FIFO", fifo_values == [b"v0", b"v1", b"v2", b"v3", b"v4"],
     "values=%r" % (fifo_values,))
for client, _, _, _ in fifo:
    client.close()

# Timeout uses the executor heartbeat. Both array-nil and move bulk-nil map to None in this parser.
started = time.monotonic()
timed = admin.cmd("BRPOP", "block:timeout", "0.15")
elapsed = time.monotonic() - started
note("blocking timeout is coarse but bounded", timed is None and 0.10 <= elapsed <= 0.75,
     "elapsed=%.3f" % elapsed)
started = time.monotonic()
move_timeout = admin.cmd("BLMOVE", "block:no-source", "block:no-dest",
                         "RIGHT", "LEFT", "0.10")
note("BLMOVE timeout replies nil", move_timeout is None and time.monotonic() - started >= 0.07)

# A waiter's deadline is its own: a short-timeout waiter parked BEHIND a forever waiter must
# still time out on schedule, and the forever waiter keeps its front-of-queue claim afterward.
forever_client, forever_thread, forever_result, forever_errors = start_wait(
    ("BRPOP", "block:behind", "0"))
wait_value(admin, "CLIENTS", "blocked_clients", 1)
started = time.monotonic()
behind = admin.cmd("BRPOP", "block:behind", "0.15")
elapsed = time.monotonic() - started
note("second waiter times out behind a forever waiter",
     behind is None and 0.10 <= elapsed <= 0.75, "elapsed=%.3f" % elapsed)
admin.cmd("RPUSH", "block:behind", "front-value")
forever_thread.join(3)
note("forever waiter still served after later waiter's timeout",
     bool(forever_result) and not forever_errors and forever_result[0][1] == b"front-value",
     "result=%r errors=%r" % (forever_result, forever_errors))
forever_client.close()

# BLMPOP and all blocking zset reply shapes.
client, thread, result, errors = start_wait(
    ("BLMPOP", "2", "2", "block:ma", "block:mb", "LEFT", "COUNT", "2"))
wait_value(admin, "CLIENTS", "blocked_clients", 1)
admin.cmd("RPUSH", "block:mb", "x", "y", "z")
thread.join(3)
note("BLMPOP wakes with key and count payload",
     not errors and result == [[b"block:mb", [b"x", b"y"]]], "reply=%r" % result)
client.close()

client, thread, result, errors = start_wait(
    ("BZMPOP", "2", "2", "block:za", "block:zb", "MAX", "COUNT", "2"))
wait_value(admin, "CLIENTS", "blocked_clients", 1)
admin.cmd("ZADD", "block:zb", "1", "x", "3", "z", "2", "y")
thread.join(3)
note("BZMPOP wakes with ordered score/member payload",
     not errors and result == [[b"block:zb", [[b"z", b"3"], [b"y", b"2"]]]],
     "reply=%r" % result)
client.close()

admin.cmd("ZADD", "block:zmin", "2", "b", "1", "a")
admin.cmd("ZADD", "block:zmax", "2", "b", "1", "a")
note("BZPOPMIN reply shape", admin.cmd("BZPOPMIN", "block:zmin", "1") ==
     [b"block:zmin", b"a", b"1"])
note("BZPOPMAX reply shape", admin.cmd("BZPOPMAX", "block:zmax", "1") ==
     [b"block:zmax", b"b", b"2"])

# A blocked frame is a parse barrier: the younger SET cannot execute before the wake.
barrier = Resp()
barrier.send("BLPOP", "block:barrier", "3")
barrier.send("SET", "block:younger", "ran")
wait_value(admin, "CLIENTS", "blocked_clients", 1)
before = admin.cmd("GET", "block:younger")
admin.cmd("RPUSH", "block:barrier", "wake")
first_reply, second_reply = barrier.read(), barrier.read()
after = admin.cmd("GET", "block:younger")
note("blocked connection stops parsing younger frames",
     before is None and first_reply == [b"block:barrier", b"wake"] and
     second_reply == b"OK" and after == b"ran")
barrier.close()

# BLMOVE wakes from a source push, and its destination publication feeds another waiter.
move_client, move_thread, move_result, move_errors = start_wait(
    ("BLMOVE", "block:move-in", "block:move-mid", "RIGHT", "LEFT", "3"))
chain_client, chain_thread, chain_result, chain_errors = start_wait(
    ("BRPOPLPUSH", "block:move-mid", "block:move-out", "3"))
tail_client, tail_thread, tail_result, tail_errors = start_wait(
    ("BLPOP", "block:move-out", "3"))
wait_value(admin, "CLIENTS", "blocked_clients", 3)
admin.cmd("RPUSH", "block:move-in", "chain")
for thread in (move_thread, chain_thread, tail_thread):
    thread.join(3)
note("BLMOVE/BRPOPLPUSH publication chain",
     not (move_errors or chain_errors or tail_errors) and
     move_result == [b"chain"] and chain_result == [b"chain"] and
     tail_result == [[b"block:move-out", b"chain"]],
     "replies=%r/%r/%r" % (move_result, chain_result, tail_result))
for client in (move_client, chain_client, tail_client):
    client.close()

# Find a cross-owner LMOVE (atomic_groups proves the mechanism fired), then force its phase-2
# destination admission to fail. The epoch-zero candidate must wake nobody; a later publish does.
atomic_pair = None
for index in range(64):
    source, destination = "block:atomic-src:%d" % index, "block:atomic-dst:%d" % index
    admin.cmd("DEL", source, destination)
    admin.cmd("RPUSH", source, "probe")
    groups_before = info_value(admin, "STATS", "atomic_groups")
    admin.cmd("LMOVE", source, destination, "RIGHT", "LEFT")
    if info_value(admin, "STATS", "atomic_groups") > groups_before:
        atomic_pair = (source, destination)
        break

atomic_ok = atomic_pair is not None
atomic_extra = "no cross-owner pair"
if atomic_pair:
    source, destination = atomic_pair
    admin.cmd("DEL", source, destination)
    admin.cmd("RPUSH", source, "hidden")
    client, thread, result, errors = start_wait(("BLPOP", destination, "3"))
    wait_value(admin, "CLIENTS", "blocked_clients", 1)
    try:
        admin.cmd("CONFIG", "SET", "maxmemory", "1")
        time.sleep(0.10)  # live config propagation to shard owners
        groups_before = info_value(admin, "STATS", "atomic_groups")
        failed = False
        try:
            admin.cmd("LMOVE", source, destination, "RIGHT", "LEFT")
        except RuntimeError as exc:
            failed = "OOM" in str(exc) or "memory" in str(exc)
        groups_after = info_value(admin, "STATS", "atomic_groups")
        time.sleep(0.15)
        hidden = thread.is_alive() and admin.cmd("LLEN", destination) == 0 and \
            admin.cmd("LRANGE", source, "0", "-1") == [b"hidden"]
    finally:
        admin.cmd("CONFIG", "SET", "maxmemory", "0")
    admin.cmd("LPUSH", destination, "published")
    thread.join(3)
    atomic_ok = (failed and groups_after > groups_before and hidden and not errors and
                 result == [[destination.encode(), b"published"]])
    atomic_extra = "failed=%r fired=%r hidden=%r reply=%r" % (
        failed, groups_after > groups_before, hidden, result)
    client.close()
note("abandoned atomic push wakes nobody; publish wakes", atomic_ok, atomic_extra)

# Blocked sockets continue receiving only to observe EOF; they never parse. Closing all clients
# must cancel their contexts and sweep every registry alias/gauge.
churn = []
for index in range(96):
    sock = socket.create_connection((HOST, PORT), timeout=10)
    sock.sendall(frame("BRPOP", "block:leak:%d" % (index % 7), "0"))
    churn.append(sock)
wait_value(admin, "CLIENTS", "blocked_clients", 96)
for sock in churn:
    sock.close()
drained_clients = wait_value(admin, "CLIENTS", "blocked_clients", 0)
drained_waiters = wait_value(admin, "STATS", "blocking_waiters", 0)
note("disconnect churn drains waiter registry and gauges", drained_clients and drained_waiters,
     "clients=%d waiters=%d" % (info_value(admin, "CLIENTS", "blocked_clients"),
                                info_value(admin, "STATS", "blocking_waiters")))

admin.close()
print("BLOCKING " + ("PASS" if FAIL == 0 else "FAIL %d" % FAIL), flush=True)
sys.exit(1 if FAIL else 0)
