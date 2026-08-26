#!/usr/bin/env python3
"""Redis-wire DUMP/RESTORE cross-restore battery.

Usage:
  tests/wiredump.py HOST TARGET_PORT [--oracle-port PORT] [--atomic 0|1]
                    [--boot] [--target-bin PATH] [--oracle-bin PATH]

With --boot the battery owns both processes and confines them to Lane I's assigned cores.
Without it, both ports must already be serving (handy for an instrumented/debug boot).
"""

import argparse
import os
import random
import socket
import struct
import subprocess
import sys
import tempfile
import time


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


def frame(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))


class Resp:
    def __init__(self, host, port, timeout=30):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed connection")
        kind, value = line[:1], line[1:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            return RespError(value)
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return payload
        if kind == b"*":
            size = int(value)
            return None if size == -1 else [self.read() for _ in range(size)]
        if kind == b"_":
            return None
        raise AssertionError("unsupported RESP reply %r" % line[:32])

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError("%s: got %r wanted %r" % (label, actual, wanted))


def expect_error(actual, wanted, label):
    if not isinstance(actual, RespError) or actual.message != wanted:
        raise AssertionError("%s: got %r wanted error %r" % (label, actual, wanted))


CRC_POLY = 0x95AC9329AC4BC9B5
CRC_TABLE = []
for table_index in range(256):
    table_crc = table_index
    for _ in range(8):
        table_crc = ((table_crc >> 1) ^ CRC_POLY) if table_crc & 1 else table_crc >> 1
    CRC_TABLE.append(table_crc)


def crc64(payload):
    value = 0
    for byte in payload:
        value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >> 8)
    return value


if crc64(b"123456789") != 0xE9C6D914C4B8D9CA:
    raise AssertionError("CRC64 test vector failed")


def reseal(encoded_value, version=12):
    body = encoded_value + struct.pack("<H", version)
    return body + struct.pack("<Q", crc64(body))


def stable_bytes(size, seed):
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(size))


def build_cases():
    cases = []

    def add(name, kind, expected_type, *commands):
        cases.append((name, kind, expected_type, commands))

    # Strings: raw lengths, integer immediates, LZF, and binary bytes.
    add("string-empty", "string", 0, ("SET", "src", b""))
    add("string-raw", "string", 0, ("SET", "src", b"hello"))
    add("string-int8", "string", 0, ("SET", "src", b"-5"))
    add("string-int16", "string", 0, ("SET", "src", b"32000"))
    add("string-int32", "string", 0, ("SET", "src", b"2000000000"))
    add("string-noncanonical-int", "string", 0, ("SET", "src", b"007"))
    add("string-6bit-boundary", "string", 0, ("SET", "src", stable_bytes(63, 1)))
    add("string-14bit-boundary", "string", 0, ("SET", "src", stable_bytes(64, 2)))
    add("string-32bit-length", "string", 0, ("SET", "src", stable_bytes(17000, 3)))
    add("string-lzf", "string", 0, ("SET", "src", b"redis-wire-" * 1000))

    # Lists are quicklist2 in Redis 7.4: packed, LZF-packed, plain, and multi-node forms.
    add("list-small", "list", 18, ("RPUSH", "src", b"a", b"bb", b"hello"))
    add("list-7bit-int", "list", 18, ("RPUSH", "src", b"0", b"127", b"128"))
    add("list-13bit-int", "list", 18, ("RPUSH", "src", b"-4096", b"4095"))
    add("list-wide-ints", "list", 18,
        ("RPUSH", "src", b"-32768", b"8388607", b"2147483647", b"9223372036854775807"))
    add("list-binary", "list", 18, ("RPUSH", "src", b"\x00\xff", b"a\x00b"))
    add("list-12bit-string", "list", 18, ("RPUSH", "src", stable_bytes(500, 4)))
    add("list-32bit-string", "list", 18, ("RPUSH", "src", stable_bytes(5000, 12)))
    add("list-lzf-listpack", "list", 18, ("RPUSH", "src", b"x" * 1000, b"x" * 1000))
    add("list-plain-node", "list", 18, ("RPUSH", "src", b"q" * 10000))
    add("list-multinode", "list", 18,
        ("RPUSH", "src", *[("item-%04d-" % i).encode() * 4 for i in range(700)]))

    # Hashes: listpack and hashtable thresholds, including compressed outer strings.
    add("hash-small", "hash", 16, ("HSET", "src", b"a", b"1", b"bb", b"hello"))
    add("hash-integers", "hash", 16,
        ("HSET", "src", b"1", b"-4096", b"32767", b"2147483647"))
    add("hash-binary", "hash", 16, ("HSET", "src", b"\x00f", b"v\xff"))
    add("hash-value-63", "hash", 16, ("HSET", "src", b"field", stable_bytes(63, 5)))
    add("hash-value-64", "hash", 16, ("HSET", "src", b"field", stable_bytes(64, 6)))
    add("hash-long-value", "hash", 4, ("HSET", "src", b"field", b"x" * 65))
    add("hash-lzf-expanded", "hash", 4, ("HSET", "src", b"field", b"z" * 1000))
    add("hash-many", "hash", 4,
        ("HSET", "src", *sum(([b"f%d" % i, b"v%d" % i] for i in range(513)), [])))
    add("hash-wide-binary", "hash", 4,
        ("HSET", "src", stable_bytes(80, 7), stable_bytes(200, 8)))

    # Sets: all intset widths, set-listpack, and hashtable promotion paths.
    add("set-int16", "set", 11, ("SADD", "src", b"-2", b"1", b"300"))
    add("set-int32", "set", 11, ("SADD", "src", b"-100000", b"100000"))
    add("set-int64", "set", 11,
        ("SADD", "src", b"-9223372036854775808", b"9223372036854775807"))
    add("set-intset-lzf", "set", 11, ("SADD", "src", *[str(i).encode() for i in range(500)]))
    add("set-listpack", "set", 20, ("SADD", "src", b"a", b"bb", b"hello"))
    add("set-listpack-binary", "set", 20, ("SADD", "src", b"\x00", b"a\xffb"))
    add("set-listpack-value64", "set", 20, ("SADD", "src", stable_bytes(64, 9), b"a"))
    add("set-long-value", "set", 2, ("SADD", "src", b"x" * 65, b"a"))
    add("set-many", "set", 2, ("SADD", "src", *[b"m%d" % i for i in range(129)]))
    add("set-expanded-lzf", "set", 2, ("SADD", "src", b"y" * 1000, b"other"))

    # Sorted sets: listpack numeric encodings and zset2 binary-double bodies.
    add("zset-small", "zset", 17, ("ZADD", "src", b"1.5", b"a", b"-2", b"bb"))
    add("zset-integer-scores", "zset", 17,
        ("ZADD", "src", b"0", b"zero", b"4095", b"high", b"-4096", b"low"))
    add("zset-fractions", "zset", 17,
        ("ZADD", "src", b"0.125", b"eighth", b"1e100", b"huge"))
    add("zset-subnormal", "zset", 17, ("ZADD", "src", b"5e-324", b"tiny"))
    add("zset-infinities", "zset", 17, ("ZADD", "src", b"-inf", b"lo", b"+inf", b"hi"))
    add("zset-binary", "zset", 17, ("ZADD", "src", b"3.25", b"a\x00\xff"))
    add("zset-member64", "zset", 17, ("ZADD", "src", b"1", stable_bytes(64, 10)))
    add("zset-long-member", "zset", 5, ("ZADD", "src", b"1.5", b"x" * 65))
    add("zset-many", "zset", 5,
        ("ZADD", "src", *sum(([str(i / 8.0).encode(), b"m%d" % i] for i in range(129)), [])))
    add("zset-expanded-binary", "zset", 5,
        ("ZADD", "src", b"-123.75", stable_bytes(100, 11)))
    add("zset-expanded-lzf", "zset", 5, ("ZADD", "src", b"7.5", b"z" * 1000))

    return cases


def read_full(client, kind, key):
    if kind == "string":
        return client.cmd("GET", key)
    if kind == "list":
        return client.cmd("LRANGE", key, "0", "-1")
    if kind == "hash":
        flat = client.cmd("HGETALL", key)
        if not isinstance(flat, list) or len(flat) % 2:
            return flat
        return sorted((flat[i], flat[i + 1]) for i in range(0, len(flat), 2))
    if kind == "set":
        value = client.cmd("SMEMBERS", key)
        return sorted(value) if isinstance(value, list) else value
    if kind == "zset":
        return client.cmd("ZRANGE", key, "0", "-1", "WITHSCORES")
    raise AssertionError("unknown kind %r" % kind)


def wait_ready(host, port, process, label):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("%s terminated during boot (status %s)" % (label, process.returncode))
        try:
            probe = Resp(host, port, timeout=0.2)
            answer = probe.cmd("PING")
            probe.close()
            if answer == b"PONG":
                return
        except (OSError, EOFError):
            time.sleep(0.03)
    raise RuntimeError("%s did not listen on %s:%d" % (label, host, port))


def ensure_port_free(host, port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.1)
    try:
        if probe.connect_ex((host, port)) == 0:
            raise RuntimeError("refusing to boot: %s:%d is already in use" % (host, port))
    finally:
        probe.close()


def boot_pair(args):
    ensure_port_free(args.host, args.target_port)
    ensure_port_free(args.host, args.oracle_port)
    logs = []
    processes = []
    try:
        for label, command in (
            ("target", ["taskset", "-c", "112-115", args.target_bin,
                        "--port", str(args.target_port), "--bind", args.host,
                        "--shards", "2", "--no-pin", "--atomic", str(args.atomic)]),
            ("oracle", ["taskset", "-c", "116-119", args.oracle_bin,
                        "--port", str(args.oracle_port), "--bind", args.host,
                        "--protected-mode", "no", "--save", "", "--appendonly", "no"]),
        ):
            log = tempfile.NamedTemporaryFile(prefix="wiredump-%s-" % label,
                                              suffix=".log", delete=False)
            logs.append(log)
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(args.host, args.target_port if label == "target" else args.oracle_port,
                       process, label)
        return processes, logs
    except Exception:
        stop_pair(processes, logs)
        raise


def stop_pair(processes, logs):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    retain_logs = any(process.returncode not in (0, -15) for process in processes)
    for log in logs:
        log.close()
        if retain_logs:
            print("server log retained at %s" % log.name, file=sys.stderr)
        else:
            os.unlink(log.name)


def run(args):
    target = Resp(args.host, args.target_port)
    oracle = Resp(args.host, args.oracle_port)
    oracle_dumps = []
    cells = 0
    try:
        expect(target.cmd("FLUSHALL"), b"OK", "target flush")
        expect(oracle.cmd("FLUSHALL"), b"OK", "oracle flush")
        for name, kind, expected_type, commands in build_cases():
            for client in (target, oracle):
                client.cmd("DEL", "src", "from-oracle", "from-tomo", "round")
            for command in commands:
                result = oracle.cmd(*command)
                if isinstance(result, RespError):
                    raise AssertionError("%s setup failed: %r" % (name, result))

            oracle_dump = oracle.cmd("DUMP", "src")
            if not isinstance(oracle_dump, bytes) or oracle_dump[0] != expected_type:
                raise AssertionError("%s oracle type: got %r wanted %d" %
                                     (name, oracle_dump[:1], expected_type))
            oracle_dumps.append(oracle_dump)
            expect(target.cmd("RESTORE", "from-oracle", "0", oracle_dump), b"OK",
                   name + " oracle->tomo restore")
            expect(read_full(target, kind, "from-oracle"), read_full(oracle, kind, "src"),
                   name + " oracle->tomo content")

            tomo_dump = target.cmd("DUMP", "from-oracle")
            if not isinstance(tomo_dump, bytes):
                raise AssertionError("%s tomo DUMP failed: %r" % (name, tomo_dump))
            expect(oracle.cmd("RESTORE", "from-tomo", "0", tomo_dump), b"OK",
                   name + " tomo->oracle restore")
            expect(read_full(oracle, kind, "from-tomo"),
                   read_full(target, kind, "from-oracle"), name + " tomo->oracle content")

            expect(target.cmd("RESTORE", "round", "0", tomo_dump), b"OK",
                   name + " tomo round trip")
            expect(read_full(target, kind, "round"), read_full(target, kind, "from-oracle"),
                   name + " tomo round content")
            cells += 1
            print("  ok   cell %02d %-24s oracle-type=%d tomo-type=%d" %
                  (cells, name, expected_type, tomo_dump[0]), flush=True)

        if cells < 40:
            raise AssertionError("only %d matrix cells fired" % cells)

        # TTL and retained option grammar. PTTL bounds prove that expiration was armed.
        payload = oracle_dumps[1]
        target.cmd("DEL", "ttl-rel", "ttl-abs", "option-key")
        expect(target.cmd("RESTORE", "ttl-rel", "5000", payload, "IDLETIME", "7"), b"OK",
               "relative TTL + IDLETIME")
        relative = target.cmd("PTTL", "ttl-rel")
        if not 3500 <= relative <= 5000:
            raise AssertionError("relative TTL not armed: %r" % relative)
        absolute = int(time.time() * 1000) + 5000
        expect(target.cmd("RESTORE", "ttl-abs", str(absolute), payload,
                          "ABSTTL", "FREQ", "9"), b"OK", "ABSTTL + FREQ")
        absolute_left = target.cmd("PTTL", "ttl-abs")
        if not 3500 <= absolute_left <= 5000:
            raise AssertionError("absolute TTL not armed: %r" % absolute_left)
        expect(target.cmd("RESTORE", "option-key", "0", payload), b"OK", "busy seed")
        expect_error(target.cmd("RESTORE", "option-key", "0", payload),
                     b"BUSYKEY Target key name already exists.", "BUSYKEY exact")
        expect(target.cmd("RESTORE", "option-key", "0", payload, "REPLACE"), b"OK",
               "REPLACE path")
        print("  ok   TTL/REPLACE/ABSTTL/IDLETIME/FREQ mechanisms fired", flush=True)

        checksum_error = b"ERR DUMP payload version or checksum are wrong"
        bad_format = b"ERR Bad data format"
        good = oracle_dumps[1]
        flipped = bytearray(good)
        flipped[1] ^= 1
        malformed = reseal(bytes([1, 2, 1]) + b"x")
        unsupported = reseal(b"\xff\x00")
        directed = [
            (bytes(flipped), checksum_error, "flipped byte"),
            (good[:-1], checksum_error, "truncated tail"),
            (good[:-10] + b"\xff\xff" + good[-8:], checksum_error, "wrong version"),
            (good[:-1] + bytes([good[-1] ^ 1]), checksum_error, "wrong CRC"),
            (unsupported, bad_format, "unsupported type"),
            (malformed, bad_format, "valid-CRC malformed body"),
        ]
        for payload, wanted, label in directed:
            target_reply = target.cmd("RESTORE", "corrupt", "0", payload, "REPLACE")
            oracle_reply = oracle.cmd("RESTORE", "corrupt", "0", payload, "REPLACE")
            expect_error(target_reply, wanted, label + " target")
            expect_error(oracle_reply, wanted, label + " oracle")
        print("  ok   directed corruptions matched exact oracle errors", flush=True)

        target.cmd("DEL", "stream-cut")
        expect(target.cmd("XADD", "stream-cut", "1-0", "f", "v"), b"1-0", "stream seed")
        expect_error(target.cmd("DUMP", "stream-cut"), b"ERR object could not be serialized",
                     "stream DUMP scope cut")

        rng = random.Random(0xD00F74)
        rejected = 0
        for iteration in range(1000):
            payload = bytearray(rng.choice(oracle_dumps))
            position = rng.randrange(len(payload) - 8)
            payload[position] ^= 1 << rng.randrange(8)
            answer = target.cmd("RESTORE", "fuzz", "0", bytes(payload), "REPLACE")
            if not isinstance(answer, RespError) or answer.message != checksum_error:
                raise AssertionError("fuzz %d was not rejected exactly: %r" % (iteration, answer))
            rejected += 1
        expect(target.cmd("PING"), b"PONG", "post-fuzz liveness")
        if rejected != 1000:
            raise AssertionError("fuzz rejection arm did not fire 1000 times")
        print("  ok   1000/1000 random corruptions rejected; target survived", flush=True)
        print("WIREDUMP PASS atomic=%d cells=%d corruptions=%d" %
              (args.atomic, cells, rejected), flush=True)
    finally:
        target.close()
        oracle.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("target_port", type=int)
    parser.add_argument("--oracle-port", type=int, default=7295)
    parser.add_argument("--atomic", type=int, choices=(0, 1), default=0)
    parser.add_argument("--boot", action="store_true")
    parser.add_argument("--target-bin", default="build/tomokv")
    parser.add_argument("--oracle-bin",
                        default="/tmp/claude-1000/redis74/src/redis-server")
    args = parser.parse_args()

    processes, logs = [], []
    try:
        if args.boot:
            processes, logs = boot_pair(args)
        run(args)
    finally:
        if args.boot:
            stop_pair(processes, logs)


if __name__ == "__main__":
    main()
