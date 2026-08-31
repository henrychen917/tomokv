#!/usr/bin/env python3
"""Small functional acceptance for the automatic FLIP controller.

Boot separately on the requested lane:
  taskset -c 48-55 ./build/tomokv --port 7837 --save '' --flip-auto 1 \
      --enable-debug-command yes

The driver keeps load live through every assertion. It deliberately uses no memtier and makes no
performance claim; command rate exists only to exercise the controller's work/rate windows.
"""

import argparse
import socket
import threading
import time


def encode(*parts):
    values = [p if isinstance(p, bytes) else str(p).encode() for p in parts]
    return b"*%d\r\n" % len(values) + b"".join(
        b"$%d\r\n%s\r\n" % (len(value), value) for value in values)


class Resp:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(10)
        self.buf = bytearray()

    def close(self):
        self.sock.close()

    def send(self, payload):
        self.sock.sendall(payload)

    def _fill(self, count=1):
        while len(self.buf) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("server closed the connection")
            self.buf.extend(chunk)

    def _line(self):
        while True:
            end = self.buf.find(b"\r\n")
            if end >= 0:
                line = bytes(self.buf[:end])
                del self.buf[:end + 2]
                return line
            self._fill(len(self.buf) + 1)

    def recv(self):
        self._fill()
        kind = chr(self.buf[0])
        del self.buf[0]
        if kind in "+-":
            value = self._line()
            if kind == "-":
                raise RuntimeError(value.decode(errors="replace"))
            return value
        if kind == ":":
            return int(self._line())
        if kind == "$":
            size = int(self._line())
            if size < 0:
                return None
            self._fill(size + 2)
            value = bytes(self.buf[:size])
            del self.buf[:size + 2]
            return value
        if kind == "*":
            size = int(self._line())
            return [self.recv() for _ in range(size)] if size >= 0 else None
        raise RuntimeError("unexpected RESP prefix %r" % kind)

    def command(self, *parts):
        self.send(encode(*parts))
        return self.recv()


def info(control):
    raw = control.command("INFO", "FLIPCTL").decode()
    return dict(line.split(":", 1) for line in raw.splitlines() if ":" in line)


def wait_for(control, description, predicate, timeout):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = info(control)
        if predicate(last):
            return last
        time.sleep(1)
    raise AssertionError("timeout waiting for %s; last=%r" % (description, last))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7837)
    parser.add_argument("--stable-seconds", type=int, default=60)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    control = Resp(args.host, args.port)
    setup = Resp(args.host, args.port)
    setup.send(b"".join(encode("SET", "k%d" % i, b"x" * 64) for i in range(1024)))
    for _ in range(1024):
        setup.recv()
    setup.close()

    mode = ["get"]
    stop = threading.Event()
    errors = []

    get_batch = b"".join(encode("GET", "k%d" % i) for i in range(32))
    mget = tuple(["MGET"] + ["k%d" % i for i in range(16)])
    mget_batch = b"".join(encode(*mget) for _ in range(8))

    def load_worker():
        client = None
        try:
            client = Resp(args.host, args.port)
            while not stop.is_set():
                if mode[0] == "get":
                    client.send(get_batch)
                    for _ in range(32):
                        client.recv()
                else:
                    client.send(mget_batch)
                    for _ in range(8):
                        client.recv()
        except Exception as error:  # reported in the controlling thread with the live state
            errors.append(repr(error))
            stop.set()
        finally:
            if client:
                client.close()

    workers = [threading.Thread(target=load_worker, daemon=True) for _ in range(args.workers)]
    for worker in workers:
        worker.start()

    try:
        anchored = wait_for(control, "boot maneuver to anchor",
                            lambda row: row.get("flipctl_state") == "anchored", 90)
        if int(anchored["flipctl_boot_triggers"]) != 1:
            raise AssertionError("boot did not produce exactly one boot trigger: %r" % anchored)
        anchor_split = (anchored["flipctl_anchor_io"], anchored["flipctl_anchor_ex"])
        trigger_count = int(anchored["flipctl_triggers"])
        print("boot anchored at %s:%s, rate=%s" %
              (anchor_split[0], anchor_split[1], anchored["flipctl_anchor_rate"]))

        deadline = time.monotonic() + args.stable_seconds
        while time.monotonic() < deadline:
            if errors:
                raise AssertionError("load driver failed: %s" % errors[0])
            row = info(control)
            if row.get("flipctl_state") != "anchored" or \
                    int(row["flipctl_triggers"]) != trigger_count or \
                    (row["flipctl_anchor_io"], row["flipctl_anchor_ex"]) != anchor_split:
                raise AssertionError("controller moved during stable hold: %r" % row)
            time.sleep(1)
        print("stable hold: %ds, no trigger or split movement" % args.stable_seconds)

        mode[0] = "mget"
        changed = wait_for(
            control, "one mix-change trigger",
            lambda row: int(row.get("flipctl_triggers", "0")) == trigger_count + 1, 30)
        if int(changed["flipctl_triggers"]) != trigger_count + 1:
            raise AssertionError("mix change did not produce exactly one trigger: %r" % changed)
        final = wait_for(
            control, "mix-change maneuver to re-anchor",
            lambda row: row.get("flipctl_state") == "anchored" and
                        int(row.get("flipctl_triggers", "0")) == trigger_count + 1, 90)
        time.sleep(5)
        held = info(control)
        if int(held["flipctl_triggers"]) != trigger_count + 1 or \
                held.get("flipctl_state") != "anchored":
            raise AssertionError("mix change caused more than one re-maneuver: %r" % held)
        print("mix change: exactly one re-maneuver, anchored at %s:%s" %
              (final["flipctl_anchor_io"], final["flipctl_anchor_ex"]))
    finally:
        stop.set()
        for worker in workers:
            worker.join(10)
        control.close()

    if errors:
        raise AssertionError("load driver failed: %s" % errors[0])
    print("ok: flipctl functional acceptance")


if __name__ == "__main__":
    main()
