#!/usr/bin/env python3
"""Directed RESP2 pub/sub test. Usage: tests/pubsub.py HOST PORT"""

import os
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
    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
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
            assert self.file.read(2) == b"\r\n"
            return payload
        if prefix == b"*":
            size = int(value)
            if size == -1:
                return None
            return [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")

    def close(self, reset=False):
        if self.sock is None:
            return
        if reset:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.file.close()
        self.sock.close()
        self.sock = None


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")


def info_stats(conn):
    raw = conn.command("INFO", "STATS")
    if not isinstance(raw, bytes):
        raise AssertionError(f"INFO STATS returned {raw!r}")
    result = {}
    for line in raw.decode().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key] = value
    return result


def main():
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} HOST PORT")
    host, port = sys.argv[1], int(sys.argv[2])
    token = f"tomo-pubsub-{os.getpid()}-{time.time_ns()}"
    channel = f"{token}:fanout"
    admin = Conn(host, port)
    publisher = Conn(host, port)
    subscribers = []

    # N-way fanout and per-subscriber ordering.
    nsubs, nmessages = 24, 40
    for index in range(nsubs):
        conn = Conn(host, port)
        expect(conn.command("SUBSCRIBE", channel),
               [b"subscribe", channel.encode(), 1], f"subscribe {index}")
        subscribers.append(conn)
    expect(admin.command("PUBSUB", "NUMSUB", channel, f"{token}:missing"),
           [channel.encode(), nsubs, f"{token}:missing".encode(), 0], "PUBSUB NUMSUB")
    channels = admin.command("PUBSUB", "CHANNELS", f"{token}:*")
    if channel.encode() not in channels:
        raise AssertionError(f"PUBSUB CHANNELS omitted {channel!r}: {channels!r}")
    expect(admin.command("PUBSUB", "CHANNELS", ""), [], "PUBSUB CHANNELS empty pattern")

    for sequence in range(nmessages):
        expect(publisher.command("PUBLISH", channel, str(sequence)), nsubs,
               f"PUBLISH {sequence}")
    for index, conn in enumerate(subscribers):
        for sequence in range(nmessages):
            expect(conn.read(), [b"message", channel.encode(), str(sequence).encode()],
                   f"subscriber {index} message {sequence}")

    # Exact and both pattern arms, including subscriber-mode framing/restrictions.
    arms = Conn(host, port)
    arm_channel = f"{token}:news:42"
    expect(arms.command("SUBSCRIBE", arm_channel), [b"subscribe", arm_channel.encode(), 1],
           "exact arm")
    expect(arms.command("PSUBSCRIBE", f"{token}:news:*", f"{token}:*:42"),
           [b"psubscribe", f"{token}:news:*".encode(), 2], "pattern arm one")
    expect(arms.read(), [b"psubscribe", f"{token}:*:42".encode(), 3], "pattern arm two")
    expect(admin.command("PUBSUB", "NUMPAT"), 2, "PUBSUB NUMPAT")
    expect(publisher.command("PUBLISH", arm_channel, "payload"), 3, "three delivery arms")
    deliveries = [arms.read(), arms.read(), arms.read()]
    wanted = {
        (b"message", arm_channel.encode(), b"payload"),
        (b"pmessage", f"{token}:news:*".encode(), arm_channel.encode(), b"payload"),
        (b"pmessage", f"{token}:*:42".encode(), arm_channel.encode(), b"payload"),
    }
    if {tuple(item) for item in deliveries} != wanted:
        raise AssertionError(f"pattern deliveries: {deliveries!r}")
    expect(arms.command("PING", "hello"), [b"pong", b"hello"], "subscriber PING")
    restricted = arms.command("SET", f"{token}:key", "value")
    if not isinstance(restricted, RespError) or "only (P|S)SUBSCRIBE" not in str(restricted):
        raise AssertionError(f"subscriber restriction: {restricted!r}")

    # RESET unregisters every exact/pattern arm and leaves subscriber mode.
    expect(arms.command("RESET"), b"RESET", "subscriber RESET")
    expect(arms.command("SET", f"{token}:after-reset", "ok"), b"OK", "command after RESET")
    expect(admin.command("PUBSUB", "NUMSUB", arm_channel), [arm_channel.encode(), 0],
           "RESET exact cleanup")

    # Directed unsubscribe variants, including the no-argument "all" forms and cumulative counts.
    controls = Conn(host, port)
    control_a, control_b = f"{token}:control:a", f"{token}:control:b"
    expect(controls.command("SUBSCRIBE", control_a, control_b),
           [b"subscribe", control_a.encode(), 1], "multi subscribe one")
    expect(controls.read(), [b"subscribe", control_b.encode(), 2], "multi subscribe two")
    expect(controls.command("UNSUBSCRIBE", control_a),
           [b"unsubscribe", control_a.encode(), 1], "named unsubscribe")
    expect(controls.command("UNSUBSCRIBE"),
           [b"unsubscribe", control_b.encode(), 0], "unsubscribe all")
    pattern_a, pattern_b = f"{token}:pa:*", f"{token}:pb:*"
    expect(controls.command("PSUBSCRIBE", pattern_a, pattern_b),
           [b"psubscribe", pattern_a.encode(), 1], "multi psubscribe one")
    expect(controls.read(), [b"psubscribe", pattern_b.encode(), 2], "multi psubscribe two")
    expect(controls.command("PUNSUBSCRIBE", pattern_a),
           [b"punsubscribe", pattern_a.encode(), 1], "named punsubscribe")
    expect(controls.command("PUNSUBSCRIBE"),
           [b"punsubscribe", pattern_b.encode(), 0], "punsubscribe all")
    controls.close()

    for conn in subscribers:
        conn.close()
    subscribers.clear()

    # Publish while connections are registering and disconnecting. Half close before reading the
    # acknowledgement, exercising the pending-command lifetime fence; half close immediately after.
    churn_channel = f"{token}:churn"
    errors = []
    start = threading.Event()

    def publish_loop():
        conn = Conn(host, port)
        try:
            start.wait()
            for sequence in range(500):
                result = conn.command("PUBLISH", churn_channel, str(sequence))
                if not isinstance(result, int):
                    raise AssertionError(f"churn PUBLISH returned {result!r}")
        except Exception as exc:  # surfaced in the main thread
            errors.append(exc)
        finally:
            conn.close()

    def churn_loop(worker):
        try:
            start.wait()
            for index in range(80):
                conn = Conn(host, port)
                conn.send("SUBSCRIBE", churn_channel)
                if (index + worker) % 2:
                    expect(conn.read(), [b"subscribe", churn_channel.encode(), 1],
                           f"churn ack {worker}/{index}")
                conn.close(reset=True)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=publish_loop)]
    threads += [threading.Thread(target=churn_loop, args=(worker,)) for worker in range(4)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]

    arms.close()
    publisher.close()
    zero_keys = (
        "pubsub_channels", "pubsub_subscriptions", "pubsub_patterns",
        "pubsub_home_entries", "pubsub_inflight", "pubsub_pending_commands",
    )
    deadline = time.monotonic() + 10
    while True:
        stats = info_stats(admin)
        if all(stats.get(key) == "0" for key in zero_keys):
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                "pub/sub gauges did not drain: " +
                ", ".join(f"{key}={stats.get(key)}" for key in zero_keys))
        time.sleep(0.02)

    expect(admin.command("PUBSUB", "NUMSUB", churn_channel), [churn_channel.encode(), 0],
           "churn NUMSUB cleanup")
    admin.close()
    print(f"pubsub: PASS (fanout={nsubs}, ordered_messages={nmessages}, churn=320)")


if __name__ == "__main__":
    main()
