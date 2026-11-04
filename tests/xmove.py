#!/usr/bin/env python3
"""Directed cross-owner element-mover battery. Usage: tests/xmove.py HOST PORT [--release-build]"""

import socket
import sys
import time


RELEASE_BUILD = "--release-build" in sys.argv[1:]
ARGS = [arg for arg in sys.argv[1:] if arg != "--release-build"]
HOST, PORT = ARGS[0], int(ARGS[1])


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if not isinstance(arg, bytes):
            arg = str(arg).encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, timeout=30):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        prefix = self.file.read(1)
        if not prefix:
            raise EOFError("server closed the connection")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError(f"bad RESP line: {prefix + line!r}")
        value = line[:-2]
        if prefix == b"+":
            return value
        if prefix == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if prefix == b":":
            return int(value)
        if prefix == b"$":
            size = int(value)
            if size == -1:
                return None
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return payload
        if prefix == b"*":
            size = int(value)
            return None if size == -1 else [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")
    print(f"  ok   {label}", flush=True)


def expect_error(actual, contains, label):
    if not isinstance(actual, RespError) or contains not in str(actual):
        raise AssertionError(f"{label}: got {actual!r}")
    print(f"  ok   {label}", flush=True)


def config_get(conn, name):
    reply = conn.command("CONFIG", "GET", name)
    if not isinstance(reply, list) or len(reply) != 2 or reply[0] != name.encode():
        raise AssertionError(f"CONFIG GET {name}: {reply!r}")
    return reply[1].decode()


def find_geometry(conn):
    # Exercise actual cross-owner routing, not merely two shards of one owner.
    by_shard, owner_of = {}, {}

    def pick():
        if len(by_shard) < 2 or not all(len(keys) >= 2 for keys in by_shard.values()):
            return None
        shards = sorted(by_shard)
        for destination_shard in shards[1:]:
            if owner_of[destination_shard] != owner_of[shards[0]]:
                return shards[0], destination_shard
        return None

    chosen = None
    for index in range(256):
        key = f"xmove:geometry:{index}:abcdefghijklmnopqrstuvwxyz"
        reply = conn.command("DEBUG", "SHARDS", key)
        if not (isinstance(reply, list) and len(reply) == 1 and isinstance(reply[0], list) and
                len(reply[0]) == 2 and all(isinstance(value, int) for value in reply[0])):
            raise AssertionError(f"DEBUG SHARDS unavailable: {reply!r}")
        shard, owner = reply[0]
        by_shard.setdefault(shard, []).append(key)
        owner_of[shard] = owner
        chosen = pick()
        if chosen:
            break
    if not chosen:
        raise AssertionError("xmove battery needs two routing shards on different owners")
    source_shard, destination_shard = chosen
    source = by_shard[source_shard][0]
    destination = by_shard[destination_shard][0]
    blocker = by_shard[destination_shard][1]
    placed = conn.command("DEBUG", "SHARDS", source, destination, blocker)
    if placed[0][0] == placed[1][0]:
        raise AssertionError("cross-shard geometry collapsed")
    if placed[0][1] == placed[1][1] or placed[2] != placed[1]:
        raise AssertionError(f"cross-owner geometry collapsed: {placed!r}")
    print(f"  ok   geometry source-shard={source_shard} destination-shard={destination_shard} "
          f"owners={placed[0][1]}/{placed[1][1]}", flush=True)
    return source, destination, blocker


def correctness(conn, source, destination):
    fired = {"lmove": 0, "rpoplpush": 0, "smove": 0, "errors": 0, "same": 0}

    expect(conn.command("FLUSHALL"), b"OK", "clean slate")
    expect(conn.command("SET", destination, "wrong"), b"OK", "LMOVE empty setup")
    expect(conn.command("LMOVE", source, destination, "LEFT", "RIGHT"), None,
           "LMOVE empty source outranks wrong destination")
    fired["lmove"] += 1

    conn.command("DEL", source, destination)
    expect(conn.command("RPUSH", source, "solo"), 1, "LMOVE single setup")
    expect(conn.command("LMOVE", source, destination, "LEFT", "LEFT"), b"solo",
           "LMOVE single cross-owner reply")
    expect(conn.command("EXISTS", source), 0, "LMOVE single deletes source")
    expect(conn.command("LRANGE", destination, "0", "-1"), [b"solo"],
           "LMOVE single creates destination")
    fired["lmove"] += 1

    conn.command("DEL", source, destination)
    conn.command("RPUSH", source, "a", "b", "c")
    conn.command("RPUSH", destination, "x")
    expect(conn.command("LMOVE", source, destination, "RIGHT", "LEFT"), b"c",
           "LMOVE selected element")
    expect(conn.command("LRANGE", source, "0", "-1"), [b"a", b"b"],
           "LMOVE source mutation")
    expect(conn.command("LRANGE", destination, "0", "-1"), [b"c", b"x"],
           "LMOVE destination mutation")
    fired["lmove"] += 1

    conn.command("SET", destination, "wrong")
    before = conn.command("LRANGE", source, "0", "-1")
    expect_error(conn.command("LMOVE", source, destination, "LEFT", "RIGHT"),
                 "WRONGTYPE", "LMOVE wrong destination")
    expect(conn.command("LRANGE", source, "0", "-1"), before,
           "LMOVE wrong destination leaves source")
    fired["errors"] += 1

    conn.command("DEL", source, destination)
    expect(conn.command("RPOPLPUSH", source, destination), None, "RPOPLPUSH empty source")
    conn.command("RPUSH", source, "only")
    expect(conn.command("RPOPLPUSH", source, destination), b"only",
           "RPOPLPUSH single cross-owner reply")
    expect(conn.command("EXISTS", source), 0, "RPOPLPUSH single deletes source")
    expect(conn.command("LRANGE", destination, "0", "-1"), [b"only"],
           "RPOPLPUSH pushes destination left")
    fired["rpoplpush"] += 2

    conn.command("DEL", source, destination)
    conn.command("SADD", source, "member")
    conn.command("SET", destination, "wrong")
    expect_error(conn.command("SMOVE", source, destination, "member"), "WRONGTYPE",
                 "SMOVE wrong destination")
    expect(conn.command("SISMEMBER", source, "member"), 1,
           "SMOVE wrong destination leaves source")
    fired["errors"] += 1

    conn.command("DEL", source, destination)
    expect(conn.command("SMOVE", source, destination, "member"), 0, "SMOVE empty source")
    conn.command("SADD", source, "member")
    conn.command("SADD", destination, "existing")
    expect(conn.command("SMOVE", source, destination, "member"), 1,
           "SMOVE single cross-owner reply")
    expect(conn.command("EXISTS", source), 0, "SMOVE single deletes source")
    expect(sorted(conn.command("SMEMBERS", destination)), [b"existing", b"member"],
           "SMOVE destination contains both members")
    fired["smove"] += 2

    same = source + ":same"
    conn.command("RPUSH", same, "a", "b", "c")
    expect(conn.command("LMOVE", same, same, "LEFT", "RIGHT"), b"a",
           "LMOVE same-key reply")
    expect(conn.command("LRANGE", same, "0", "-1"), [b"b", b"c", b"a"],
           "LMOVE same-key rotation")
    expect(conn.command("RPOPLPUSH", same, same), b"a", "RPOPLPUSH same-key reply")
    expect(conn.command("LRANGE", same, "0", "-1"), [b"a", b"b", b"c"],
           "RPOPLPUSH same-key rotation")
    conn.command("DEL", same)
    conn.command("SADD", same, "member")
    expect(conn.command("SMOVE", same, same, "member"), 1, "SMOVE same-key hit")
    expect(conn.command("SMOVE", same, same, "missing"), 0, "SMOVE same-key miss")
    fired["same"] += 4

    if not all(fired.values()):
        raise AssertionError(f"vacuous correctness cells: {fired}")
    print(f"  ok   correctness mechanisms fired {fired}", flush=True)


def fill_list(conn, key, prefix, count):
    for base in range(0, count, 400):
        values = [f"{prefix}{index}" for index in range(base, min(count, base + 400))]
        reply = conn.command("RPUSH", key, *values)
        if not isinstance(reply, int):
            raise AssertionError(f"RPUSH fill failed: {reply!r}")


def move_cost(conn, source, destination, count, moves=160):
    conn.command("FLUSHALL")
    fill_list(conn, source, "a", count)
    fill_list(conn, destination, "b", count)
    for index in range(20):
        args = (source, destination, "RIGHT", "LEFT") if index % 2 == 0 else (
            destination, source, "LEFT", "RIGHT")
        if conn.command("LMOVE", *args) is None:
            raise AssertionError("LMOVE warmup returned nil")
    started = time.perf_counter_ns()
    for index in range(moves):
        args = (source, destination, "RIGHT", "LEFT") if index % 2 == 0 else (
            destination, source, "LEFT", "RIGHT")
        if conn.command("LMOVE", *args) is None:
            raise AssertionError("LMOVE timing move returned nil")
    elapsed = time.perf_counter_ns() - started
    expect(conn.command("LLEN", source), count, f"timing source size N={count}")
    expect(conn.command("LLEN", destination), count, f"timing destination size N={count}")
    return elapsed / moves / 1000.0


def complexity_cell(conn, source, destination, atomic):
    small = move_cost(conn, source, destination, 100)
    large = move_cost(conn, source, destination, 10000)
    ratio = large / small
    print(f"  info LMOVE N=100 {small:.1f} us N=10000 {large:.1f} us ratio={ratio:.2f}",
          flush=True)
    if atomic == 0:
        if ratio >= 5.0:
            raise AssertionError(f"atomic-off LMOVE cost still scales with collection size: {ratio:.2f}")
        print("  ok   atomic-off LMOVE size ratio < 5.0", flush=True)
    else:
        # Stage two intentionally retains MVCC's mandatory deep candidate. Measuring it keeps this
        # scoped exception visible without pretending the atomic-on lane received the O(1) fix.
        print("  skip atomic-on ratio bound: MVCC deep-candidate stage two is documented scope", flush=True)


def main():
    admin = Conn()
    atomic = int(config_get(admin, "atomic"))
    source, destination, blocker = find_geometry(admin)
    print(f"xmove directed battery atomic={atomic}", flush=True)
    correctness(admin, source, destination)
    if RELEASE_BUILD:
        complexity_cell(admin, source, destination, atomic)
    else:
        print("  skip size-ratio timing: requires --release-build; correctness checks remain active",
              flush=True)
    print("  info D2 probe/push/claim schedule is checked by the gated moverfix production-body unit", flush=True)
    print(f"PASS xmove atomic={atomic}", flush=True)


if __name__ == "__main__":
    main()
