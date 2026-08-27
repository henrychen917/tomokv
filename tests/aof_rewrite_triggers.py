#!/usr/bin/env python3
"""Live rewrite knobs, INFO observability, auto trigger, and retry limiter battery."""

import json
import os
import socket
import sys
import time


if len(sys.argv) != 7 or sys.argv[3] not in ("run", "verify"):
    raise SystemExit(
        "usage: tests/aof_rewrite_triggers.py HOST PORT run|verify STATE DIR ATOMIC")

HOST, PORT = sys.argv[1], int(sys.argv[2])
MODE, STATE_PATH, DIRECTORY, ATOMIC = sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])


class RespError(RuntimeError):
    pass


def encode(args):
    out = b"*%d\r\n" % len(args)
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return out


class Resp:
    def __init__(self, timeout=10):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.sock.makefile("rb")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("server closed connection")
        kind = line[:1]
        if kind == b"-":
            raise RespError(line[1:-2].decode(errors="replace"))
        if kind == b"+":
            return line[1:-2]
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            value = self.stream.read(size)
            if self.stream.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return value
        if kind == b"*":
            count = int(line[1:-2])
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("invalid RESP reply %r" % line[:40])

    def command(self, *args):
        self.sock.sendall(encode(args))
        return self.read()

    def send_only(self, *args):
        self.sock.sendall(encode(args))


def info(client):
    body = client.command("INFO", "Persistence").decode()
    result = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name.startswith("aof_"):
            result[name] = int(value) if value.isdigit() else value
    return result


def wait_info(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        client = None
        try:
            client = Resp(timeout=0.5)
            last = info(client)
            if predicate(last):
                return last
        except (OSError, EOFError, RespError):
            pass
        finally:
            if client:
                client.close()
        time.sleep(0.02)
    raise AssertionError("INFO condition timed out: %r" % last)


def expect_error(client, *args):
    try:
        client.command(*args)
    except RespError:
        return
    raise AssertionError("command unexpectedly succeeded: %r" % (args,))


def pipeline_sets(client, prefix, count, width, expected):
    for begin in range(0, count, width):
        commands = []
        for index in range(begin, min(begin + width, count)):
            key = "%s:%06d" % (prefix, index)
            value = ("value-%06d:" % index).encode() + bytes([65 + index % 26]) * 180
            expected[key] = value.decode("ascii")
            commands.append(("SET", key, value))
        client.sock.sendall(b"".join(encode(command) for command in commands))
        for _ in commands:
            if client.read() != b"OK":
                raise AssertionError("SET pipeline failed")


def pipeline_script_sets(client, prefix, count, width, expected):
    source = "return redis.call('SET', KEYS[1], ARGV[1])"
    for begin in range(0, count, width):
        commands = []
        for index in range(begin, min(begin + width, count)):
            key = "%s:%06d" % (prefix, index)
            value = ("value-%06d:" % index).encode() + bytes([65 + index % 26]) * 180
            expected[key] = value.decode("ascii")
            commands.append(("EVAL", source, "1", key, value))
        client.sock.sendall(b"".join(encode(command) for command in commands))
        for _ in commands:
            if client.read() != b"OK":
                raise AssertionError("EVAL SET pipeline failed")


def wait_marker(marker, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(marker, "r", encoding="ascii") as source:
                if source.read().strip() == "before-manifest":
                    return
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    raise AssertionError("rewrite pause marker did not appear")


def observe_in_progress(pool):
    observed = None
    for client in pool:
        try:
            client.sock.settimeout(0.25)
            candidate = info(client)
            if candidate.get("aof_rewrite_in_progress") == 1:
                observed = candidate
                break
        except (OSError, EOFError, RespError):
            continue
    if observed is None:
        raise AssertionError("aof_rewrite_in_progress was not observed as 1")
    if observed.get("aof_rewrite_scheduled") not in (0, 1):
        raise AssertionError("rewrite scheduled field is missing")
    if observed.get("aof_pending_rewrite") not in (0, 1):
        raise AssertionError("pending rewrite field is missing")
    return observed


def verify_values(expected):
    client = Resp()
    try:
        items = sorted(expected.items())
        for begin in range(0, len(items), 64):
            chunk = items[begin:begin + 64]
            client.sock.sendall(encode(["MGET"] + [key for key, _ in chunk]))
            got = client.read()
            want = [value.encode() for _, value in chunk]
            if got != want:
                raise AssertionError("recovered trigger state differs at %d" % begin)
    finally:
        client.close()


if MODE == "verify":
    with open(STATE_PATH, "r", encoding="utf-8") as source:
        state = json.load(source)
    verify_values(state["values"])
    print("AOF TRIGGER RECOVERY PASS: atomic=%d keys=%d" % (ATOMIC, len(state["values"])))
    sys.exit(0)


controller = Resp()
pool = [Resp(timeout=2) for _ in range(24)]
appenddir = os.path.join(DIRECTORY, "appendonlydir")
marker = os.path.join(appenddir, "debug-aof-rewrite-stage")
expected = {}
if controller.command("CONFIG", "GET", "appendonly") != [b"appendonly", b"yes"]:
    raise AssertionError("trigger battery was not purpose-booted with appendonly yes")
if controller.command("CONFIG", "GET", "atomic") != [b"atomic", str(ATOMIC).encode()]:
    raise AssertionError("atomic purpose boot differs")
if controller.command("CONFIG", "GET", "auto-aof-rewrite-percentage") != [
        b"auto-aof-rewrite-percentage", b"0"]:
    raise AssertionError("auto rewrite was not disabled at boot")

expect_error(controller, "CONFIG", "SET", "auto-aof-rewrite-percentage", "-1")
expect_error(controller, "CONFIG", "SET", "auto-aof-rewrite-percentage", "4294967296")
expect_error(controller, "CONFIG", "SET", "auto-aof-rewrite-min-size", "1.5mb")

pipeline_sets(controller, "trigger:base", 768, 48, expected)
if controller.command("DEBUG", "AOF-REWRITE-PAUSE", "before-manifest") != b"OK":
    raise AssertionError("could not arm manual rewrite pause")
manual_before = info(controller)
controller.send_only("BGREWRITEAOF")
wait_marker(marker)
manual_observed = observe_in_progress(pool)
if manual_observed.get("aof_rewrite_requests", 0) <= manual_before.get("aof_rewrite_requests", 0):
    raise AssertionError("manual rewrite request counter did not fire")
os.unlink(marker)
manual_after = wait_info(
    lambda values: values.get("aof_rewrite_completions", 0) >
                   manual_before.get("aof_rewrite_completions", 0))
if manual_after.get("aof_last_bgrewrite_status") != "ok" or manual_after.get("aof_base_size", 0) == 0:
    raise AssertionError("manual rewrite observability did not publish success: %r" % manual_after)

# Three directed create failures arm the Redis-shaped 1-minute retry limiter.
controller.close()
controller = Resp()
if controller.command("CONFIG", "SET", "auto-aof-rewrite-percentage", "0") != b"OK":
    raise AssertionError("could not disable auto rewrite")
os.chmod(appenddir, 0o500)
try:
    failure_start = info(controller).get("aof_rewrite_failures", 0)
    for attempt in range(3):
        client = Resp()
        try:
            response = client.command("BGREWRITEAOF")
            if response != b"Background append only file rewriting started":
                raise AssertionError("failure rewrite was not scheduled")
        finally:
            client.close()
        wait_info(lambda values, target=failure_start + attempt + 1:
                  values.get("aof_rewrite_failures", 0) >= target)
    limited = wait_info(lambda values:
                        values.get("aof_rewrite_consecutive_failures", 0) >= 3)
    auto_before = limited.get("aof_auto_rewrite_triggers", 0)
    if controller.command("CONFIG", "SET",
                          "auto-aof-rewrite-percentage", "1",
                          "auto-aof-rewrite-min-size", "1kb") != b"OK":
        raise AssertionError("live auto rewrite CONFIG SET failed")
    pipeline_sets(controller, "trigger:limited", 96, 32, expected)
    limited = wait_info(lambda values:
                        values.get("aof_auto_rewrite_backoff_skips", 0) > 0)
    if limited.get("aof_auto_rewrite_triggers", 0) != auto_before:
        raise AssertionError("auto rewrite bypassed the retry limiter")
finally:
    os.chmod(appenddir, 0o700)

# A successful manual rewrite bypasses and clears the limiter.
controller.close()
controller = Resp()
if controller.command("CONFIG", "SET", "auto-aof-rewrite-percentage", "0") != b"OK":
    raise AssertionError("could not disable auto rewrite for limiter recovery")
recovery_before = info(controller)
controller.send_only("BGREWRITEAOF")
recovery_after = wait_info(
    lambda values: values.get("aof_rewrite_completions", 0) >
                   recovery_before.get("aof_rewrite_completions", 0))
if recovery_after.get("aof_rewrite_consecutive_failures") != 0:
    raise AssertionError("successful rewrite did not clear the limiter")

# Accumulate growth exclusively through script post-images with auto work exactly disabled, then
# enable both knobs live and observe the automatic rewrite at a held completion boundary.
controller.close()
controller = Resp()
pipeline_script_sets(controller, "trigger:auto-script", 384, 48, expected)
grown = wait_info(lambda values:
                  values.get("aof_current_size", 0) >
                  recovery_after.get("aof_rewrite_base_size", 0) * 6 // 5)
auto_start = grown.get("aof_auto_rewrite_triggers", 0)
completion_start = grown.get("aof_rewrite_completions", 0)
base_start = grown.get("aof_base_size", 0)
if controller.command("DEBUG", "AOF-REWRITE-PAUSE", "before-manifest") != b"OK":
    raise AssertionError("could not arm auto rewrite pause")
controller.send_only("CONFIG", "SET",
                     "auto-aof-rewrite-percentage", "20",
                     "auto-aof-rewrite-min-size", "1kb")
wait_marker(marker)
auto_observed = observe_in_progress(pool)
if auto_observed.get("aof_auto_rewrite_triggers", 0) <= auto_start:
    raise AssertionError("automatic rewrite trigger counter did not fire")
os.unlink(marker)
auto_after = wait_info(lambda values:
                       values.get("aof_rewrite_completions", 0) > completion_start)
if auto_after.get("aof_base_size", 0) <= base_start:
    raise AssertionError("automatic rewrite did not replace the BASE")
if auto_after.get("aof_current_size", 0) >= grown.get("aof_current_size", 0):
    raise AssertionError("automatic rewrite did not reset current size")
if auto_after.get("aof_history_unlinks", 0) == 0:
    raise AssertionError("history unlink counter did not fire")

controller.close()
controller = Resp()
values = controller.command("CONFIG", "GET", "auto-aof-rewrite-*")
if values != [b"auto-aof-rewrite-percentage", b"20",
              b"auto-aof-rewrite-min-size", b"1024"]:
    raise AssertionError("live auto rewrite CONFIG GET differs: %r" % (values,))

with open(STATE_PATH + ".tmp", "w", encoding="utf-8") as target:
    json.dump({"values": expected}, target, sort_keys=True)
os.replace(STATE_PATH + ".tmp", STATE_PATH)
verify_values(expected)
time.sleep(2)
print("AOF TRIGGER PASS: atomic=%d script_growth=384 requests=%d completions=%d "
      "auto=%d failures=%d backoff=%d" % (
    ATOMIC, auto_after["aof_rewrite_requests"], auto_after["aof_rewrite_completions"],
    auto_after["aof_auto_rewrite_triggers"], auto_after["aof_rewrite_failures"],
    auto_after["aof_auto_rewrite_backoff_skips"]))

for client in pool:
    client.close()
controller.close()
