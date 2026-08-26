#!/usr/bin/env python3
"""Directed RESP2 pub/sub test. Usage: tests/pubsub.py HOST PORT"""

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


def expect_no_frame(conn, label, timeout=0.15):
    if select.select([conn.sock], [], [], timeout)[0]:
        raise AssertionError(f"{label}: unexpected frame {conn.read()!r}")


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

    # Shard subscription acknowledgements, duplicates, explicit/all unsubscribe, and CLIENT ssub.
    shard_controls = Conn(host, port)
    shard_client_id = shard_controls.command("CLIENT", "ID")
    shard_a, shard_b, shard_c = (
        f"{token}:shard:control:a", f"{token}:shard:control:b", f"{token}:shard:control:c")
    expect(shard_controls.command("SSUBSCRIBE", shard_a),
           [b"ssubscribe", shard_a.encode(), 1], "shard subscribe one")
    expect(shard_controls.command("SSUBSCRIBE", shard_b),
           [b"ssubscribe", shard_b.encode(), 2], "shard subscribe two")
    expect(shard_controls.command("SSUBSCRIBE", shard_a),
           [b"ssubscribe", shard_a.encode(), 2], "duplicate shard subscribe")
    expect(publisher.command("SPUBLISH", shard_a, "hello"), 1, "shard publish receiver count")
    expect(shard_controls.read(), [b"smessage", shard_a.encode(), b"hello"],
           "shard smessage frame")
    client_list = admin.command("CLIENT", "LIST").decode().splitlines()
    client_line = next((line for line in client_list if f"id={shard_client_id} " in line), None)
    if client_line is None or "ssub=2" not in client_line:
        raise AssertionError(f"CLIENT LIST shard count: {client_line!r}")
    missing_shard = f"{token}:shard:missing"
    expect(shard_controls.command("SUNSUBSCRIBE", missing_shard),
           [b"sunsubscribe", missing_shard.encode(), 2], "shard unsubscribe missing")
    expect(shard_controls.command("SUNSUBSCRIBE", shard_a),
           [b"sunsubscribe", shard_a.encode(), 1], "shard unsubscribe named")
    expect(shard_controls.command("SSUBSCRIBE", shard_a, shard_c),
           [b"ssubscribe", shard_a.encode(), 2], "shard resubscribe first")
    expect(shard_controls.read(), [b"ssubscribe", shard_c.encode(), 3],
           "shard resubscribe second")
    unsubscribe_all = [shard_controls.command("SUNSUBSCRIBE"),
                       shard_controls.read(), shard_controls.read()]
    if ({item[1] for item in unsubscribe_all} !=
            {shard_a.encode(), shard_b.encode(), shard_c.encode()} or
            {item[2] for item in unsubscribe_all} != {0, 1, 2} or
            any(item[0] != b"sunsubscribe" for item in unsubscribe_all)):
        raise AssertionError(f"SUNSUBSCRIBE all: {unsubscribe_all!r}")
    expect(shard_controls.command("SUNSUBSCRIBE"), [b"sunsubscribe", None, 0],
           "SUNSUBSCRIBE empty")
    shard_controls.close()

    # Regular exact, shard exact, and regular pattern namespaces never cross in either direction.
    namespace_channel = f"{token}:namespace:exact"
    regular_only = Conn(host, port)
    expect(regular_only.command("SUBSCRIBE", namespace_channel),
           [b"subscribe", namespace_channel.encode(), 1], "regular namespace subscribe")
    expect(publisher.command("SPUBLISH", namespace_channel, "shard"), 0,
           "SPUBLISH ignores regular exact")
    expect_no_frame(regular_only, "regular subscriber got shard publish")
    regular_only.close()

    shard_only = Conn(host, port)
    expect(shard_only.command("SSUBSCRIBE", namespace_channel),
           [b"ssubscribe", namespace_channel.encode(), 1], "shard namespace subscribe")
    expect(publisher.command("PUBLISH", namespace_channel, "regular"), 0,
           "PUBLISH ignores shard exact")
    expect_no_frame(shard_only, "shard subscriber got regular publish")
    shard_only.close()

    pattern_only = Conn(host, port)
    namespace_pattern = f"{token}:namespace:*"
    expect(pattern_only.command("PSUBSCRIBE", namespace_pattern),
           [b"psubscribe", namespace_pattern.encode(), 1], "namespace pattern subscribe")
    expect(publisher.command("SPUBLISH", namespace_channel, "pattern"), 0,
           "SPUBLISH ignores patterns")
    expect_no_frame(pattern_only, "pattern subscriber got shard publish")
    pattern_only.close()

    # Reply counts are namespace-scoped, while subscriber-mode exit uses their three-way total.
    mixed = Conn(host, port)
    mixed_a, mixed_b = f"{token}:mixed:a", f"{token}:mixed:b"
    mixed_pattern = f"{token}:mixed:p:*"
    mixed_s, mixed_t = f"{token}:mixed:s", f"{token}:mixed:t"
    expect(mixed.command("SUBSCRIBE", mixed_a), [b"subscribe", mixed_a.encode(), 1],
           "mixed regular one")
    expect(mixed.command("PSUBSCRIBE", mixed_pattern),
           [b"psubscribe", mixed_pattern.encode(), 2], "mixed pattern two")
    expect(mixed.command("SSUBSCRIBE", mixed_s), [b"ssubscribe", mixed_s.encode(), 1],
           "mixed shard one not three")
    expect(mixed.command("SUBSCRIBE", mixed_b), [b"subscribe", mixed_b.encode(), 3],
           "mixed regular count three")
    expect(mixed.command("SSUBSCRIBE", mixed_t), [b"ssubscribe", mixed_t.encode(), 2],
           "mixed shard count two")
    expect(mixed.command("PING"), [b"pong", b""], "shard subscriber PING")
    restricted_spublish = mixed.command("SPUBLISH", mixed_s, "blocked")
    if not isinstance(restricted_spublish, RespError) or "only (P|S)SUBSCRIBE" not in str(restricted_spublish):
        raise AssertionError(f"subscriber SPUBLISH restriction: {restricted_spublish!r}")
    expect(mixed.command("UNSUBSCRIBE", mixed_a, mixed_b),
           [b"unsubscribe", mixed_a.encode(), 2], "mixed unsubscribe regular first")
    expect(mixed.read(), [b"unsubscribe", mixed_b.encode(), 1],
           "mixed unsubscribe regular second")
    expect(mixed.command("PUNSUBSCRIBE", mixed_pattern),
           [b"punsubscribe", mixed_pattern.encode(), 0], "mixed unsubscribe pattern")
    still_restricted = mixed.command("SET", f"{token}:mixed:key", "value")
    if not isinstance(still_restricted, RespError):
        raise AssertionError(f"shard subscriptions did not retain subscriber mode: {still_restricted!r}")
    expect(mixed.command("SUNSUBSCRIBE", mixed_s, mixed_t),
           [b"sunsubscribe", mixed_s.encode(), 1], "mixed shard unsubscribe first")
    expect(mixed.read(), [b"sunsubscribe", mixed_t.encode(), 0],
           "mixed shard unsubscribe second")
    expect(mixed.command("SET", f"{token}:mixed:key", "value"), b"OK",
           "total subscription count exits mode")
    mixed.close()

    # RESET silently removes shard subscriptions and clears both introspection surfaces.
    reset_conn = Conn(host, port)
    reset_client_id = reset_conn.command("CLIENT", "ID")
    reset_channel = f"{token}:shard:reset"
    expect(reset_conn.command("SSUBSCRIBE", reset_channel),
           [b"ssubscribe", reset_channel.encode(), 1], "shard RESET subscribe")
    expect(reset_conn.command("RESET"), b"RESET", "shard RESET")
    expect_no_frame(reset_conn, "RESET emitted sunsubscribe")
    expect(admin.command("PUBSUB", "SHARDNUMSUB", reset_channel),
           [reset_channel.encode(), 0], "RESET shard cleanup")
    client_info = reset_conn.command("CLIENT", "INFO").decode()
    if f"id={reset_client_id} " not in client_info or "ssub=0" not in client_info:
        raise AssertionError(f"CLIENT INFO shard count: {client_info!r}")
    client_list = admin.command("CLIENT", "LIST").decode().splitlines()
    client_line = next((line for line in client_list if f"id={reset_client_id} " in line), None)
    if client_line is None or "ssub=0" not in client_line:
        raise AssertionError(f"CLIENT LIST reset shard count: {client_line!r}")
    reset_conn.close()

    # Shard introspection is separate, glob-filtered, and has no SHARDNUMPAT arm.
    introspect_regular = Conn(host, port)
    introspect_shard = Conn(host, port)
    regular_intro = f"{token}:introspect:regular"
    shard_intro_a = f"{token}:introspect:shard:a"
    shard_intro_b = f"{token}:introspect:shard:b"
    expect(introspect_regular.command("SUBSCRIBE", regular_intro),
           [b"subscribe", regular_intro.encode(), 1], "introspection regular subscribe")
    expect(introspect_shard.command("SSUBSCRIBE", shard_intro_a, shard_intro_b),
           [b"ssubscribe", shard_intro_a.encode(), 1], "introspection shard first")
    expect(introspect_shard.read(), [b"ssubscribe", shard_intro_b.encode(), 2],
           "introspection shard second")
    all_shard_channels = admin.command("PUBSUB", "SHARDCHANNELS")
    if not {shard_intro_a.encode(), shard_intro_b.encode()}.issubset(all_shard_channels):
        raise AssertionError(f"PUBSUB SHARDCHANNELS omitted active channels: {all_shard_channels!r}")
    shard_channels = admin.command("PUBSUB", "SHARDCHANNELS", f"{token}:introspect:*")
    if set(shard_channels) != {shard_intro_a.encode(), shard_intro_b.encode()}:
        raise AssertionError(f"PUBSUB SHARDCHANNELS namespace: {shard_channels!r}")
    expect(admin.command("PUBSUB", "SHARDCHANNELS", ""), [],
           "PUBSUB SHARDCHANNELS empty pattern")
    regular_channels = admin.command("PUBSUB", "CHANNELS", f"{token}:introspect:*")
    expect(regular_channels, [regular_intro.encode()], "PUBSUB CHANNELS excludes shard")
    expect(admin.command("PUBSUB", "SHARDNUMSUB", shard_intro_a, shard_intro_b, missing_shard),
           [shard_intro_a.encode(), 1, shard_intro_b.encode(), 1, missing_shard.encode(), 0],
           "PUBSUB SHARDNUMSUB")
    expect(admin.command("PUBSUB", "SHARDNUMSUB"), [], "PUBSUB SHARDNUMSUB empty")
    shardnumpat = admin.command("PUBSUB", "SHARDNUMPAT")
    if not isinstance(shardnumpat, RespError) or "Unknown subcommand" not in str(shardnumpat):
        raise AssertionError(f"PUBSUB SHARDNUMPAT unexpectedly exists: {shardnumpat!r}")
    help_reply = admin.command("PUBSUB", "HELP")
    if b"SHARDCHANNELS [<pattern>]" not in help_reply or b"SHARDNUMSUB [<shardchannel> ...]" not in help_reply:
        raise AssertionError(f"PUBSUB HELP omitted shard subcommands: {help_reply!r}")
    introspect_regular.close()
    introspect_shard.close()

    # A single command may span channel homes: no slot/CROSSSLOT semantics are imposed.
    multi_home = Conn(host, port)
    multi_channels = [f"{token}:multihome:{index}" for index in range(3)]
    expect(multi_home.command("SSUBSCRIBE", *multi_channels),
           [b"ssubscribe", multi_channels[0].encode(), 1], "multi-home ack one")
    expect(multi_home.read(), [b"ssubscribe", multi_channels[1].encode(), 2],
           "multi-home ack two")
    expect(multi_home.read(), [b"ssubscribe", multi_channels[2].encode(), 3],
           "multi-home ack three")
    for index, item in enumerate(multi_channels):
        expect(publisher.command("SPUBLISH", item, str(index)), 1,
               f"multi-home publish {index}")
        expect(multi_home.read(), [b"smessage", item.encode(), str(index).encode()],
               f"multi-home delivery {index}")
    multi_home.close()

    # N-way shard fanout and per-subscriber ordering mirrors the regular fanout arm.
    shard_fanout_channel = f"{token}:shard:fanout"
    shard_subscribers = []
    for index in range(nsubs):
        conn = Conn(host, port)
        expect(conn.command("SSUBSCRIBE", shard_fanout_channel),
               [b"ssubscribe", shard_fanout_channel.encode(), 1], f"shard subscribe {index}")
        shard_subscribers.append(conn)
    for sequence in range(nmessages):
        expect(publisher.command("SPUBLISH", shard_fanout_channel, str(sequence)), nsubs,
               f"SPUBLISH {sequence}")
    for index, conn in enumerate(shard_subscribers):
        for sequence in range(nmessages):
            expect(conn.read(), [b"smessage", shard_fanout_channel.encode(), str(sequence).encode()],
                   f"shard subscriber {index} message {sequence}")
        conn.close()

    # Subscription controls cannot be EXEC children in the owner-only transaction machinery.
    multi = Conn(host, port)
    expect(multi.command("MULTI"), b"OK", "MULTI before SSUBSCRIBE")
    forbidden_multi = multi.command("SSUBSCRIBE", f"{token}:multi")
    if not isinstance(forbidden_multi, RespError) or "not allowed inside a transaction" not in str(forbidden_multi):
        raise AssertionError(f"SSUBSCRIBE inside MULTI: {forbidden_multi!r}")
    expect(multi.command("DISCARD"), b"OK", "DISCARD after forbidden SSUBSCRIBE")
    multi.close()

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

    # Shard-publish while connections register and disconnect. Half close before reading the
    # acknowledgement, exercising the pending-command lifetime fence; half close immediately after.
    churn_channel = f"{token}:churn"
    errors = []
    start = threading.Event()

    def publish_loop():
        conn = Conn(host, port)
        try:
            start.wait()
            for sequence in range(500):
                result = conn.command("SPUBLISH", churn_channel, str(sequence))
                if not isinstance(result, int):
                    raise AssertionError(f"churn SPUBLISH returned {result!r}")
        except Exception as exc:  # surfaced in the main thread
            errors.append(exc)
        finally:
            conn.close()

    def churn_loop(worker):
        try:
            start.wait()
            for index in range(80):
                conn = Conn(host, port)
                conn.send("SSUBSCRIBE", churn_channel)
                if (index + worker) % 2:
                    expect(conn.read(), [b"ssubscribe", churn_channel.encode(), 1],
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
        "pubsubshard_channels", "pubsubshard_subscriptions",
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

    expect(admin.command("PUBSUB", "SHARDNUMSUB", churn_channel), [churn_channel.encode(), 0],
           "churn SHARDNUMSUB cleanup")
    admin.close()
    print(f"pubsub: PASS (regular_fanout={nsubs}, shard_fanout={nsubs}, "
          f"ordered_messages={nmessages}, shard_churn=320)")


if __name__ == "__main__":
    main()
