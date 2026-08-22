#!/usr/bin/env python3
"""Live deadlock/escape test for uring2 purchased batching.

The target is deliberately larger than the complete live connection set. Each
test connection holds exactly one PING reply outstanding, so a correct server
must time out and submit short rather than wait for an impossible full batch.
"""

import argparse
import select
import socket
import time


class RespConnection:
    def __init__(self, host, port, timeout):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = bytearray()

    def close(self):
        self.sock.close()

    def send(self, *parts):
        encoded = [p.encode() if isinstance(p, str) else p for p in parts]
        frame = [f"*{len(encoded)}\r\n".encode()]
        for part in encoded:
            frame.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
        self.sock.sendall(b"".join(frame))

    def _line(self):
        while True:
            end = self.buf.find(b"\r\n")
            if end >= 0:
                line = bytes(self.buf[:end])
                del self.buf[: end + 2]
                return line
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("server closed the connection")
            self.buf.extend(chunk)

    def _bytes(self, count):
        while len(self.buf) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("server closed the connection")
            self.buf.extend(chunk)
        value = bytes(self.buf[:count])
        del self.buf[:count]
        return value

    def read(self):
        prefix = self._bytes(1)
        if prefix == b"+":
            return self._line().decode()
        if prefix == b"-":
            raise RuntimeError(self._line().decode(errors="replace"))
        if prefix == b":":
            return int(self._line())
        if prefix == b"$":
            length = int(self._line())
            if length < 0:
                return None
            value = self._bytes(length)
            if self._bytes(2) != b"\r\n":
                raise RuntimeError("malformed bulk reply")
            return value
        if prefix == b"*":
            return [self.read() for _ in range(int(self._line()))]
        raise RuntimeError(f"unknown RESP prefix {prefix!r}")

    def command(self, *parts):
        self.send(*parts)
        return self.read()


STAT_NAMES = (
    "tomokv_uring2_batch_waits",
    "tomokv_uring2_batch_filled",
    "tomokv_uring2_batch_escapes",
    "tomokv_uring2_batch_wait_us_mean",
)


def stats(conn):
    payload = conn.command("INFO", "stats").decode()
    parsed = {}
    for line in payload.splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name in STAT_NAMES:
            parsed[name] = float(value) if name.endswith("_mean") else int(value)
    missing = set(STAT_NAMES) - set(parsed)
    if missing:
        raise RuntimeError(f"missing INFO witnesses: {sorted(missing)}")
    return parsed


def config_get(conn, name):
    reply = conn.command("CONFIG", "GET", name)
    if not isinstance(reply, list) or len(reply) != 2:
        raise RuntimeError(f"malformed CONFIG GET {name}: {reply!r}")
    return int(reply[1])


def set_batch(conn, maximum, minimum, wait_us):
    reply = conn.command(
        "CONFIG", "SET",
        "tomokv-uring2-max-sqes-per-enter", str(maximum),
        "tomokv-uring2-min-sqes-per-enter", str(minimum),
        "tomokv-uring2-batch-wait-us", str(wait_us),
    )
    if reply != "OK":
        raise RuntimeError(f"CONFIG SET returned {reply!r}")


def simultaneous_ping(connections, timeout):
    request = b"*1\r\n$4\r\nPING\r\n"
    for conn in connections:
        conn.sock.sendall(request)
        conn.sock.setblocking(False)

    deadline = time.monotonic() + timeout
    replies = [bytearray() for _ in connections]
    pending = set(range(len(connections)))
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        readers = [connections[i].sock for i in pending]
        ready, _, _ = select.select(readers, [], [], remaining)
        if not ready:
            break
        for sock in ready:
            index = next(i for i in pending if connections[i].sock is sock)
            chunk = sock.recv(64)
            if not chunk:
                raise RuntimeError(f"connection {index} closed before PONG")
            replies[index].extend(chunk)
            if replies[index] == b"+PONG\r\n":
                pending.remove(index)
            elif not b"+PONG\r\n".startswith(replies[index]):
                raise RuntimeError(
                    f"connection {index} returned {bytes(replies[index])!r}")
    if pending:
        raise RuntimeError(f"connections wedged waiting for PONG: {sorted(pending)}")
    for conn in connections:
        conn.sock.setblocking(True)
        conn.sock.settimeout(timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6391)
    parser.add_argument("--connections", type=int, default=3)
    parser.add_argument("--target", type=int, default=32)
    parser.add_argument("--wait-us", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 < args.connections < args.target:
        raise SystemExit("connections must be positive and below target")

    control = RespConnection(args.host, args.port, args.timeout)
    clients = []
    names = (
        "tomokv-uring2-max-sqes-per-enter",
        "tomokv-uring2-min-sqes-per-enter",
        "tomokv-uring2-batch-wait-us",
    )
    original = tuple(config_get(control, name) for name in names)
    try:
        set_batch(control, 0, 0, 0)
        model = control.command("DEBUG", "TOMO-URING2CAPSELFTEST")
        decoded = [item.decode() if isinstance(item, bytes) else item
                   for item in model]
        if not decoded or any(not item.startswith("OK ") for item in decoded):
            raise RuntimeError(f"deterministic selftest failed: {decoded!r}")
        if not any("min-max-zero-legacy-submit-sequence" in item
                   for item in decoded):
            raise RuntimeError("zero/zero legacy sequence witness is absent")

        clients = [RespConnection(args.host, args.port, args.timeout)
                   for _ in range(args.connections)]
        off_before = stats(control)
        simultaneous_ping(clients, args.timeout)
        off_after = stats(control)
        if (off_after[STAT_NAMES[0]] != off_before[STAT_NAMES[0]] or
                off_after[STAT_NAMES[2]] != off_before[STAT_NAMES[2]]):
            raise RuntimeError("batch wait/escape fired while min=max=0")

        set_batch(control, 0, args.target, args.wait_us)
        on_before = stats(control)
        simultaneous_ping(clients, args.timeout)
        on_after = stats(control)
        waits = on_after[STAT_NAMES[0]] - on_before[STAT_NAMES[0]]
        filled = on_after[STAT_NAMES[1]] - on_before[STAT_NAMES[1]]
        escapes = on_after[STAT_NAMES[2]] - on_before[STAT_NAMES[2]]
        if waits <= 0 or escapes <= 0:
            raise RuntimeError(
                f"short live set did not exercise escape: "
                f"waits={waits} escapes={escapes}")
        if filled != 0 or escapes != waits:
            raise RuntimeError(
                f"impossible target unexpectedly filled or failed to escape: "
                f"waits={waits} filled={filled} escapes={escapes}")
        print(
            "OK uring2-batch-wait-live "
            f"connections={args.connections} target={args.target} "
            f"replies={args.connections} waits={waits} filled={filled} "
            f"escapes={escapes} mean_us={on_after[STAT_NAMES[3]]:.6f}"
        )
    finally:
        try:
            set_batch(control, *original)
        finally:
            for conn in clients:
                conn.close()
            control.close()


if __name__ == "__main__":
    main()
