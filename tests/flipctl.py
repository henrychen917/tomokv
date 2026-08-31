#!/usr/bin/env python3
"""Small functional acceptance for the automatic FLIP controller.

Boot separately on the requested lane:
  taskset -c 48-55 ./build/tomokv --port 7845 --save '' --flip-auto 1 \
      --flip-auto-band 2 --enable-debug-command yes

The driver ramps to a low-load anchor, raises the issue rate on those same connections, and then
changes the command mix. It deliberately uses no memtier and makes no performance claim; command
rate exists only to exercise the controller's work/rate windows.
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
    parser.add_argument("--port", type=int, default=7845)
    parser.add_argument("--stable-seconds", type=int, default=60)
    parser.add_argument("--idle-seconds", type=int, default=4)
    parser.add_argument("--workers", type=int, default=9)
    parser.add_argument("--ramp-delay", type=float, default=1.1)
    parser.add_argument("--think-time", type=float, default=0.0005)
    parser.add_argument("--surge-think-time", type=float, default=0.0004)
    parser.add_argument("--pace-burst", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 9 or args.workers % 9:
        parser.error("--workers must be a positive multiple of 9")
    if args.think_time < 0:
        parser.error("--think-time must be non-negative")
    if args.surge_think_time < 0 or args.surge_think_time >= args.think_time:
        parser.error("--surge-think-time must be non-negative and less than --think-time")
    if args.pace_burst < 1:
        parser.error("--pace-burst must be positive")
    low_workers = args.workers // 3

    control = Resp(args.host, args.port)
    mode = ["base"]
    surge = threading.Event()
    stop = threading.Event()
    errors = []

    # One frame is sent only after the prior reply, so shortening think-time raises volume without
    # changing connections, pipeline-depth buckets, command mix, or key/value shapes.
    def bitcount_frame(index):
        return encode("BITCOUNT", "flipctl-bits%d" % index)

    def incr_frame(index):
        return encode("INCR", "flipctl-count%d" % index)

    def load_worker(base_frame, mix_frame):
        client = None
        try:
            client = Resp(args.host, args.port)
            next_issue = time.monotonic()
            issued = 0

            def pace(issue_interval):
                nonlocal issued, next_issue
                next_issue += issue_interval
                issued += 1
                if issued < args.pace_burst:
                    return
                issued = 0
                delay = next_issue - time.monotonic()
                if delay > 0:
                    stop.wait(delay)
                else:
                    next_issue = time.monotonic()

            while not stop.is_set():
                if mode[0] == "incr":
                    client.send(mix_frame)
                    client.recv()
                    # Keep command volume steady so this phase changes only the fingerprint.
                    pace(args.surge_think_time)
                else:
                    client.send(base_frame)
                    client.recv()
                    issue_interval = args.surge_think_time if surge.is_set() \
                        else args.think_time
                    pace(issue_interval)
        except Exception as error:  # reported in the controlling thread with the live state
            errors.append(repr(error))
            stop.set()
        finally:
            if client:
                client.close()

    workers = []

    def start_worker(index):
        worker = threading.Thread(target=load_worker,
                                  args=(bitcount_frame(index), incr_frame(index)), daemon=True)
        worker.start()
        workers.append(worker)

    try:
        deadline = time.monotonic() + args.idle_seconds
        while time.monotonic() < deadline:
            idle = info(control)
            if idle.get("flipctl_state") != "awaiting-load-stability" or \
                    int(idle.get("flipctl_triggers", "-1")) != 0:
                raise AssertionError("idle server started a controller maneuver: %r" % idle)
            time.sleep(0.2)

        setup = Resp(args.host, args.port)
        setup.send(b"".join(encode("SET", "k%d" % i, b"x" * 64) for i in range(1024)))
        for _ in range(1024):
            setup.recv()
        bitmap = b"\xaa" * (4 * 1024 * 1024)
        for index in range(low_workers):
            if setup.command("SET", "flipctl-bits%d" % index, bitmap) != b"OK":
                raise AssertionError("failed to initialize controller bitmap %d" % index)
        setup.close()

        # Keep the EWMA moving for the whole connection ramp. None of these partial-load plateaus
        # may start the boot maneuver or become its anchor baseline.
        for index in range(low_workers):
            opened = index + 1
            start_worker(index)
            deadline = time.monotonic() + args.ramp_delay
            while time.monotonic() < deadline:
                if errors:
                    raise AssertionError("load driver failed: %s" % errors[0])
                row = info(control)
                if row.get("flipctl_state") != "awaiting-load-stability" or \
                        int(row.get("flipctl_triggers", "-1")) != 0:
                    raise AssertionError(
                        "controller maneuvered during load ramp at %d/%d connections: %r" %
                        (opened, low_workers, row))
                time.sleep(0.2)

        anchored = wait_for(control, "boot maneuver to anchor",
                            lambda row: row.get("flipctl_state") == "anchored", 90)
        if int(anchored["flipctl_boot_triggers"]) != 1:
            raise AssertionError("boot did not produce exactly one boot trigger: %r" % anchored)
        anchor_split = (anchored["flipctl_anchor_io"], anchored["flipctl_anchor_ex"])
        if int(anchor_split[0]) <= 1 or int(anchor_split[1]) <= 1:
            raise AssertionError("ramping load produced a rail anchor: %r" % anchored)
        trigger_count = int(anchored["flipctl_triggers"])
        print("ramp deferred boot; low load anchored off-rail at %s:%s, rate=%s" %
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

        before_surge = info(control)
        fingerprint_before = int(before_surge["flipctl_fingerprint_triggers"])
        collapse_before = int(before_surge["flipctl_rate_collapse_triggers"])
        if int(before_surge["flipctl_rate_surge_triggers"]) != 0:
            raise AssertionError("rate-surge counter changed before surge: %r" % before_surge)

        def rate_surge_triggered(row):
            if int(row.get("flipctl_fingerprint_triggers", "0")) != fingerprint_before:
                raise AssertionError("issue-rate surge shifted the workload fingerprint: %r" % row)
            return int(row.get("flipctl_triggers", "0")) == trigger_count + 1 and \
                int(row.get("flipctl_rate_surge_triggers", "0")) == 1

        surge.set()
        surged = wait_for(
            control, "one rate-surge trigger on the invariant workload",
            rate_surge_triggered, 30)
        if int(surged["flipctl_rate_collapse_triggers"]) != collapse_before or \
                int(surged["flipctl_surge_triggers"]) != 1 or \
                int(surged["flipctl_collapse_triggers"]) != collapse_before:
            raise AssertionError("rate trigger counters/aliases disagree on surge: %r" % surged)

        def rate_surge_reanchored(row):
            return rate_surge_triggered(row) and row.get("flipctl_state") == "anchored"

        surge_anchor = wait_for(
            control, "rate-surge maneuver to re-anchor",
            rate_surge_reanchored, 90)
        time.sleep(5)
        held = info(control)
        if int(held["flipctl_triggers"]) != trigger_count + 1 or \
                int(held["flipctl_fingerprint_triggers"]) != fingerprint_before or \
                int(held["flipctl_rate_surge_triggers"]) != 1 or \
                held.get("flipctl_state") != "anchored":
            raise AssertionError("load surge caused more than one re-maneuver: %r" % held)
        trigger_count += 1
        print("load surge: shortened think-time on the same %d connections, exactly one "
              "rate re-maneuver at %s:%s" %
              (low_workers, surge_anchor["flipctl_anchor_io"],
               surge_anchor["flipctl_anchor_ex"]))

        mode[0] = "incr"
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
