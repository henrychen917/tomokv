#!/usr/bin/env python3
"""Directed IO-owned CLIENT LIST/KILL scatter test. Usage: climon.py HOST PORT."""

import os
import select
import socket
import struct
import sys
import threading
import time


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, host, port, timeout=5):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("rb", buffering=0)

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def exact(self, count):
        chunks = []
        while count:
            chunk = self.file.read(count)
            if not chunk:
                raise EOFError("server closed connection")
            chunks.append(chunk)
            count -= len(chunk)
        return b"".join(chunks)

    def read(self):
        prefix = self.exact(1)
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
            payload = self.exact(size)
            assert self.exact(2) == b"\r\n"
            return payload
        if prefix == b"*":
            size = int(value)
            if size == -1:
                return None
            return [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")

    def close(self, reset=False):
        if not self.sock:
            return
        if reset:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                 struct.pack("ii", 1, 0))
        self.file.close()
        self.sock.close()
        self.sock = None


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")


def expect_error(actual, needle, label):
    if not isinstance(actual, RespError) or needle not in str(actual):
        raise AssertionError(f"{label}: got {actual!r}, wanted error containing {needle!r}")


def fields(line):
    return [token.split("=", 1)[0] for token in line.decode().split()]


def values(line):
    return dict(token.split("=", 1) for token in line.decode().split())


def stats(conn):
    result = {}
    for line in conn.command("INFO", "STATS").decode().splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        try:
            result[key] = int(value)
        except ValueError:
            pass
    return result


def wait_eof(conn, label):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        ready = select.select([conn.sock], [], [], 0.05)[0]
        if not ready:
            continue
        if conn.sock.recv(1) == b"":
            return
    raise AssertionError(f"{label}: connection did not close")


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
EXPECTED_FIELDS = [
    "id", "addr", "laddr", "fd", "name", "age", "idle", "flags", "db", "sub",
    "psub", "ssub", "multi", "watch", "qbuf", "qbuf-free", "argv-mem", "multi-mem",
    "rbs", "rbp", "obl", "oll", "omem", "tot-mem", "events", "cmd", "user", "redir",
    "resp", "lib-name", "lib-ver",
]


admin = Conn(HOST, PORT)
owned = []
TOKEN = f"climon-{os.getpid()}-{time.time_ns()}"
try:
    # Exact vanilla-7.4 CLIENT line shape, including cold connection metadata.
    probe = Conn(HOST, PORT)
    owned.append(probe)
    probe_id = probe.command("CLIENT", "ID")
    expect(probe.command("CLIENT", "SETNAME", "climon-probe"), b"OK", "SETNAME")
    expect(probe.command("CLIENT", "GETNAME"), b"climon-probe", "GETNAME")
    expect(probe.command("CLIENT", "SETINFO", "LIB-NAME", "climon"), b"OK", "SETINFO name")
    expect(probe.command("CLIENT", "SETINFO", "LIB-VER", "1.0"), b"OK", "SETINFO ver")
    info_line = probe.command("CLIENT", "INFO").rstrip(b"\n")
    expect(fields(info_line), EXPECTED_FIELDS, "CLIENT INFO vanilla field order")
    info = values(info_line)
    expect(int(info["id"]), probe_id, "CLIENT INFO id")
    expect(info["name"], "climon-probe", "CLIENT INFO name")
    expect(info["lib-name"], "climon", "CLIENT INFO lib-name")
    expect(info["lib-ver"], "1.0", "CLIENT INFO lib-ver")

    listed = admin.command("CLIENT", "LIST").splitlines()
    if not listed or any(fields(line) != EXPECTED_FIELDS for line in listed):
        raise AssertionError("CLIENT LIST did not emit the exact vanilla 7.4 field set")
    selected = admin.command("CLIENT", "LIST", "ID", str(probe_id)).splitlines()
    expect(len(selected), 1, "CLIENT LIST ID")
    expect(values(selected[0])["name"], "climon-probe", "CLIENT LIST ID metadata")
    if not any(int(values(line)["id"]) == probe_id
               for line in admin.command("CLIENT", "LIST", "TYPE", "normal").splitlines()):
        raise AssertionError("CLIENT LIST TYPE normal omitted ordinary client")

    # Optional same-shape vanilla oracle: compare every emitted field-name sequence, not dynamic
    # fd/port/time values. CI can set VANILLA_ORACLE_PORT to a Redis 7.4 instance.
    oracle_port = int(os.environ.get("VANILLA_ORACLE_PORT", "0"))
    if oracle_port:
        oracle_admin = Conn(HOST, oracle_port)
        oracle_shapes = [Conn(HOST, oracle_port) for _ in range(8)]
        tomo_shapes = [Conn(HOST, PORT) for _ in range(8)]
        try:
            vanilla = oracle_admin.command("CLIENT", "LIST").splitlines()
            tomo = admin.command("CLIENT", "LIST").splitlines()
            expect({tuple(fields(line)) for line in tomo},
                   {tuple(fields(line)) for line in vanilla},
                   "CLIENT LIST field-set oracle diff")
        finally:
            oracle_admin.close()
            for conn in oracle_shapes + tomo_shapes:
                conn.close()

    # Scatter is non-vacuous: one LIST must receive one acknowledgement from every (>1) IO.
    before = stats(admin)
    admin.command("CLIENT", "LIST")
    after = stats(admin)
    req_delta = after["client_scatter_requests"] - before["client_scatter_requests"]
    io_delta = after["client_scatter_io_responses"] - before["client_scatter_io_responses"]
    expect(req_delta, 1, "CLIENT scatter request counter")
    if io_delta <= 1:
        raise AssertionError(f"CLIENT LIST did not scatter beyond its origin IO: {io_delta}")

    # KILL old/new forms, default SKIPME, close-self-last, and cross-IO ID kills under load.
    victim = Conn(HOST, PORT)
    victim_id = victim.command("CLIENT", "ID")
    expect(admin.command("CLIENT", "KILL", "ID", str(victim_id)), 1, "KILL ID")
    wait_eof(victim, "KILL ID victim")

    old_victim = Conn(HOST, PORT)
    old_info = values(old_victim.command("CLIENT", "INFO").rstrip(b"\n"))
    expect(admin.command("CLIENT", "KILL", old_info["addr"]), b"OK", "KILL old addr")
    wait_eof(old_victim, "KILL old-form victim")

    self_keep = Conn(HOST, PORT)
    self_id = self_keep.command("CLIENT", "ID")
    expect(self_keep.command("CLIENT", "KILL", "ID", str(self_id)), 0,
           "KILL default SKIPME")
    expect(self_keep.command("PING"), b"PONG", "SKIPME kept caller alive")
    self_keep.close()

    self_kill = Conn(HOST, PORT)
    self_id = self_kill.command("CLIENT", "ID")
    expect(self_kill.command("CLIENT", "KILL", "ID", str(self_id), "SKIPME", "NO"), 1,
           "KILL self SKIPME no reply-before-close")
    wait_eof(self_kill, "KILL self close-after-reply")

    expect_error(admin.command("CLIENT", "KILL", "ID", "0"),
                 "client-id should be greater than 0", "KILL invalid id")
    expect_error(admin.command("CLIENT", "KILL", "MAXAGE", "x"),
                 "maxage is not an integer", "KILL invalid maxage")
    expect_error(admin.command("CLIENT", "KILL", "USER", "no-such-climon-user"),
                 "No such user", "KILL missing user")

    addr_victim = Conn(HOST, PORT)
    addr_info = values(addr_victim.command("CLIENT", "INFO").rstrip(b"\n"))
    expect(admin.command("CLIENT", "KILL", "ADDR", addr_info["addr"]), 1,
           "KILL ADDR")
    wait_eof(addr_victim, "KILL ADDR victim")

    laddr_victim = Conn(HOST, PORT)
    laddr_id = laddr_victim.command("CLIENT", "ID")
    laddr = values(laddr_victim.command("CLIENT", "INFO").rstrip(b"\n"))["laddr"]
    expect(admin.command("CLIENT", "KILL", "ID", str(laddr_id), "LADDR", laddr), 1,
           "KILL LADDR AND filter")
    wait_eof(laddr_victim, "KILL LADDR victim")

    pubsub_victim = Conn(HOST, PORT)
    expect(pubsub_victim.command("SUBSCRIBE", f"{TOKEN}:kill-type"),
           [b"subscribe", f"{TOKEN}:kill-type".encode(), 1], "KILL TYPE setup")
    expect(admin.command("CLIENT", "KILL", "TYPE", "PUBSUB"), 1, "KILL TYPE pubsub")
    wait_eof(pubsub_victim, "KILL TYPE pubsub victim")

    acl_user = f"climon-kill-{os.getpid()}"
    acl_pass = f"pass-{time.time_ns()}"
    expect(admin.command("ACL", "SETUSER", acl_user, "reset", "on", f">{acl_pass}",
                         "~*", "&*", "+@all"), b"OK", "KILL USER setup")
    user_victim = Conn(HOST, PORT)
    expect(user_victim.command("AUTH", acl_user, acl_pass), b"OK", "KILL USER auth")
    expect(admin.command("CLIENT", "KILL", "USER", acl_user), 1, "KILL USER")
    wait_eof(user_victim, "KILL USER victim")
    expect(admin.command("ACL", "DELUSER", acl_user), 1, "KILL USER cleanup")

    age_victim = Conn(HOST, PORT)
    age_id = age_victim.command("CLIENT", "ID")
    time.sleep(1.05)
    expect(admin.command("CLIENT", "KILL", "ID", str(age_id), "MAXAGE", "1"), 1,
           "KILL MAXAGE")
    wait_eof(age_victim, "KILL MAXAGE victim")
    expect_error(admin.command("CLIENT", "KILL", "127.0.0.1:1"),
                 "No such client", "KILL old-form no match")

    load_stop = threading.Event()
    load_errors = []
    load_conns = [Conn(HOST, PORT) for _ in range(4)]

    def load_worker(index):
        conn = load_conns[index]
        sequence = 0
        try:
            while not load_stop.is_set():
                expect(conn.command("SET", f"climon:load:{index}", str(sequence)),
                       b"OK", "kill load SET")
                sequence += 1
        except Exception as error:  # pragma: no cover - reported below
            load_errors.append(error)

    threads = [threading.Thread(target=load_worker, args=(i,), daemon=True)
               for i in range(len(load_conns))]
    for thread in threads:
        thread.start()
    targets = [Conn(HOST, PORT) for _ in range(48)]
    target_ids = [conn.command("CLIENT", "ID") for conn in targets]
    scatter_before = stats(admin)
    for target_id in target_ids:
        expect(admin.command("CLIENT", "KILL", "ID", str(target_id)), 1,
               "cross-IO KILL ID")
    scatter_after = stats(admin)
    expect(scatter_after["client_scatter_requests"] - scatter_before["client_scatter_requests"],
           len(targets), "cross-IO KILL request count")
    expect(scatter_after["client_scatter_io_responses"] -
           scatter_before["client_scatter_io_responses"], len(targets) * io_delta,
           "every KILL acknowledged by every IO")
    for conn in targets:
        wait_eof(conn, "cross-IO KILL victim")
    load_stop.set()
    for thread in threads:
        thread.join(2)
    if load_errors:
        raise AssertionError(f"cross-IO KILL load failed: {load_errors!r}")
    for conn in load_conns:
        conn.close()

    print("climon: ok")
finally:
    for conn in owned:
        try:
            conn.close()
        except Exception:
            pass
    admin.close()
