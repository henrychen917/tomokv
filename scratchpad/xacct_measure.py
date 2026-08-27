#!/usr/bin/env python3
"""Live reproduction harness for the XACCT lane.

Usage:
  scratchpad/xacct_measure.py HOST PORT stream [DEPTH ...]
  scratchpad/xacct_measure.py HOST PORT multi [K ...]
  scratchpad/xacct_measure.py HOST PORT multi-abort [K ...]

The timed stream interval contains only pipelined XADD commands and their replies.
The timed transaction interval starts immediately before sending EXEC and ends after
its complete reply is decoded; queuing is deliberately outside the interval.
"""

import socket
import statistics
import sys
import time


HOST = sys.argv[1]
PORT = int(sys.argv[2])


def frame(*args):
    values = [value if isinstance(value, bytes) else str(value).encode() for value in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n"
                     for value in values))


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=300)
        self.sock.settimeout(300)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind, value = line[:1], line[1:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            raise RuntimeError(value.decode(errors="replace"))
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return payload
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise ValueError("unsupported RESP prefix %r" % kind)

    def command(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()

    def pipeline(self, commands):
        self.sock.sendall(b"".join(frame(*command) for command in commands))
        return [self.read() for _ in commands]


def pipeline_chunks(client, commands, chunk=2000):
    for start in range(0, len(commands), chunk):
        part = commands[start:start + chunk]
        replies = client.pipeline(part)
        if len(replies) != len(part):
            raise AssertionError("short pipeline reply")


def prepare_pel(client, depth):
    if client.command("FLUSHDB") != b"OK":
        raise AssertionError("FLUSHDB failed")
    count = max(depth, 1)
    pipeline_chunks(client, [("XADD", "xacct:stream", "%d-0" % (index + 1), "f", "v")
                             for index in range(count)])
    group_id = "0" if depth else "$"
    if client.command("XGROUP", "CREATE", "xacct:stream", "g", group_id) != b"OK":
        raise AssertionError("XGROUP CREATE failed")
    if depth:
        delivered = client.command("XREADGROUP", "GROUP", "g", "c", "COUNT", depth,
                                   "STREAMS", "xacct:stream", ">")
        if len(delivered) != 1 or len(delivered[0][1]) != depth:
            raise AssertionError("XREADGROUP did not deliver requested PEL depth")
    summary = client.command("XPENDING", "xacct:stream", "g")
    if summary[0] != depth:
        raise AssertionError("PEL depth %r, wanted %d" % (summary[0], depth))
    return count + 1


def stream_ops(depth):
    if depth <= 0:
        return 20000
    if depth <= 100:
        return 10000
    if depth <= 1000:
        return 3000
    if depth <= 10000:
        return 500
    return 50


def measure_stream(client, depths):
    print("depth,ops,median_us_per_xadd,min_us_per_xadd,max_us_per_xadd", flush=True)
    for depth in depths:
        next_id = prepare_pel(client, depth)
        ops = stream_ops(depth)
        samples = []
        for repeat in range(5):
            commands = [("XADD", "xacct:stream", "%d-0" % ident, "f", "bench")
                        for ident in range(next_id, next_id + ops)]
            next_id += ops
            started = time.perf_counter_ns()
            replies = client.pipeline(commands)
            elapsed = time.perf_counter_ns() - started
            if len(replies) != ops or not all(isinstance(reply, bytes) for reply in replies):
                raise AssertionError("bad XADD benchmark reply")
            samples.append(elapsed / ops / 1000.0)
        print("%d,%d,%.3f,%.3f,%.3f" %
              (depth, ops, statistics.median(samples), min(samples), max(samples)), flush=True)


def measure_multi(client, sizes):
    print("keys,median_exec_us,min_exec_us,max_exec_us", flush=True)
    for count in sizes:
        samples = []
        for repeat in range(5):
            if client.command("FLUSHDB") != b"OK" or client.command("MULTI") != b"OK":
                raise AssertionError("transaction setup failed")
            for base in range(0, count, 2000):
                commands = [("SET", "xacct:multi:%d:%d" % (repeat, index), "v")
                            for index in range(base, min(count, base + 2000))]
                replies = client.pipeline(commands)
                if not all(reply == b"QUEUED" for reply in replies):
                    raise AssertionError("SET was not queued")
            started = time.perf_counter_ns()
            reply = client.command("EXEC")
            elapsed = time.perf_counter_ns() - started
            if len(reply) != count or not all(item == b"OK" for item in reply):
                raise AssertionError("bad EXEC reply")
            samples.append(elapsed / 1000.0)
        print("%d,%.3f,%.3f,%.3f" %
              (count, statistics.median(samples), min(samples), max(samples)), flush=True)


def measure_multi_abort(client, sizes):
    invalidator = Resp()
    print("keys,median_aborted_exec_us,min_aborted_exec_us,max_aborted_exec_us", flush=True)
    for count in sizes:
        samples = []
        for repeat in range(5):
            if client.command("FLUSHDB") != b"OK":
                raise AssertionError("FLUSHDB failed")
            if client.command("WATCH", "xacct:watched") != b"OK":
                raise AssertionError("WATCH failed")
            if invalidator.command("SET", "xacct:watched", repeat) != b"OK":
                raise AssertionError("watch invalidation failed")
            if client.command("MULTI") != b"OK":
                raise AssertionError("MULTI failed")
            for base in range(0, count, 2000):
                commands = [("SET", "xacct:multi:%d:%d" % (repeat, index), "v")
                            for index in range(base, min(count, base + 2000))]
                replies = client.pipeline(commands)
                if not all(reply == b"QUEUED" for reply in replies):
                    raise AssertionError("SET was not queued")
            started = time.perf_counter_ns()
            reply = client.command("EXEC")
            elapsed = time.perf_counter_ns() - started
            if reply is not None or client.command("DBSIZE") != 1:
                raise AssertionError("WATCH did not abort before transaction writes")
            samples.append(elapsed / 1000.0)
        print("%d,%.3f,%.3f,%.3f" %
              (count, statistics.median(samples), min(samples), max(samples)), flush=True)
    invalidator.file.close()
    invalidator.sock.close()


def main():
    if len(sys.argv) < 4 or sys.argv[3] not in ("stream", "multi", "multi-abort"):
        raise SystemExit(__doc__)
    client = Resp()
    try:
        if sys.argv[3] == "stream":
            depths = [int(value) for value in sys.argv[4:]] or [0, 100, 1000, 10000, 100000]
            measure_stream(client, depths)
        elif sys.argv[3] == "multi":
            sizes = [int(value) for value in sys.argv[4:]] or [100, 1000, 5000, 10000]
            measure_multi(client, sizes)
        else:
            sizes = [int(value) for value in sys.argv[4:]] or [100, 1000, 5000, 10000]
            measure_multi_abort(client, sizes)
    finally:
        client.file.close()
        client.sock.close()


if __name__ == "__main__":
    main()
