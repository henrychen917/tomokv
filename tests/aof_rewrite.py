#!/usr/bin/env python3
"""Directed AOF rewrite, manifest, recovery, and corruption checks."""

import json
import os
import socket
import struct
import sys
import time


HOST, PORT, MODE = sys.argv[1], int(sys.argv[2]), sys.argv[3]


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
    if kind == b"-":
        raise RuntimeError(line[1:-2].decode(errors="replace"))
    if kind == b"+":
        return line[1:-2]
    if kind == b":":
        return int(line[1:-2])
    if kind == b"$":
        length = int(line[1:-2])
        if length == -1:
            return None
        value = stream.read(length)
        if stream.read(2) != b"\r\n":
            raise ValueError("bad bulk terminator")
        return value
    if kind == b"*":
        length = int(line[1:-2])
        return None if length == -1 else [read_reply(stream) for _ in range(length)]
    raise ValueError("unknown RESP reply %r" % line[:32])


def connect():
    sock = socket.create_connection((HOST, PORT), timeout=30)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock, sock.makefile("rb")


def command(sock, stream, *args):
    sock.sendall(encode(args))
    return read_reply(stream)


def pipeline(sock, stream, commands, width=64):
    for begin in range(0, len(commands), width):
        group = commands[begin:begin + width]
        sock.sendall(b"".join(encode(item) for item in group))
        for _ in group:
            reply = read_reply(stream)
            if reply not in (b"OK", 1):
                raise AssertionError("unexpected write reply %r" % (reply,))


def base_value(index):
    prefix = ("base-%06d:" % index).encode()
    return prefix + bytes([65 + index % 26]) * (256 - len(prefix))


def post_value(index):
    return ("post-%06d" % index).encode()


def group_value(group, member):
    return ("group-%03d-%d" % (group, member)).encode()


def load_state(path):
    with open(path, "r", encoding="utf-8") as source:
        return json.load(source)


def save_state(path, state):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as target:
        json.dump(state, target, sort_keys=True)
    os.replace(temp, path)


def parse_manifest(directory):
    path = os.path.join(directory, "appendonlydir", "appendonly.aof.manifest")
    with open(path, "r", encoding="ascii") as source:
        lines = [line.strip() for line in source if line.strip()]
    if not lines or lines[0] != "TOMOAOF-MANIFEST 1":
        raise AssertionError("invalid manifest header")
    base = []
    increments = []
    for line in lines[1:]:
        fields = line.split()
        if fields[0] != "file":
            continue
        if fields[4:6] == ["type", "b"]:
            base.append((fields[1], int(fields[3])))
        elif fields[4:6] == ["type", "i"]:
            increments.append((fields[1], int(fields[3])))
    return path, base, increments


def wait_final_manifest(directory, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = parse_manifest(directory)
            if len(result[1]) == 1 and len(result[2]) == 1:
                return result
        except (FileNotFoundError, AssertionError, ValueError):
            pass
        time.sleep(0.02)
    raise AssertionError("rewrite did not publish a final manifest")


def verify_state(sock, stream, state):
    commands = []
    expected = []
    for index in range(state["base_count"]):
        commands.append(["GET", "rw:base:%06d" % index])
        expected.append(base_value(index))
    for index in range(state.get("post_count", 0)):
        commands.append(["GET", "rw:post:%06d" % index])
        expected.append(post_value(index))
    for group in range(state["groups"]):
        for member in range(8):
            commands.append(["GET", "rw:group:%03d:%d" % (group, member)])
            expected.append(group_value(group, member))
    for begin in range(0, len(commands), 64):
        chunk = commands[begin:begin + 64]
        sock.sendall(b"".join(encode(item) for item in chunk))
        for offset, want in enumerate(expected[begin:begin + len(chunk)]):
            got = read_reply(stream)
            if got != want:
                raise AssertionError("state differs at %d: %r != %r" %
                                     (begin + offset, got, want))


def checksum(data):
    value = 1469598103934665603
    for byte in data:
        value ^= byte
        value = (value * 1099511628211) & 0xffffffffffffffff
    return value


def rewrite_frame_checksums(data, frame):
    length = struct.unpack_from("<I", data, frame + 16)[0]
    payload = frame + 40
    struct.pack_into("<Q", data, frame + 24, checksum(data[payload:payload + length]))
    struct.pack_into("<Q", data, frame + 32, checksum(data[frame:frame + 32]))


def corrupt(directory, kind):
    manifest_path, base, increments = parse_manifest(directory)
    appenddir = os.path.dirname(manifest_path)
    if kind == "manifest":
        with open(manifest_path, "ab") as target:
            target.write(b"invalid manifest line\n")
        return
    if kind == "base":
        path = os.path.join(appenddir, base[0][0])
        data = bytearray(open(path, "rb").read())
        data[64] ^= 0x80
        with open(path, "wb") as target:
            target.write(data)
        return
    path = os.path.join(appenddir, increments[-1][0])
    data = bytearray(open(path, "rb").read())
    frame = 80
    found = False
    while frame + 40 <= len(data):
        sid = struct.unpack_from("<I", data, frame + 4)[0]
        length = struct.unpack_from("<I", data, frame + 16)[0]
        payload = frame + 40
        if payload + length > len(data):
            break
        record_kind = data[payload + 4] if length >= 40 else 0
        if kind == "record-length" and sid != 0xffffffff and record_kind in (1, 2, 5, 6):
            struct.pack_into("<Q", data, payload + 16, 0xffffffffffffffff)
            rewrite_frame_checksums(data, frame)
            found = True
            break
        if kind == "group-vector" and sid == 0xffffffff and record_kind == 7:
            struct.pack_into("<I", data, payload + 40, 0)
            rewrite_frame_checksums(data, frame)
            found = True
            break
        frame = payload + length
    if not found:
        raise AssertionError("did not find frame for %s corruption" % kind)
    with open(path, "wb") as target:
        target.write(data)


if MODE == "corrupt":
    corrupt(sys.argv[4], sys.argv[5])
    print("AOF REWRITE CORRUPTION PREP PASS: %s" % sys.argv[5])
    sys.exit(0)


sock, stream = connect()
try:
    if MODE == "populate":
        state_path, count = sys.argv[4], int(sys.argv[5])
        state = {"base_count": count, "post_count": 0, "groups": 32}
        writes = [["SET", "rw:base:%06d" % index, base_value(index)]
                  for index in range(count)]
        pipeline(sock, stream, writes)
        groups = []
        for group in range(state["groups"]):
            item = ["MSET"]
            for member in range(8):
                item += ["rw:group:%03d:%d" % (group, member), group_value(group, member)]
            groups.append(item)
        pipeline(sock, stream, groups, 8)
        save_state(state_path, state)
        print("AOF REWRITE POPULATE PASS: keys=%d groups=%d" % (count, state["groups"]))
    elif MODE == "rewrite":
        state_path, directory = sys.argv[4], sys.argv[5]
        state = load_state(state_path)
        response = command(sock, stream, "BGREWRITEAOF")
        if response != b"Background append only file rewriting started":
            raise AssertionError("unexpected BGREWRITEAOF reply %r" % response)
        state["post_count"] = 512
        writes = [["SET", "rw:post:%06d" % index, post_value(index)]
                  for index in range(state["post_count"])]
        pipeline(sock, stream, writes)
        wait_final_manifest(directory)
        # These groups are deliberately after the cut so the active INCR contains GCMT records.
        groups = []
        for group in range(state["groups"]):
            item = ["MSET"]
            for member in range(8):
                item += ["rw:group:%03d:%d" % (group, member), group_value(group, member)]
            groups.append(item)
        pipeline(sock, stream, groups, 8)
        save_state(state_path, state)
        verify_state(sock, stream, state)
        print("AOF REWRITE LIVE PASS: base=%d post=%d" %
              (state["base_count"], state["post_count"]))
    elif MODE == "verify":
        state = load_state(sys.argv[4])
        verify_state(sock, stream, state)
        print("AOF REWRITE RECOVERY PASS: base=%d post=%d groups=%d" %
              (state["base_count"], state.get("post_count", 0), state["groups"]))
    elif MODE == "manifest":
        directory = sys.argv[4]
        manifest_path, base, increments = parse_manifest(directory)
        if len(base) != 1 or len(increments) != 1:
            raise AssertionError("manifest is not one BASE plus one INCR")
        appenddir = os.path.dirname(manifest_path)
        referenced = {base[0][0], increments[0][0], os.path.basename(manifest_path)}
        actual = {name for name in os.listdir(appenddir)
                  if name.endswith((".base.tomo", ".incr.tomo", ".manifest"))}
        if actual != referenced:
            raise AssertionError("history remains: %r != %r" % (actual, referenced))
        if os.path.getsize(os.path.join(appenddir, base[0][0])) <= 80:
            raise AssertionError("base snapshot did not capture data")
        print("AOF REWRITE MANIFEST PASS: base_seq=%d incr_seq=%d" %
              (base[0][1], increments[0][1]))
    elif MODE == "pause":
        stage = sys.argv[4]
        if command(sock, stream, "DEBUG", "AOF-REWRITE-PAUSE", stage) != b"OK":
            raise AssertionError("could not arm rewrite pause")
        # before-mark may deliberately park the same IO thread that owns this connection before
        # it transmits the already-staged reply. The stage marker below is the non-vacuous proof
        # that this fire-and-observe request was accepted and reached the requested boundary.
        sock.sendall(encode(["BGREWRITEAOF"]))
        print("AOF REWRITE PAUSE ARMED: %s" % stage)
    else:
        raise SystemExit("unknown mode %s" % MODE)
finally:
    sock.close()
