#!/usr/bin/env python3
"""Directed parity battery for blocking collection commands in MULTI and unsatisfied WAIT."""

import select
import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
CHECKS = 0


def frame(*args):
    encoded = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(encoded) +
            b"".join(b"$%d\r\n" % len(arg) + arg + b"\r\n" for arg in encoded))


def read_raw(file):
    line = file.readline()
    if not line:
        raise EOFError("server closed the connection")
    kind = line[:1]
    if kind in b"+-:,_#(":
        return line
    if kind in (b"$", b"=", b"!"):
        size = int(line[1:-2])
        return line if size == -1 else line + file.read(size + 2)
    if kind in (b"*", b"~", b">"):
        count = int(line[1:-2])
        return line if count == -1 else line + b"".join(read_raw(file) for _ in range(count))
    if kind in (b"%", b"|"):
        count = int(line[1:-2])
        return line + b"".join(read_raw(file) for _ in range(count * 2))
    raise AssertionError("unexpected RESP marker %r" % (line[:24],))


class Conn:
    def __init__(self, resp3=False, timeout=3):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")
        if resp3:
            self.send("HELLO", "3")
            hello = self.read()
            if not hello.startswith(b"%7\r\n"):
                raise AssertionError("HELLO 3 failed: %r" % hello[:96])

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def read(self):
        return read_raw(self.file)

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.file.close()
        self.sock.close()


def bulk(value):
    value = value if isinstance(value, bytes) else str(value).encode()
    return b"$%d\r\n" % len(value) + value + b"\r\n"


def array(*values):
    return b"*%d\r\n" % len(values) + b"".join(values)


def expect(label, got, wanted):
    global CHECKS
    CHECKS += 1
    if got != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, got, wanted))
    print("  ok   " + label, flush=True)


def expect_true(label, condition, detail=""):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError("%s%s" % (label, ": " + detail if detail else ""))
    print("  ok   " + label, flush=True)


def info_blocked(conn):
    raw = conn.cmd("INFO", "CLIENTS")
    marker = b"blocked_clients:"
    if marker not in raw:
        raise AssertionError("INFO CLIENTS omitted blocked_clients: %r" % raw[:160])
    return int(raw.split(marker, 1)[1].split(b"\r\n", 1)[0])


def wait_blocked(conn, wanted, timeout=2.0):
    deadline = time.monotonic() + timeout
    value = -1
    while time.monotonic() < deadline:
        value = info_blocked(conn)
        if value == wanted:
            return value
        time.sleep(0.01)
    raise AssertionError("blocked_clients=%d, wanted %d" % (value, wanted))


def exec_one(conn, command):
    expect("MULTI before " + command[0], conn.cmd("MULTI"), b"+OK\r\n")
    expect(command[0] + " queues", conn.cmd(*command), b"+QUEUED\r\n")
    started = time.monotonic()
    reply = conn.cmd("EXEC")
    return reply, time.monotonic() - started


def collection_multi_surface(resp3):
    conn = Conn(resp3=resp3)
    mode = "RESP3" if resp3 else "RESP2"
    expect(mode + " FLUSHALL", conn.cmd("FLUSHALL"), b"+OK\r\n")
    missing = [
        ("BLPOP", "bm:list", "0"),
        ("BRPOP", "bm:list", "0"),
        ("BLMPOP", "0", "1", "bm:list", "LEFT"),
        ("BZPOPMIN", "bm:zset", "0"),
        ("BZPOPMAX", "bm:zset", "0"),
        ("BZMPOP", "0", "1", "bm:zset", "MIN"),
    ]
    null = b"_\r\n" if resp3 else b"*-1\r\n"
    for command in missing:
        reply, elapsed = exec_one(conn, command)
        expect(mode + " missing " + command[0], reply, array(null))
        expect_true(mode + " " + command[0] + " does not block in EXEC", elapsed < 0.25,
                    "elapsed %.3fs" % elapsed)

    score = b",1\r\n" if resp3 else bulk("1")
    ready = [
        (("RPUSH", "bm:list", "v"), ("BLPOP", "bm:list", "0"),
         array(array(bulk("bm:list"), bulk("v")))),
        (("RPUSH", "bm:list", "left", "right"), ("BRPOP", "bm:list", "0"),
         array(array(bulk("bm:list"), bulk("right")))),
        (("RPUSH", "bm:list", "a", "b"),
         ("BLMPOP", "0", "1", "bm:list", "LEFT", "COUNT", "2"),
         array(array(bulk("bm:list"), array(bulk("a"), bulk("b"))))),
        (("ZADD", "bm:zset", "1", "low"), ("BZPOPMIN", "bm:zset", "0"),
         array(array(bulk("bm:zset"), bulk("low"), score))),
        (("ZADD", "bm:zset", "1", "high"), ("BZPOPMAX", "bm:zset", "0"),
         array(array(bulk("bm:zset"), bulk("high"), score))),
        (("ZADD", "bm:zset", "1", "one", "2", "two"),
         ("BZMPOP", "0", "1", "bm:zset", "MAX", "COUNT", "2"),
         array(array(bulk("bm:zset"),
                     array(array(bulk("two"), b",2\r\n" if resp3 else bulk("2")),
                           array(bulk("one"), score))))),
    ]
    fired = 0
    for setup, command, wanted in ready:
        conn.cmd("DEL", "bm:list", "bm:zset")
        conn.cmd(*setup)
        reply, elapsed = exec_one(conn, command)
        expect(mode + " ready " + command[0], reply, wanted)
        expect_true(mode + " ready " + command[0] + " remains nonblocking", elapsed < 0.25)
        fired += 1
    expect_true(mode + " ready controls fired", fired == 6, "fired=%d" % fired)

    invalid = [
        (("BLPOP", "bm:list", "bad"), b"ERR timeout is not a float or out of range"),
        (("BLMPOP", "bad", "1", "bm:list", "LEFT"),
         b"ERR timeout is not a float or out of range"),
        (("BLMPOP", "0", "bad", "bm:list", "LEFT"),
         b"ERR numkeys should be greater than 0"),
        (("BZMPOP", "0", "1", "bm:zset", "BAD"), b"ERR syntax error"),
    ]
    for command, message in invalid:
        reply, _ = exec_one(conn, command)
        expect(mode + " invalid " + command[0], reply, array(b"-" + message + b"\r\n"))
    conn.close()


def wait_surface():
    admin = Conn()
    wait_blocked(admin, 0)
    expect("WAIT blocked gauge zero control", info_blocked(admin), 0)

    started = time.monotonic()
    expect("satisfied-count WAIT is immediate", admin.cmd("WAIT", "0", "500"), b":0\r\n")
    expect_true("satisfied-count WAIT timing control", time.monotonic() - started < 0.10)

    finite = Conn()
    started = time.monotonic()
    finite.send("WAIT", "1", "200")
    wait_blocked(admin, 1)
    expect_true("finite unsatisfied WAIT is silent before deadline",
                not select.select([finite.sock], [], [], 0.05)[0])
    expect("finite unsatisfied WAIT final reply", finite.read(), b":0\r\n")
    elapsed = time.monotonic() - started
    expect_true("finite unsatisfied WAIT waited for deadline", 0.15 <= elapsed <= 0.90,
                "elapsed %.3fs" % elapsed)
    wait_blocked(admin, 0)
    finite.close()

    piped = Conn()
    started = time.monotonic()
    piped.sock.sendall(frame("WAIT", "1", "120") + frame("PING"))
    wait_blocked(admin, 1)
    expect_true("WAIT is a pipeline barrier", not select.select([piped.sock], [], [], 0.04)[0])
    expect("pipelined WAIT reply", piped.read(), b":0\r\n")
    expect("younger PING follows WAIT", piped.read(), b"+PONG\r\n")
    expect_true("pipeline barrier held through deadline", time.monotonic() - started >= 0.09)
    wait_blocked(admin, 0)
    piped.close()

    forever = Conn()
    forever.send("WAIT", "1", "0")
    wait_blocked(admin, 1)
    expect_true("timeout-zero WAIT stays silent",
                not select.select([forever.sock], [], [], 0.10)[0])
    forever.close()
    wait_blocked(admin, 0)
    expect("timeout-zero disconnect drains blocked gauge", info_blocked(admin), 0)

    expect("MULTI before WAIT", admin.cmd("MULTI"), b"+OK\r\n")
    expect("WAIT queues in MULTI", admin.cmd("WAIT", "1", "0"), b"+QUEUED\r\n")
    started = time.monotonic()
    expect("WAIT stays immediate inside EXEC", admin.cmd("EXEC"), array(b":0\r\n"))
    expect_true("WAIT EXEC timing", time.monotonic() - started < 0.25)
    expect("final blocked gauge zero control", info_blocked(admin), 0)
    admin.close()


collection_multi_surface(False)
collection_multi_surface(True)
wait_surface()
print("BLOCKMULTI PASS: %d checks; collection_fired=12 wait_deadlines_fired=2 "
      "wait_disconnect_fired=1" % CHECKS, flush=True)
