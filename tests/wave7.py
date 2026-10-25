#!/usr/bin/env python3
"""Wave 7 interaction checks, called only by the existing owning gate jobs."""
import contextlib
import socket
import sys
import time
import uuid

from _lib import Conn, info, cross_owner_pair


@contextlib.contextmanager
def connection(admin):
    c = Conn(admin.host, admin.port, buffering=0)
    try:
        yield c
        c.sock.shutdown(socket.SHUT_WR)
        assert c.file.read(1) == b"", "connection teardown never acknowledged"
    finally:
        c.close()


def count(client, admin, expected):
    own = dict(word.split(b"=", 1) for word in client.must("CLIENT", "INFO").split())
    rows = [dict(word.split(b"=", 1) for word in row.split())
            for row in admin.must("CLIENT", "LIST").splitlines()]
    listed = next(row for row in rows if row[b"id"] == own[b"id"])
    assert int(own[b"watch"]) == int(listed[b"watch"]) == expected, (own, listed, expected)


def watch_effects(admin):
    left, right, a, b = cross_owner_pair(admin, "wave7:watch:" + uuid.uuid4().hex)
    assert a != b
    with connection(admin) as watcher, connection(admin) as writer:
        for queued in (False, True):
            for modifies in (False, True):
                assert admin.must("MSET", left, "a", right, "b") == b"OK"
                assert watcher.must("WATCH", left, right, left) == b"OK"
                count(watcher, admin, 2)
                commands = [("MSET", left, "a", right, "b")] if modifies else [
                    ("SET", left, "ignored", "NX"), ("DEL", right + ":missing")]
                if queued: assert writer.must("MULTI") == b"OK"
                for command in commands:
                    result = writer.cmd(*command)
                    if queued: assert result == b"QUEUED", result
                if queued:
                    assert writer.must("EXEC") == ([b"OK"] if modifies else [None, 0])
                count(watcher, admin, 2)
                assert watcher.must("MULTI") == b"OK"
                assert watcher.must("MGET", left, right) == b"QUEUED"
                result = watcher.must("EXEC")
                assert result == (None if modifies else [[b"a", b"b"]]), (queued, modifies, result)
                count(watcher, admin, 0)
        # Materializing an unchanged embedded bit must not invent a WATCH effect.
        assert admin.must("SET", left, "a") == b"OK"
        assert admin.must("OBJECT", "ENCODING", left) == b"embstr"
        assert watcher.must("WATCH", left) == b"OK"
        assert writer.must("SETBIT", left, 0, 0) == 0
        assert writer.must("OBJECT", "ENCODING", left) == b"raw"
        count(watcher, admin, 1)
        assert watcher.must("MULTI") == b"OK"
        assert watcher.must("GET", left) == b"QUEUED"
        assert watcher.must("EXEC") == [b"a"]
        count(watcher, admin, 0)
    print("PASS wave7 cross-owner WATCH counts, effects and EXEC scheduling", flush=True)


def selected_fields(c):
    """Nonzero RESETSTAT witness plus exact section membership (RESP2/RESP3)."""
    key = "wave7:subkeys:" + uuid.uuid4().hex
    before = info(c, "stats")
    assert c.must("HSET", key, "f", "v") == 1
    assert c.must("HPEXPIRE", key, 0, "FIELDS", 1, "f") == [2]
    after = info(c, "stats")
    assert int(after["expired_subkeys"]) == int(before["expired_subkeys"]) + 1
    assert int(after["expired_hash_fields"]) == int(before["expired_hash_fields"]) + 1
    fields = {
        "stats": ("expired_subkeys", "expired_hash_fields", "hash_field_expires"),
        "persistence": ("rdb_bgsave_in_progress", "rdb_last_save_time", "rdb_saves",
                        "aof_enabled", "aof_rewrite_in_progress", "aof_rewrite_scheduled",
                        "aof_rewrites", "aof_rewrites_consecutive_failures"),
    }
    for resp in (2, 3):
        c.must("HELLO", resp)
        for section in ("server", "clients", "memory", "persistence", "stats", "replication",
                        "commandstats", "cluster", "keyspace", "writeback", "lb", "flipctl"):
            body = c.must("INFO", section)
            for owner, names in fields.items():
                for name in names:
                    found = sum(line.startswith(name.encode() + b":") for line in body.split(b"\r\n"))
                    assert found == int(section == owner), (resp, section, name, found)
        for selection in ((), ("default",), ("all",), ("everything",),
                          ("stats", "persistence", "STATS")):
            body = c.must("INFO", *selection)
            for names in fields.values():
                for name in names:
                    assert sum(line.startswith(name.encode() + b":") for line in body.split(b"\r\n")) == 1
        assert int(info(c, "persistence")["rdb_last_save_time"]) == c.must("LASTSAVE")
    c.must("HELLO", 2)
    assert c.must("CONFIG", "RESETSTAT") == b"OK"
    reset = info(c, "stats")
    assert int(reset["expired_subkeys"]) == 0
    assert int(reset["expired_hash_fields"]) == int(after["expired_hash_fields"])
    print("PASS wave7 selective INFO field sections, nonzero expiry and RESETSTAT", flush=True)


def blocking_effects(c):
    """A blocked move changes its watched destination at actual serve time."""
    source, destination = "wave7:block:source", "wave7:block:destination"
    c.must("DEL", source, destination)
    with connection(c) as watcher, connection(c) as blocked:
        assert watcher.must("WATCH", destination) == b"OK"
        blocked.send("BLMOVE", source, destination, "LEFT", "RIGHT", 0)
        deadline = time.monotonic() + 5
        while int(info(c, "clients")["blocked_clients"]) != 1:
            assert time.monotonic() < deadline, "blocked move never entered registry"
            time.sleep(.002)
        count(watcher, c, 1)
        assert c.must("RPUSH", source, "served") == 1
        assert blocked.read() == b"served"
        assert c.must("LRANGE", destination, 0, -1) == [b"served"]
        assert c.must("OBJECT", "ENCODING", destination) == b"listpack"
        assert int(info(c, "clients")["blocked_clients"]) == 0
        assert watcher.must("MULTI") == b"OK"
        assert watcher.must("PING") == b"QUEUED"
        assert watcher.must("EXEC") is None
        count(watcher, c, 0)
    print("PASS wave7 blocked move registry, destination WATCH and encoding", flush=True)
    return [b"served", b"listpack", None]


if __name__ == "__main__":
    c = Conn("127.0.0.1", int(sys.argv[1]), buffering=0)
    try:
        watch_effects(c)
        c.sock.shutdown(socket.SHUT_WR)
        assert c.file.read(1) == b""
    finally:
        c.close()
