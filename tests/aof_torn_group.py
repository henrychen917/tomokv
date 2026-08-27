#!/usr/bin/env python3
"""GCMT atomic-group recovery gate.

Usage:
  tests/aof_torn_group.py HOST PORT prepare STATE.json
  tests/aof_torn_group.py HOST PORT verify STATE.json
  tests/aof_torn_group.py HOST PORT scan appendonly.aof.1.incr.tomo

The prepare mode purposefully loses its connection: the debug-gated writer stop ends the server
after a fragment frame is appended and before GCMT. The caller owns process restart and port reuse.
"""

import json
import socket
import sys
import time


if len(sys.argv) != 5 or sys.argv[3] not in ("prepare", "verify", "scan"):
    raise SystemExit("usage: tests/aof_torn_group.py HOST PORT prepare|verify|scan STATE_OR_AOF")

HOST, PORT, MODE, PATH = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]


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
        self.sock.sendall(frame(*args))
        return self.read()


def info(client):
    body = client.cmd("INFO", "Persistence").decode()
    values = {}
    for line in body.splitlines():
        if line.startswith("aof_") and ":" in line:
            key, value = line.split(":", 1)
            if value.isdigit(): values[key] = int(value)
    return values


def wait_group_count(client, before, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = info(client).get("aof_groups_committed", 0)
        if current > before: return current
        time.sleep(0.01)
    raise AssertionError("GCMT counter did not advance from %d" % before)


def assert_surface(client):
    if client.cmd("CONFIG", "GET", "appendonly") != [b"appendonly", b"yes"]:
        raise AssertionError("appendonly test was not purpose-booted")
    if client.cmd("CONFIG", "GET", "atomic") != [b"atomic", b"1"]:
        raise AssertionError("atomic test was not purpose-booted")
    if client.cmd("CONFIG", "GET", "enable-debug-command") not in (
            [b"enable-debug-command", b"yes"], [b"enable-debug-command", b"local"]):
        raise AssertionError("debug test was not purpose-booted")


def same_shard_keys(client, prefix, count):
    keys = []
    target = None
    for candidate in range(8192):
        key = "%s:%d" % (prefix, candidate)
        shard = client.cmd("DEBUG", "SHARD", key)
        if not isinstance(shard, int):
            raise AssertionError("DEBUG SHARD failed for %s" % key)
        if target is None:
            target = shard
        if shard == target:
            keys.append(key)
            if len(keys) == count:
                return keys
    raise AssertionError("could not select %d same-shard script keys" % count)


def find_group_path(client, name, operation):
    for candidate in range(256):
        state = operation(candidate)
        before = state.pop("counter_before")
        try:
            wait_group_count(client, before, 0.2)
            state["candidate"] = candidate
            state["name"] = name
            return state
        except AssertionError:
            continue
    raise AssertionError("could not route %s through a cross-shard GCMT path" % name)


def prepare():
    client = Resp()
    assert_surface(client)
    if client.cmd("FLUSHALL") != b"OK": raise AssertionError("FLUSHALL failed")
    state = {}

    baseline_keys = ["gcmt:base:%d" % index for index in range(16)]
    args = ["MSET"]
    for index, key in enumerate(baseline_keys): args += [key, "base-%d" % index]
    before = info(client).get("aof_groups_committed", 0)
    if client.cmd(*args) != b"OK": raise AssertionError("baseline MSET failed")
    wait_group_count(client, before)
    state["baseline_keys"] = baseline_keys

    # EXEC force-admits an atomic group even when its child commands are individually local.
    before = info(client).get("aof_groups_committed", 0)
    if client.cmd("MULTI") != b"OK": raise AssertionError("MULTI failed")
    if client.cmd("SET", "gcmt:exec:a", "A") != b"QUEUED": raise AssertionError("queue A")
    if client.cmd("SET", "gcmt:exec:b", "B") != b"QUEUED": raise AssertionError("queue B")
    result = client.cmd("EXEC")
    if result != [b"OK", b"OK"]: raise AssertionError("EXEC failed: %r" % (result,))
    wait_group_count(client, before)

    def rename(candidate):
        source, dest = "gcmt:rename:%d:s" % candidate, "gcmt:rename:%d:d" % candidate
        client.cmd("DEL", source, dest)
        client.cmd("SET", source, "rename-value")
        before = info(client).get("aof_groups_committed", 0)
        if client.cmd("RENAME", source, dest) != b"OK": raise AssertionError("RENAME")
        return {"source": source, "dest": dest, "counter_before": before}
    state["rename"] = find_group_path(client, "RENAME", rename)

    def copy(candidate):
        source, dest = "gcmt:copy:%d:s" % candidate, "gcmt:copy:%d:d" % candidate
        client.cmd("DEL", source, dest)
        client.cmd("SET", source, "copy-value")
        before = info(client).get("aof_groups_committed", 0)
        if client.cmd("COPY", source, dest, "REPLACE") != 1: raise AssertionError("COPY")
        return {"source": source, "dest": dest, "counter_before": before}
    state["copy"] = find_group_path(client, "COPY", copy)

    def sinterstore(candidate):
        left = "gcmt:set:%d:l" % candidate
        right = "gcmt:set:%d:r" % candidate
        dest = "gcmt:set:%d:d" % candidate
        client.cmd("DEL", left, right, dest)
        client.cmd("SADD", left, "base", "left")
        client.cmd("SADD", right, "base", "right")
        before = info(client).get("aof_groups_committed", 0)
        if client.cmd("SINTERSTORE", dest, left, right) != 1: raise AssertionError("SINTERSTORE")
        return {"left": left, "right": right, "dest": dest, "counter_before": before}
    state["sinterstore"] = find_group_path(client, "SINTERSTORE", sinterstore)

    def lmpop(candidate):
        empty = "gcmt:pop:%d:e" % candidate
        source = "gcmt:pop:%d:s" % candidate
        client.cmd("DEL", empty, source)
        client.cmd("RPUSH", source, "a", "b", "c")
        before = info(client).get("aof_groups_committed", 0)
        result = client.cmd("LMPOP", "2", empty, source, "LEFT", "COUNT", "2")
        if result != [source.encode(), [b"a", b"b"]]:
            raise AssertionError("LMPOP: %r" % (result,))
        if client.cmd("LRANGE", source, "0", "-1") != [b"c"]:
            raise AssertionError("LMPOP live post-image differs")
        return {"empty": empty, "source": source, "counter_before": before}
    state["lmpop"] = find_group_path(client, "LMPOP", lmpop)

    state["committed_before_interruption"] = info(client).get("aof_groups_committed", 0)
    state["torn_keys"] = same_shard_keys(client, "gcmt:script:torn", 16)
    with open(PATH, "w", encoding="utf-8") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.write("\n")

    reply = client.cmd("DEBUG", "AOF-STOP-AFTER-GROUP-FRAGMENTS", "1")
    if reply != b"OK": raise AssertionError("interruption toggle reply=%r" % (reply,))
    source = ("for i=1,#KEYS do redis.call('SET',KEYS[i],ARGV[i]) end; "
              "return #KEYS")
    values = [("torn-%d:" % index).encode() + b"x" * 1024
              for index in range(len(state["torn_keys"]))]
    args = ["EVAL", source, str(len(state["torn_keys"]))] + state["torn_keys"] + values
    try:
        client.cmd(*args)
    except (EOFError, ConnectionError, OSError):
        pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            probe = socket.create_connection((HOST, PORT), timeout=0.1)
            probe.close()
            time.sleep(0.02)
        except OSError:
            print("AOF DIRECTED SCRIPT GROUP STOP FIRED: committed=%d" %
                  state["committed_before_interruption"])
            return
    raise AssertionError("directed writer stop did not terminate the server")


def verify():
    with open(PATH, "r", encoding="utf-8") as stream:
        state = json.load(stream)
    client = Resp()
    assert_surface(client)
    baseline = client.cmd("MGET", *state["baseline_keys"])
    expected = [("base-%d" % index).encode() for index in range(16)]
    if baseline != expected: raise AssertionError("committed MSET did not replay")
    if client.cmd("MGET", "gcmt:exec:a", "gcmt:exec:b") != [b"A", b"B"]:
        raise AssertionError("EXEC group did not replay")
    rename = state["rename"]
    if client.cmd("MGET", rename["source"], rename["dest"]) != [None, b"rename-value"]:
        raise AssertionError("RENAME group did not replay")
    copy = state["copy"]
    if client.cmd("MGET", copy["source"], copy["dest"]) != [b"copy-value", b"copy-value"]:
        raise AssertionError("COPY group did not replay")
    stored = state["sinterstore"]
    if set(client.cmd("SMEMBERS", stored["dest"])) != {b"base"}:
        raise AssertionError("SINTERSTORE group did not replay")
    popped = state["lmpop"]
    if client.cmd("LRANGE", popped["source"], "0", "-1") != [b"c"]:
        raise AssertionError("LMPOP group did not replay")
    torn = client.cmd("MGET", *state["torn_keys"])
    present = sum(value is not None for value in torn)
    if present not in (0, len(torn)):
        raise AssertionError("torn group partially replayed: %d/%d" % (present, len(torn)))
    if present != 0:
        raise AssertionError("directed pre-GCMT group unexpectedly committed")
    stats = info(client)
    if stats.get("aof_groups_skipped_on_replay", 0) <= 0:
        raise AssertionError("group skip counter did not fire: %r" % stats)
    if stats.get("aof_groups_committed", 0) < state["committed_before_interruption"]:
        raise AssertionError("committed group counter regressed: %r" % stats)
    print("AOF INCOMPLETE GROUP RECOVERY PASS: present=0/%d committed=%d skipped=%d" % (
        len(torn), stats["aof_groups_committed"], stats["aof_groups_skipped_on_replay"]))


def scan_file():
    with open(PATH, "rb") as stream: data = stream.read()
    if len(data) < 80 or data[:8] != b"TOMOAOF\0": raise AssertionError("invalid AOF")
    u32 = lambda pos: int.from_bytes(data[pos:pos + 4], "little")
    u64 = lambda pos: int.from_bytes(data[pos:pos + 8], "little")
    frame_offsets = {}
    controls = []
    pos = 80
    while pos < len(data):
        if pos + 40 > len(data) or u32(pos) != 0x4D524641: raise AssertionError("bad frame")
        frame_at = pos
        sid, seq, length = u32(pos + 4), u32(pos + 8), u32(pos + 16)
        pos += 40
        payload = data[pos:pos + length]
        if len(payload) != length: raise AssertionError("torn test file")
        if sid == 0xFFFFFFFF: controls.append((frame_at, payload))
        else: frame_offsets[(sid, seq)] = frame_at
        pos += length
    commits = 0
    for frame_at, section in controls:
        record = 0
        while record < len(section):
            if len(section) - record < 40 or int.from_bytes(section[record:record + 4], "little") != 0x43524F41:
                raise AssertionError("bad control record")
            kind = section[record + 4]
            payload_len = int.from_bytes(section[record + 16:record + 24], "little")
            ticket = int.from_bytes(section[record + 32:record + 40], "little")
            if kind != 7 or not ticket: raise AssertionError("non-GCMT control record")
            payload = record + 40
            count = int.from_bytes(section[payload:payload + 4], "little")
            if payload_len != 4 + count * 8: raise AssertionError("bad GCMT vector")
            for index in range(count):
                dep = payload + 4 + index * 8
                key = (int.from_bytes(section[dep:dep + 4], "little"),
                       int.from_bytes(section[dep + 4:dep + 8], "little"))
                if key not in frame_offsets or frame_offsets[key] >= frame_at:
                    raise AssertionError("GCMT precedes dependency %r" % (key,))
            commits += 1
            record += 40 + payload_len
    if commits == 0: raise AssertionError("file contains no GCMT records")
    print("AOF GCMT ORDER PASS: %d commits, every dependency at lower byte offset" % commits)


if MODE == "prepare": prepare()
elif MODE == "verify": verify()
else: scan_file()
