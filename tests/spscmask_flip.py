#!/usr/bin/env python3
"""Exercise every masked producer lane across the two 64-thread extreme splits.

Usage: tests/spscmask_flip.py HOST PORT [seconds-per-shape]

Boot requirement: exactly 64 threads at 63 io : 1 ex, appendonly=no, and
--enable-debug-command yes.  The runner should confine the server to cores 48-55; explicit
placement may repeat those CPUs to create the owner-required oversubscribed 64-thread geometry.

The test retains one socket owned by each of the 63 initial IO threads (DEBUG IO-THREAD is the
fired-mechanism proof), then continuously pipelines SET/GET pairs on a producer-private key.  It
flips 63:1 -> 1:63 -> 63:1 without stopping those streams.  Exact replies and final values prove no
loss and no reorder within a producer; counter movement on both sides proves both the 63-producer
and one-producer masks carried load rather than merely being installed.
"""

import socket
import sys
import threading
import time


HOST = sys.argv[1]
PORT = int(sys.argv[2])
SECONDS_PER_SHAPE = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
PRODUCERS = 63
BATCH = 32
MAX_DISCOVERY = 8192


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if not isinstance(arg, bytes):
            arg = str(arg).encode()
        out.extend((b"$%d\r\n" % len(arg), arg, b"\r\n"))
    return b"".join(out)


class RespError(Exception):
    pass


class Conn:
    def __init__(self, timeout=30):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def send_raw(self, payload):
        self.sock.sendall(payload)

    def command(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        prefix = self.file.read(1)
        if not prefix:
            raise EOFError("server closed connection")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError("bad RESP line %r" % (prefix + line,))
        value = line[:-2]
        if prefix == b"+":
            return value
        if prefix == b"-":
            raise RespError(value.decode("utf-8", "replace"))
        if prefix == b":":
            return int(value)
        if prefix in (b"$", b"="):
            size = int(value)
            if size < 0:
                return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return data
        if prefix in (b"*", b"~", b">"):
            size = int(value)
            return None if size < 0 else [self.read() for _ in range(size)]
        if prefix == b"%":
            out = {}
            for _ in range(int(value)):
                out[self.read()] = self.read()
            return out
        raise AssertionError("unexpected RESP prefix %r" % prefix)

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()


def flip_report(conn):
    reply = conn.command("FLIP")
    if isinstance(reply, dict):
        return {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in reply.items()}
    if not isinstance(reply, list) or len(reply) % 2:
        raise AssertionError("bad FLIP report %r" % (reply,))
    return {reply[i].decode(): int(reply[i + 1]) for i in range(0, len(reply), 2)}


def discover_producers():
    retained = {}
    attempts = 0
    while len(retained) < PRODUCERS and attempts < MAX_DISCOVERY:
        attempts += 1
        conn = Conn()
        owner = conn.command("DEBUG", "IO-THREAD")
        if owner in retained:
            conn.close()
        else:
            retained[owner] = conn
    if len(retained) != PRODUCERS:
        for conn in retained.values():
            conn.close()
        raise AssertionError("covered %d/%d IO producers after %d connections" %
                             (len(retained), PRODUCERS, attempts))
    expected = set(range(PRODUCERS))
    if set(retained) != expected:
        raise AssertionError("initial IO tids %r, expected %r" %
                             (sorted(retained), sorted(expected)))
    print("covered all 63 initial IO producers after %d connections" % attempts, flush=True)
    return [retained[owner] for owner in sorted(retained)]


stop = threading.Event()
start = threading.Barrier(PRODUCERS + 1)
lock = threading.Lock()
errors = []
verified = [0] * PRODUCERS
last_value = [-1] * PRODUCERS


def fail(message):
    with lock:
        if len(errors) < 20:
            errors.append(message)
    stop.set()


def flood(index, conn):
    key = "spscmask:%02d" % index
    sequence = 0
    try:
        start.wait(timeout=30)
        while not stop.is_set():
            commands = []
            expected = []
            for _ in range(BATCH):
                sequence += 1
                value = "%02d:%012d" % (index, sequence)
                commands.extend((encode("SET", key, value), encode("GET", key)))
                expected.extend((b"OK", value.encode()))
            conn.send_raw(b"".join(commands))
            for wanted in expected:
                got = conn.read()
                if got != wanted:
                    raise AssertionError("producer %d reply %r, wanted %r" %
                                         (index, got, wanted))
            with lock:
                verified[index] += BATCH
                last_value[index] = sequence
    except Exception as exc:
        fail("producer %d: %r" % (index, exc))


def wait_all_advance(before, label, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline and not errors:
        with lock:
            current = list(verified)
        if all(current[i] > before[i] for i in range(PRODUCERS)):
            print("all streams advanced under %s" % label, flush=True)
            return current
        time.sleep(0.02)
    stalled = [i for i in range(PRODUCERS) if verified[i] <= before[i]]
    raise AssertionError("streams stalled under %s: %r" % (label, stalled[:10]))


def main():
    control = Conn(timeout=60)
    report = flip_report(control)
    if (report["live_io"], report["live_ex"]) != (63, 1):
        raise AssertionError("boot at 63:1, got %d:%d" %
                             (report["live_io"], report["live_ex"]))
    if control.command("CONFIG", "GET", "appendonly") != [b"appendonly", b"no"]:
        raise AssertionError("directed mask test requires appendonly no so 63 -> 1 is legal")
    conns = discover_producers()
    if control.command("FLUSHALL") != b"OK":
        raise AssertionError("FLUSHALL failed")

    threads = [threading.Thread(target=flood, args=(i, conn), daemon=True)
               for i, conn in enumerate(conns)]
    for thread in threads:
        thread.start()
    start.wait(timeout=30)
    wait_all_advance([0] * PRODUCERS, "63-producer mask")

    # Workers keep posting while FLIP performs ExDrain and ExInstall remasking.
    if control.command("FLIP", "1", "63") != b"OK":
        raise AssertionError("63:1 -> 1:63 FLIP did not answer OK")
    report = flip_report(control)
    if (report["live_io"], report["live_ex"]) != (1, 63):
        raise AssertionError("first extreme FLIP landed at %d:%d" %
                             (report["live_io"], report["live_ex"]))
    one_before = list(verified)
    wait_all_advance(one_before, "one-producer mask")
    time.sleep(SECONDS_PER_SHAPE)

    if control.command("FLIP", "63", "1") != b"OK":
        raise AssertionError("1:63 -> 63:1 FLIP did not answer OK")
    report = flip_report(control)
    if (report["live_io"], report["live_ex"]) != (63, 1):
        raise AssertionError("return extreme FLIP landed at %d:%d" %
                             (report["live_io"], report["live_ex"]))
    with lock:
        expanded_before = list(verified)
    wait_all_advance(expanded_before, "re-expanded 63-producer mask")
    time.sleep(SECONDS_PER_SHAPE)

    stop.set()
    for thread in threads:
        thread.join(timeout=60)
    alive = [i for i, thread in enumerate(threads) if thread.is_alive()]
    if alive:
        raise AssertionError("flood threads did not drain: %r" % alive[:10])
    if errors:
        raise AssertionError("; ".join(errors))

    # Every synchronous pipeline was fully read before its worker exited. Final point reads prove
    # that the last acknowledged write from each producer also reached the store.
    for index, conn in enumerate(conns):
        key = "spscmask:%02d" % index
        expected = ("%02d:%012d" % (index, last_value[index])).encode()
        got = conn.command("GET", key)
        if got != expected:
            raise AssertionError("final drain producer %d got %r, wanted %r" %
                                 (index, got, expected))
    if control.command("DBSIZE") != PRODUCERS:
        raise AssertionError("final DBSIZE does not match producer key count")

    total = sum(verified)
    print("spscmask_flip: PASS producers=63 -> 1 -> 63 verified_pairs=%d" % total)
    for conn in conns:
        conn.close()
    control.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        stop.set()
        print("spscmask_flip: FAIL: %s" % exc)
        sys.exit(1)
