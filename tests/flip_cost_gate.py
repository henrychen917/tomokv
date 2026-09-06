#!/usr/bin/env python3
"""Directed test of the FLIP controller's COST GATE and OUTCOME LOOP (src/core/flip_policy.h).

Boot the server separately at the WRONG split, in split mode, with the controller on, e.g.:
  taskset -c <cores> ./build/tomokv --port <port> --save '' --ratio 3:1 --shards 64 \\
      --flip-auto 1 --enable-debug-command yes

The load is BITCOUNT over 4 MB bitmaps from a handful of closed-loop connections: pure executor
work that saturates the one ex thread of a 3:1 boot while the io threads idle, so the placement
model projects a large gain for 1:3 and the server, not the driver, bounds throughput. No memtier,
no performance claim; the numbers only exist to drive the controller's arithmetic.

  1. COST GATE REFUSES.  Before any load, DEBUG FLIPCTL COST types an absurd per-client transfer
     cost. The boot maneuver must still see the gain (the model's target is not the live split),
     must still not move (a move that cannot pay for itself is refused), and must record WHY:
     model_last_decision hold-cost, one cost hold, zero flips, live split unchanged.
  2. A MOVE THAT PAYS HAPPENS.  COST -1 restores the measured cost (zero: no flip has been
     measured yet) and DEBUG FLIPCTL TRIGGER re-opens the same workload. Exactly ONE flip must
     complete, land on the model's target, and be verified against the origin's own noise:
     model_last_decision moved-delivered, one move, zero misses.
  3. AN INDUCED MISS REVERTS AND RAISES THE BAR.  DEBUG FLIPCTL SEEK <origin> FORCE proposes the
     split the controller just left -- a hypothesis the model rates as a loss -- and bypasses the
     bars. The outcome loop must measure it, flip straight back, and raise the bar: two more flips,
     live split back on the anchor, round_trips 1, model_margin doubled, model_misses 1, kappa
     halved, model_last_decision moved-reverted.
  4. THE RAISED BAR HOLDS.  The same proposal WITHOUT force is judged by the model and refused
     without a flip (hold-below-bar): a hypothesis that lost stays refused.
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
        self.sock = socket.create_connection((host, port), timeout=30)
        self.sock.settimeout(30)
        self.buf = bytearray()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

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
        if kind == "=":
            size = int(self._line())
            self._fill(size + 2)
            value = bytes(self.buf[:size])
            del self.buf[:size + 2]
            return value[4:] if value[3:4] == b":" else value
        raise RuntimeError("unexpected RESP prefix %r" % kind)

    def command(self, *parts):
        self.send(encode(*parts))
        return self.recv()


CHECKS = [0]


def check(name, got, want):
    CHECKS[0] += 1
    if got != want:
        raise AssertionError("%s: got %r want %r" % (name, got, want))


def state(control):
    row = {}
    for section in ("FLIPCTL", "STATS", "SERVER"):
        raw = control.command("INFO", section).decode()
        row.update(dict(line.split(":", 1) for line in raw.splitlines() if ":" in line))
    return row


def dump(control):
    raw = control.command("DEBUG", "FLIPCTL")
    return raw.decode(errors="replace") if raw else ""


def wait_for(control, description, predicate, timeout, poll=0.5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = state(control)
        if predicate(last):
            return last
        time.sleep(poll)
    raise AssertionError("timeout waiting for %s; last=%r\n%s" % (description, last, dump(control)))


def anchored(row):
    return row.get("flipctl_state") == "anchored"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host", nargs="?", default="127.0.0.1")
    parser.add_argument("port", nargs="?", type=int, default=8087)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--bitmap-mb", type=int, default=4)
    parser.add_argument("--boot-timeout", type=float, default=120.0)
    parser.add_argument("--maneuver-timeout", type=float, default=120.0)
    args = parser.parse_args()

    control = Resp(args.host, args.port)
    row = state(control)
    if row.get("flipctl_state") == "disabled":
        raise AssertionError("server was booted without --flip-auto 1: %r" % row)
    if row.get("flipctl_state") == "unavailable":
        raise AssertionError("server is in 1s mode; this battery needs split mode: %r" % row)
    if row.get("flipctl_state") != "awaiting-load-stability":
        raise AssertionError("server must be freshly booted and idle: %r" % row)
    boot_io, boot_ex = int(row["io_threads"]), int(row["ex_threads"])
    if boot_io < 2 or boot_ex != 1:
        raise AssertionError("boot the server at an ex-starved split such as 3:1; got %d:%d"
                             % (boot_io, boot_ex))
    total = boot_io + boot_ex

    # ---- 1. an absurd measured cost, typed before any load -----------------------------------
    check("DEBUG FLIPCTL COST accepts a per-client cost",
          control.command("DEBUG", "FLIPCTL", "COST", "1000000000"), b"OK")

    setup = Resp(args.host, args.port)
    bitmap = b"\xaa" * (args.bitmap_mb * 1024 * 1024)
    for index in range(args.workers):
        if setup.command("SET", "costgate-bits%d" % index, bitmap) != b"OK":
            raise AssertionError("failed to initialize bitmap %d" % index)
    setup.close()

    stop = threading.Event()
    errors = []

    def worker(index):
        client = None
        try:
            client = Resp(args.host, args.port)
            frame = encode("BITCOUNT", "costgate-bits%d" % index)
            while not stop.is_set():
                client.send(frame)
                client.recv()
        except Exception as error:  # surfaced by the controlling thread
            errors.append(repr(error))
            stop.set()
        finally:
            if client:
                client.close()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(args.workers)]
    try:
        for thread in threads:
            thread.start()

        held = wait_for(control, "the boot maneuver to finish under the typed cost",
                        lambda r: anchored(r) and int(r.get("flipctl_boot_triggers", 0)) == 1,
                        args.boot_timeout)
        if errors:
            raise AssertionError("load driver failed: %s" % errors[0])
        check("cost gate: no flip completed", int(held["flip_completed"]), 0)
        check("cost gate: live split unchanged",
              (int(held["io_threads"]), int(held["ex_threads"])), (boot_io, boot_ex))
        check("cost gate: the decision names the cost", held["flipctl_model_last_decision"],
              "hold-cost")
        check("cost gate: one cost hold booked", int(held["flipctl_cost_holds"]), 1)
        trail = dump(control)
        target = None
        for line in trail.splitlines():
            if line.startswith("model_target_io="):
                target = int(line.split()[0].split("=")[1])
        if target is None or target == boot_io:
            raise AssertionError("the model did not propose a different split under load:\n%s"
                                 % trail)
        print("1. cost gate: model proposed %d:%d from %d:%d, typed cost refused it -- "
              "decision=%s flips=%s live=%s:%s"
              % (target, total - target, boot_io, boot_ex, held["flipctl_model_last_decision"],
                 held["flip_completed"], held["io_threads"], held["ex_threads"]))

        # ---- 2. the measured cost (zero, nothing measured yet) and the same workload -------------
        check("DEBUG FLIPCTL COST -1 restores the measurement",
              control.command("DEBUG", "FLIPCTL", "COST", "-1"), b"OK")
        triggers = int(held["flipctl_triggers"])
        check("DEBUG FLIPCTL TRIGGER", control.command("DEBUG", "FLIPCTL", "TRIGGER"), b"OK")
        moved = wait_for(control, "the re-opened maneuver to move and anchor",
                         lambda r: anchored(r) and int(r.get("flipctl_triggers", 0)) > triggers,
                         args.maneuver_timeout)
        if errors:
            raise AssertionError("load driver failed: %s" % errors[0])
        check("paying move: exactly one flip", int(moved["flip_completed"]), 1)
        check("paying move: landed on the model's target",
              (int(moved["io_threads"]), int(moved["ex_threads"])), (target, total - target))
        check("paying move: anchored there",
              (int(moved["flipctl_anchor_io"]), int(moved["flipctl_anchor_ex"])),
              (target, total - target))
        check("paying move: verified against the origin", moved["flipctl_model_last_decision"],
              "moved-delivered")
        check("paying move: one move, no miss",
              (int(moved["flipctl_model_moves"]), int(moved["flipctl_model_misses"])), (1, 0))
        kappa_after_hit = float(moved["flipctl_model_kappa"])
        check("paying move: calibration in (0, 1]", 0.0 < kappa_after_hit <= 1.0, True)
        check("paying move: the flip's cost was measured",
              int(moved["flipctl_last_flip_moved"]) > 0, True)
        print("2. paying move: one flip to %s:%s, decision=%s kappa=%.3f client_cost=%s "
              "lost=%s moved=%s"
              % (moved["io_threads"], moved["ex_threads"], moved["flipctl_model_last_decision"],
                 kappa_after_hit, moved["flipctl_client_cost"], moved["flipctl_last_flip_lost"],
                 moved["flipctl_last_flip_moved"]))

        # ---- 3. an induced miss: propose the split the controller just left, forced --------------
        flips = int(moved["flip_completed"])
        margin = int(moved["flipctl_model_margin"])
        triggers = int(moved["flipctl_triggers"])
        check("DEBUG FLIPCTL SEEK <origin> FORCE",
              control.command("DEBUG", "FLIPCTL", "SEEK", str(boot_io), "FORCE"), b"OK")
        reverted = wait_for(control, "the forced hypothesis to be judged and the anchor restored",
                            lambda r: anchored(r) and int(r.get("flipctl_triggers", 0)) > triggers
                            and int(r.get("flip_completed", 0)) >= flips + 2,
                            args.maneuver_timeout)
        if errors:
            raise AssertionError("load driver failed: %s" % errors[0])
        check("induced miss: out and back", int(reverted["flip_completed"]), flips + 2)
        check("induced miss: live split back on the anchor",
              (int(reverted["io_threads"]), int(reverted["ex_threads"])), (target, total - target))
        check("induced miss: the decision names the revert",
              reverted["flipctl_model_last_decision"], "moved-reverted")
        check("induced miss: one round trip", int(reverted["flipctl_round_trips"]), 1)
        check("induced miss: the bar doubled", int(reverted["flipctl_model_margin"]), 2 * margin)
        check("induced miss: one miss of two moves",
              (int(reverted["flipctl_model_moves"]), int(reverted["flipctl_model_misses"])), (2, 1))
        check("induced miss: baseline held, so the miss was earned",
              int(reverted["flipctl_invalidated_maneuvers"]), 0)
        print("3. induced miss: %d:%d proposed by force, measured, reverted -- margin %s -> %s, "
              "misses=%s kappa=%s"
              % (boot_io, boot_ex, margin, reverted["flipctl_model_margin"],
                 reverted["flipctl_model_misses"], reverted["flipctl_model_kappa"]))

        # ---- 4. the same proposal, judged: refused without a flip ---------------------------------
        flips = int(reverted["flip_completed"])
        triggers = int(reverted["flipctl_triggers"])
        check("DEBUG FLIPCTL SEEK <origin>",
              control.command("DEBUG", "FLIPCTL", "SEEK", str(boot_io)), b"OK")
        refused = wait_for(control, "the judged proposal to be refused and the anchor kept",
                           lambda r: anchored(r) and int(r.get("flipctl_triggers", 0)) > triggers,
                           args.maneuver_timeout)
        check("judged proposal: no flip", int(refused["flip_completed"]), flips)
        check("judged proposal: refused below the bar", refused["flipctl_model_last_decision"],
              "hold-below-bar")
        check("judged proposal: split kept",
              (int(refused["io_threads"]), int(refused["ex_threads"])), (target, total - target))
        print("4. judged proposal: %d:%d refused without a flip (decision=%s)"
              % (boot_io, boot_ex, refused["flipctl_model_last_decision"]))
    finally:
        stop.set()
        for thread in threads:
            thread.join(10)
        control.close()

    if errors:
        raise AssertionError("load driver failed: %s" % errors[0])
    print("ok: flip cost gate + outcome loop (%d checks)" % CHECKS[0])


if __name__ == "__main__":
    main()
