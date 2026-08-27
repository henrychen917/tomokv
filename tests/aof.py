#!/usr/bin/env python3
"""AOF restart/DEBUG LOADAOF typed-dataset gate.

Usage:
  tests/aof.py HOST PORT populate STATE.json
  tests/aof.py HOST PORT loadaof  STATE.json
  tests/aof.py HOST PORT verify   STATE.json

The state file contains the exact RESP wire replies observed before restart.  Only
Redis replies with explicitly unspecified order (SMEMBERS and HGETALL) are given
the same canonicalization used by tests/differ.py.  PTTL is checked separately
because wall-clock time must advance.
"""

import base64
import glob
import hashlib
import json
import os
import random
import socket
import sys
import time


if len(sys.argv) != 5 or sys.argv[3] not in ("populate", "loadaof", "verify", "snapshot"):
    raise SystemExit(
        "usage: tests/aof.py HOST PORT populate|loadaof|verify STATE.json\n"
        "       tests/aof.py HOST PORT snapshot SNAPSHOT.tomo")

HOST, PORT, MODE, STATE_PATH = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]


def encode(args):
    out = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return out


def read_reply(stream):
    line = stream.readline()
    if not line:
        raise EOFError("server closed connection")
    kind = line[:1]
    if kind in b"+-:":
        return line
    if kind == b"$":
        size = int(line[1:-2])
        return line if size == -1 else line + stream.read(size + 2)
    if kind == b"*":
        count = int(line[1:-2])
        if count == -1:
            return line
        return line + b"".join(read_reply(stream) for _ in range(count))
    raise AssertionError("invalid RESP reply: %r" % line[:80])


def flat_bulk_array(reply):
    """Decode the flat bulk arrays used by the two unordered probe families."""
    if reply[:1] != b"*":
        raise AssertionError("wanted array reply, got %r" % reply[:80])
    eol = reply.index(b"\r\n")
    count = int(reply[1:eol])
    pos = eol + 2
    values = []
    for _ in range(count):
        if reply[pos:pos + 1] != b"$":
            raise AssertionError("wanted bulk array item, got %r" % reply[pos:pos + 40])
        eol = reply.index(b"\r\n", pos)
        size = int(reply[pos + 1:eol])
        pos = eol + 2
        values.append(reply[pos:pos + size])
        pos += size + 2
    if pos != len(reply):
        raise AssertionError("trailing bytes in array reply")
    return values


def canonical_reply(probe, reply):
    if probe[0] == "SMEMBERS":
        values = sorted(flat_bulk_array(reply))
        return b"SMEMBERS\0" + b"".join(len(value).to_bytes(4, "little") + value
                                         for value in values)
    if probe[0] == "HGETALL":
        values = flat_bulk_array(reply)
        if len(values) % 2:
            raise AssertionError("odd HGETALL reply")
        pairs = sorted(zip(values[0::2], values[1::2]))
        return b"HGETALL\0" + b"".join(
            len(field).to_bytes(4, "little") + field +
            len(value).to_bytes(4, "little") + value for field, value in pairs)
    return reply


class Client:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(encode(args))
        return read_reply(self.stream)


c = Client()


def expect(args, reply):
    got = c.command(*args)
    if got != reply:
        raise AssertionError("%r: expected %r, got %r" % (args, reply, got))
    return got


def ok(*args):
    got = c.command(*args)
    if got[:1] == b"-":
        raise AssertionError("%r failed: %r" % (args, got))
    return got


def bulk_payload(reply):
    if reply[:1] != b"$":
        raise AssertionError("wanted bulk reply, got %r" % reply[:80])
    eol = reply.index(b"\r\n")
    size = int(reply[1:eol])
    if size < 0:
        return None
    payload = reply[eol + 2:eol + 2 + size]
    if len(payload) != size:
        raise AssertionError("truncated bulk reply")
    return payload


def persistence_info():
    payload = bulk_payload(c.command("INFO", "Persistence"))
    values = {}
    for line in payload.decode().splitlines():
        if not line.startswith("aof_") or ":" not in line:
            continue
        name, value = line.split(":", 1)
        values[name] = int(value) if value.isdigit() else value
    return values


def assert_surface():
    expect(("CONFIG", "GET", "appendonly"),
           b"*2\r\n$10\r\nappendonly\r\n$3\r\nyes\r\n")
    # This exact reply prevents a vacuous DEBUG LOADAOF validation on a server
    # whose debug command surface was never enabled.
    expect(("CONFIG", "GET", "enable-debug-command"),
           b"*2\r\n$20\r\nenable-debug-command\r\n$3\r\nyes\r\n")


def find_distinct_shard_keys(prefix, count):
    keys = []
    owners = set()
    for candidate in range(4096):
        key = "%s:%d" % (prefix, candidate)
        reply = c.command("DEBUG", "SHARD", key)
        if reply[:1] != b":":
            raise AssertionError("DEBUG SHARD failed: %r" % reply)
        shard = int(reply[1:-2])
        if shard in owners:
            continue
        owners.add(shard)
        keys.append(key)
        if len(keys) == count:
            return keys
    raise AssertionError("could not find %d distinct script owners" % count)


def populate_script_writes():
    values = {
        "aof:script:eval": "eval-value",
        "aof:script:evalsha": "evalsha-value",
        "aof:script:fcall": "fcall-value",
    }
    eval_source = "return redis.call('SET', KEYS[1], ARGV[1])"
    expect(("EVAL", eval_source, "1", "aof:script:eval", values["aof:script:eval"]),
           b"+OK\r\n")

    evalsha_source = "redis.call('SET', KEYS[1], ARGV[1]); return 42"
    evalsha = hashlib.sha1(evalsha_source.encode()).hexdigest()
    ok("SCRIPT", "LOAD", evalsha_source)
    expect(("EVALSHA", evalsha, "1", "aof:script:evalsha",
            values["aof:script:evalsha"]), b":42\r\n")

    library = ("#!lua name=aofscript\n"
               "redis.register_function{function_name='aofset', "
               "callback=function(keys,args) "
               "return redis.call('SET',keys[1],args[1]) end}\n"
               "redis.register_function{function_name='aofget', "
               "callback=function(keys,args) return redis.call('GET',keys[1]) end, "
               "flags={'no-writes'}}\n")
    ok("FUNCTION", "LOAD", "REPLACE", library)
    expect(("FCALL", "aofset", "1", "aof:script:fcall", values["aof:script:fcall"]),
           b"+OK\r\n")

    multi_keys = find_distinct_shard_keys("aof:script:multi", 2)
    values[multi_keys[0]] = "multi-left"
    values[multi_keys[1]] = "multi-right"
    multi_source = ("redis.call('SET', KEYS[1], ARGV[1]); "
                    "redis.call('SET', KEYS[2], ARGV[2]); return 2")
    expect(("EVAL", multi_source, "2", multi_keys[0], multi_keys[1],
            values[multi_keys[0]], values[multi_keys[1]]), b":2\r\n")

    failed_pair = find_distinct_shard_keys("aof:script:failed-prefix", 2)
    values[failed_pair[0]] = "retained-left"
    values[failed_pair[1]] = "retained-right"
    failed = c.command(
        "EVAL", "redis.call('SET',KEYS[1],ARGV[1]); "
                "redis.call('SET',KEYS[2],ARGV[2]); error('after write')",
        "2", failed_pair[0], failed_pair[1],
        values[failed_pair[0]], values[failed_pair[1]])
    if not (failed.startswith(b"-ERR ") and b"after write script:" in failed):
        raise AssertionError("failed script did not return the expected runtime error: %r" % failed)

    readonly_keys = ["aof:script:ro:eval", "aof:script:ro:evalsha",
                     "aof:script:ro:fcall"]
    ro_source = "return redis.call('GET', KEYS[1])"
    expect(("EVAL_RO", ro_source, "1", readonly_keys[0]), b"$-1\r\n")
    ro_sha = hashlib.sha1(ro_source.encode()).hexdigest()
    ok("SCRIPT", "LOAD", ro_source)
    expect(("EVALSHA_RO", ro_sha, "1", readonly_keys[1]), b"$-1\r\n")
    expect(("FCALL_RO", "aofget", "1", readonly_keys[2]), b"$-1\r\n")

    return {"values": values, "multi_keys": multi_keys, "failed_keys": failed_pair,
            "readonly_keys": readonly_keys, "expected_groups": 5}


def populate():
    expect(("FLUSHALL",), b"+OK\r\n")

    # Strings: integer/raw/binary, embedded-size edges, bitmap, HLL, and a
    # multi-frame value larger than the 64 KiB AOF staging chunk.
    expect(("SET", "s:int", "12345"), b"+OK\r\n")
    expect(("SET", "s:raw", "hello world"), b"+OK\r\n")
    expect(("SET", "s:embed192", b"e" * 192), b"+OK\r\n")
    expect(("SET", "s:extern193", b"E" * 193), b"+OK\r\n")
    expect(("SET", "s:i64min", "-9223372036854775808"), b"+OK\r\n")
    expect(("SET", "s:i64max", "9223372036854775807"), b"+OK\r\n")
    expect(("SET", "s:binary", b"\x00\x01bin\xff\x00"), b"+OK\r\n")
    expect(("SET", "s:large", b"L" * 70000), b"+OK\r\n")
    expect(("SET", "s:ttl", "survives-restart", "PX", "3600000"), b"+OK\r\n")
    expect(("SETBIT", "bitmap", "1", "1"), b":0\r\n")
    expect(("SETBIT", "bitmap", "4097", "1"), b":0\r\n")
    expect(("SETBIT", "bitmap", "99999", "1"), b":0\r\n")
    ok("PFADD", "hll", "alpha", "beta", "gamma", "delta")

    # Compact and promoted variants of every aggregate type.
    for i in range(6):
        ok("HSET", "h:compact", "f%d" % i, "v%d" % i)
    hargs = ["HSET", "h:expanded"]
    for i in range(513):
        hargs += ["field-%03d" % i, "value-%03d" % i]
    ok(*hargs)
    ok("HSET", "h:binary", b"f\x00x", b"v\xff\x00")
    ok("HSET", "h:bigvalue", "field", b"V" * 40000)

    ok("RPUSH", "l:compact", *["item-%d" % i for i in range(6)])
    ok("RPUSH", "l:expanded", *[("item-%03d-" % i) + ("p" * 50) for i in range(400)])
    ok("LPUSH", "l:expanded", "front")

    ok("SADD", "set:int", *[str(i) for i in range(50)])
    ok("SADD", "set:compact", *["member-%d" % i for i in range(8)])
    ok("SADD", "set:expanded", *["table-%03d" % i for i in range(400)])

    for i in range(6):
        ok("ZADD", "z:compact", str(i * 0.5 - 1.25), "member-%d" % i)
    rng = random.Random(31)
    zargs = ["ZADD", "z:expanded"]
    for i in range(300):
        zargs += ["%.17g" % rng.uniform(-1e6, 1e6), "member-%03d" % i]
    ok(*zargs)
    ok("ZADD", "z:infinity", "inf", "up", "-inf", "down")

    ok("XADD", "x:compact", "10-0", "f", "v")
    for i in range(300):
        ok("XADD", "x:expanded", "%d-0" % (i + 1), "field",
           "value-%03d-" % i + "Q" * 256)
    ok("XDEL", "x:expanded", "90-0")
    ok("XTRIM", "x:expanded", "MINID", "=", "51-0")
    return populate_script_writes()


PROBES = [
    ("DBSIZE",),
    ("TYPE", "s:int"), ("GET", "s:int"), ("OBJECT", "ENCODING", "s:int"),
    ("GET", "s:raw"), ("GET", "s:embed192"), ("GET", "s:extern193"),
    ("OBJECT", "ENCODING", "s:embed192"), ("OBJECT", "ENCODING", "s:extern193"),
    ("GET", "s:i64min"), ("GET", "s:i64max"),
    ("OBJECT", "ENCODING", "s:i64min"), ("OBJECT", "ENCODING", "s:i64max"),
    ("GET", "s:binary"), ("GET", "s:large"), ("STRLEN", "s:large"),
    ("GET", "s:ttl"),
    ("GETBIT", "bitmap", "1"), ("GETBIT", "bitmap", "4097"),
    ("GETBIT", "bitmap", "99999"), ("BITCOUNT", "bitmap"), ("STRLEN", "bitmap"),
    ("PFCOUNT", "hll"), ("STRLEN", "hll"),
    ("HGETALL", "h:compact"), ("HGETALL", "h:expanded"),
    ("HGETALL", "h:binary"), ("HGET", "h:bigvalue", "field"),
    ("OBJECT", "ENCODING", "h:compact"), ("OBJECT", "ENCODING", "h:expanded"),
    ("LRANGE", "l:compact", "0", "-1"), ("LRANGE", "l:expanded", "0", "-1"),
    ("OBJECT", "ENCODING", "l:compact"), ("OBJECT", "ENCODING", "l:expanded"),
    ("SMEMBERS", "set:int"), ("SMEMBERS", "set:compact"),
    ("SMEMBERS", "set:expanded"),
    ("OBJECT", "ENCODING", "set:int"), ("OBJECT", "ENCODING", "set:expanded"),
    ("ZRANGE", "z:compact", "0", "-1", "WITHSCORES"),
    ("ZRANGE", "z:expanded", "0", "-1", "WITHSCORES"),
    ("ZSCORE", "z:infinity", "up"), ("ZSCORE", "z:infinity", "down"),
    ("OBJECT", "ENCODING", "z:compact"), ("OBJECT", "ENCODING", "z:expanded"),
    ("TYPE", "x:compact"), ("XRANGE", "x:compact", "-", "+"),
    ("OBJECT", "ENCODING", "x:compact"),
    ("TYPE", "x:expanded"), ("XRANGE", "x:expanded", "-", "+"),
    ("XLEN", "x:expanded"), ("OBJECT", "ENCODING", "x:expanded"),
]


def capture():
    replies = [base64.b64encode(canonical_reply(probe, c.command(*probe))).decode("ascii")
               for probe in PROBES]
    pttl_reply = c.command("PTTL", "s:ttl")
    if pttl_reply[:1] != b":" or int(pttl_reply[1:-2]) <= 0:
        raise AssertionError("TTL key is not live: %r" % pttl_reply)
    return {"replies": replies, "pttl_ms": int(pttl_reply[1:-2])}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.write("\n")


def load_state():
    with open(STATE_PATH, "r", encoding="utf-8") as stream:
        return json.load(stream)


def increment_files():
    appenddir = os.path.join(os.path.dirname(os.path.abspath(STATE_PATH)), "appendonlydir")
    paths = sorted(glob.glob(os.path.join(appenddir, "*.incr.tomo")))
    if not paths:
        raise AssertionError("no AOF increment file found in %s" % appenddir)
    return paths


def committed_group_tickets(data):
    if len(data) < 80 or data[:8] != b"TOMOAOF\0":
        raise AssertionError("invalid AOF increment header")
    tickets = set()
    pos = 80
    while pos < len(data):
        if len(data) - pos < 40 or data[pos:pos + 4] != b"AFRM":
            raise AssertionError("invalid AOF frame while scanning script records")
        sid = int.from_bytes(data[pos + 4:pos + 8], "little")
        length = int.from_bytes(data[pos + 16:pos + 20], "little")
        payload = pos + 40
        end = payload + length
        if end > len(data):
            raise AssertionError("truncated AOF frame while scanning script records")
        if sid == 0xFFFFFFFF:
            record = payload
            while record < end:
                if end - record < 40 or data[record:record + 4] != b"AORC":
                    raise AssertionError("invalid AOF control record")
                kind = data[record + 4]
                key_len = int.from_bytes(data[record + 8:record + 12], "little")
                payload_len = int.from_bytes(data[record + 16:record + 24], "little")
                ticket = int.from_bytes(data[record + 32:record + 40], "little")
                if kind != 7 or key_len != 0 or ticket == 0:
                    raise AssertionError("invalid AOF group commit record")
                tickets.add(ticket)
                record += 40 + payload_len
            if record != end:
                raise AssertionError("AOF control record crosses its frame")
        pos = end
    return tickets


def group_ticket_for_key(data, key):
    marker = key.encode()
    matches = []
    start = 0
    while True:
        found = data.find(marker, start)
        if found < 0:
            break
        header = found - 40
        if (header >= 0 and data[header:header + 4] == b"AORC" and
                data[header + 4] == 5 and
                int.from_bytes(data[header + 8:header + 12], "little") == len(marker)):
            matches.append(int.from_bytes(data[header + 32:header + 40], "little"))
        start = found + len(marker)
    if len(matches) != 1 or matches[0] == 0:
        raise AssertionError("%s has %d grouped AOF post-images" % (key, len(matches)))
    return matches[0]


def assert_script_aof(script_state):
    blobs = []
    commits = set()
    for path in increment_files():
        with open(path, "rb") as stream:
            data = stream.read()
        blobs.append(data)
        commits.update(committed_group_tickets(data))
    tickets = {}
    for key in script_state["values"]:
        matches = [group_ticket_for_key(data, key) for data in blobs if key.encode() in data]
        if len(matches) != 1:
            raise AssertionError("%s appears in %d AOF increments" % (key, len(matches)))
        tickets[key] = matches[0]
        if matches[0] not in commits:
            raise AssertionError("%s group ticket has no GCMT" % key)
    multi = script_state["multi_keys"]
    if tickets[multi[0]] != tickets[multi[1]]:
        raise AssertionError("multi-key EVAL post-images do not share one group ticket")
    failed = script_state["failed_keys"]
    if tickets[failed[0]] != tickets[failed[1]]:
        raise AssertionError("failed script prefix post-images do not share one group ticket")
    if len(set(tickets.values())) != script_state["expected_groups"]:
        raise AssertionError("script writes used %d groups, wanted %d" %
                             (len(set(tickets.values())), script_state["expected_groups"]))
    joined = b"".join(blobs)
    leaked = [key for key in script_state["readonly_keys"] if key.encode() in joined]
    if leaked:
        raise AssertionError("read-only script keys were emitted to AOF: %r" % leaked)
    print("AOF SCRIPT BYTES PASS: write_keys=%d groups=%d readonly_absent=%d" %
          (len(tickets), len(set(tickets.values())), len(script_state["readonly_keys"])))


def wait_for_script_aof(script_state):
    deadline = time.monotonic() + 10
    stable = 0
    previous = None
    while time.monotonic() < deadline:
        stats = persistence_info()
        current = (stats.get("aof_records_written", 0), stats.get("aof_current_size", 0),
                   stats.get("aof_groups_committed", 0))
        if current[2] >= script_state["expected_groups"]:
            stable = stable + 1 if current == previous else 1
            if stable >= 5:
                assert_script_aof(script_state)
                return
        else:
            stable = 0
        previous = current
        time.sleep(0.02)
    raise AssertionError("script AOF records did not settle: %r" % (previous,))


def verify_script_state(script_state):
    for key, value in script_state["values"].items():
        reply = c.command("GET", key)
        if bulk_payload(reply) != value.encode():
            raise AssertionError("script-written key did not recover: %s" % key)
    for key in script_state["readonly_keys"]:
        if c.command("GET", key) != b"$-1\r\n":
            raise AssertionError("read-only script key exists after recovery: %s" % key)
    print("AOF SCRIPT RECOVERY PASS: values=%d readonly_absent=%d" %
          (len(script_state["values"]), len(script_state["readonly_keys"])))


def verify(expect_state):
    got = capture()
    failures = []
    for index, (want, actual) in enumerate(zip(expect_state["replies"], got["replies"])):
        if want != actual:
            failures.append((PROBES[index], base64.b64decode(want), base64.b64decode(actual)))
    if not (0 < got["pttl_ms"] <= expect_state["pttl_ms"]):
        failures.append((("PTTL", "s:ttl"), expect_state["pttl_ms"], got["pttl_ms"]))
    if failures:
        for probe, want, actual in failures[:8]:
            print("MISMATCH %r\n  expected %r\n  actual   %r" % (probe, want, actual))
        raise AssertionError("%d/%d AOF state probes differed" % (len(failures), len(PROBES) + 1))
    verify_script_state(expect_state["script"])
    print("AOF BYTE-EXACT PASS: %d static replies + live monotonic PTTL" % len(PROBES))


def snapshot_model():
    """Return the audit's normalized snapshot model: logical RECD bytes per shard."""
    expect(("SAVE",), b"+OK\r\n")
    with open(STATE_PATH, "rb") as stream:
        data = stream.read()
    if len(data) < 112 or data[:8] != b"TOMOSNP\0":
        raise AssertionError("invalid snapshot header in %s" % STATE_PATH)
    get_u32 = lambda offset: int.from_bytes(data[offset:offset + 4], "little")
    shards = get_u32(16)
    sections = [bytearray() for _ in range(shards)]
    sequence = [0] * shards
    pos = 80
    frames = 0
    while pos + 32 <= len(data) and get_u32(pos) == 0x4D415246:  # FRAM
        sid, seq, length = get_u32(pos + 4), get_u32(pos + 8), get_u32(pos + 16)
        if sid >= shards or seq != sequence[sid] or pos + 32 + length > len(data):
            raise AssertionError("invalid snapshot frame")
        sequence[sid] += 1
        pos += 32
        sections[sid] += data[pos:pos + length]
        pos += length
        frames += 1
    if pos + 32 != len(data) or get_u32(pos) != 0x454E4F44:  # DONE
        raise AssertionError("snapshot completion footer is missing")
    return {
        "shards": shards,
        "frames": frames,
        "sections": [hashlib.sha256(section).hexdigest() for section in sections],
        "section_bytes": [len(section) for section in sections],
    }


assert_surface()
if MODE == "populate":
    script_state = populate()
    wait_for_script_aof(script_state)
    state = capture()
    state["script"] = script_state
    save_state(state)
    print("AOF DATASET CAPTURED: %d static replies, PTTL=%d ms" %
          (len(PROBES), state["pttl_ms"]))
elif MODE == "loadaof":
    expect(("DEBUG", "LOADAOF"), b"+OK\r\n")
    verify(load_state())
elif MODE == "verify":
    verify(load_state())
else:
    print("SNAPSHOT BYTE MODEL: " + json.dumps(snapshot_model(), sort_keys=True))
