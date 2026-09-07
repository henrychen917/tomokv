#!/usr/bin/env python3
"""Directed regression for the multi-key FLIP-controller thrash.

THE DEFECT.  Under `--flip-auto 1` a stationary multi-key workload made the controller re-maneuver
on its own: it completed flips, transferred hundreds of connections, and anchored on exactly the
split it started from.  The trigger was the fingerprint's pass-depth family -- the histogram of how
many frames each io thread happened to parse per pass.  That is an arrival-batching observation,
not a workload property, and the controller's own actuator moves it: a measured io 5->7 step moved
the pass-depth distance by 0.048, eight to forty times its learned band, while the three families
that describe what the clients actually asked for (command class, keys per multi-key command, value
bytes per command) moved by 4e-7, 0 and 5e-7 over the same seconds.

THE TEST.  Two phases against one anchored controller.

  NEGATIVE -- the defect.  Hold the command mix EXACTLY constant (same commands, same key count,
  same value bytes, same paced issue rate) and vary only the client's write batching, so parse-pass
  occupancy sweeps from the 2-4 bucket to the 5-16 bucket and back.  Nothing the clients ask for
  changes.  Assert the mix detector's own distance never reaches its own band, that no fingerprint
  trigger fires, that no flip completes, that no connection is transferred, and that the anchor
  does not move.  On the unpatched tree the distance reaches 204x the band within seconds.

  POSITIVE -- the feature still works.  Then change the mix for real (8-key multi-key traffic ->
  single-key GET: command class, keys/op and value bytes all move) and assert the mix detector's
  distance DOES clear its band and that the controller re-maneuvers and re-anchors.  A fix that
  simply desensitized the detector would pass the negative phase and fail here, so the negative
  assertion can never be satisfied vacuously.

  SCOPE.  The two assertions above are about the MIX detector, which is what a multi-key workload
  fools.  The rate detector is deliberately not asserted on: it is fed by measured throughput, and
  this battery paces its own load from nine Python threads, whose second-to-second jitter is larger
  than the sub-percent band the controller learns on a paced stream.  Asserting on it would measure
  the load driver.  Its response is still bounded by the same evidence rules and is reported below.

  POLICY.  Since the placement policy landed (src/core/flip_policy.h) a maneuver on a workload the
  server is not CPU-bound on -- such as this battery's paced stream -- holds without a flip, so the
  negative phase also asserts the policy's own hold path.

Boot the server separately, in split mode, with the controller on, e.g.:
  taskset -c <cores> ./build/tomokv --port <port> --save '' --ratio 2:2 --shards 64 --atomic 1 \
      --flip-auto 1 --enable-debug-command yes
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
        self.sock = socket.create_connection((host, port), timeout=20)
        self.sock.settimeout(20)
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
    raw = control.command("INFO", "FLIPCTL").decode()
    row = dict(line.split(":", 1) for line in raw.splitlines() if ":" in line)
    raw = control.command("INFO", "STATS").decode()
    row.update(dict(line.split(":", 1) for line in raw.splitlines() if ":" in line))
    return row


def motion(row):
    """Ownership the controller can move, plus the mix detector that a multi-key stream fools.

    Deliberately excludes flipctl_triggers: the rate detector can also raise it, and this battery
    does not control throughput to the precision that detector's learned band demands.  What it
    does control exactly is the command mix, so the mix trigger is asserted; and what the defect
    actually costs -- completed flips, transferred connections, a moved split -- is asserted
    whatever detector asked for it.
    """
    return (int(row.get("flipctl_fingerprint_triggers", -1)),
            int(row.get("flip_completed", -1)),
            int(row.get("flip_clients_transferred", -1)),
            row.get("flipctl_anchor_io"), row.get("flipctl_anchor_ex"))


def detector(control):
    """(distance, band) of the mix detector, or None while it is between anchors.

    This is the quantity the fix is about, read straight out of the controller instead of inferred
    from a counter some other detector can also move.
    """
    raw = control.command("DEBUG", "FLIPCTL")
    if raw is None:
        return None
    row = dict(line.split("=", 1) for line in raw.decode().splitlines()
               if "=" in line and " " not in line.split("=", 1)[0])
    try:
        band = float(row["signature_band"])
        distance = float(row["signature_distance"])
    except (KeyError, ValueError):
        return None
    return (distance, band) if band > 0 else None


def wait_for(control, description, predicate, timeout, poll=0.5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = state(control)
        if predicate(last):
            return last
        time.sleep(poll)
    raise AssertionError("timeout waiting for %s; last=%r" % (description, last))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host", nargs="?", default="127.0.0.1")
    parser.add_argument("port", nargs="?", type=int, default=8087)
    parser.add_argument("--workers", type=int, default=9)
    parser.add_argument("--keys", type=int, default=8)
    parser.add_argument("--value-bytes", type=int, default=32)
    parser.add_argument("--rate", type=float, default=1500.0,
                        help="commands per second per worker; identical in every phase")
    parser.add_argument("--anchor-timeout", type=float, default=150.0)
    parser.add_argument("--settle-seconds", type=float, default=10.0,
                        help="the anchor must hold this long, unchanged, before the hold begins")
    parser.add_argument("--hold-seconds", type=float, default=45.0)
    parser.add_argument("--batch-period", type=float, default=3.0,
                        help="seconds between write-batch size changes in the negative phase")
    parser.add_argument("--mix-timeout", type=float, default=120.0)
    args = parser.parse_args()

    control = Resp(args.host, args.port)
    row = state(control)
    if row.get("flipctl_state") == "disabled":
        raise AssertionError("server was booted without --flip-auto 1: %r" % row)
    if row.get("flipctl_state") == "unavailable":
        raise AssertionError("server is in 1s mode; this battery needs split mode: %r" % row)

    value = b"v" * args.value_bytes
    # One fixed key set per worker.  Key names, key count and value bytes never change, so the
    # command-class mix, keys-per-multikey and value-bytes-per-command families are constant to the
    # bit across every phase of the negative hold.
    def frames(index):
        keys = ["mkhold:%d:%d" % (index, k) for k in range(args.keys)]
        mget = encode("MGET", *keys)
        mset = encode("MSET", *[part for k in keys for part in (k, value)])
        get = encode("GET", keys[0])
        return mget, mset, get

    mode = ["multi"]
    batch = [8]
    stop = threading.Event()
    errors = []

    def worker(index):
        client = None
        try:
            client = Resp(args.host, args.port)
            mget, mset, get = frames(index)
            client.send(mset)
            client.recv()
            next_issue = time.monotonic()
            while not stop.is_set():
                size = batch[0]
                if mode[0] == "multi":
                    # Always an even count of alternating MGET/MSET, so every closed work window
                    # sees the same 50/50 class mix no matter where the batch boundaries land.
                    payload = (mget + mset) * (size // 2)
                    replies = size - (size % 2)
                else:
                    payload = get * size
                    replies = size
                if not replies:
                    continue
                client.send(payload)
                for _ in range(replies):
                    client.recv()
                next_issue += replies / args.rate
                delay = next_issue - time.monotonic()
                if delay > 0:
                    stop.wait(delay)
                else:
                    next_issue = time.monotonic()
        except Exception as error:  # surfaced by the controlling thread with the live state
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

        # Anchor, then require the anchor to HOLD unchanged before the measured phase starts.
        # A controller that anchored on the connection ramp and is still chasing the steady state
        # is not yet the "stationary, already balanced" condition this battery is about; without
        # this the run measures the tail of the boot maneuver instead of the defect.
        deadline = time.monotonic() + args.anchor_timeout
        anchored = None
        while True:
            anchored = wait_for(control, "the controller to anchor on stationary multi-key load",
                                lambda r: r.get("flipctl_state") == "anchored",
                                max(1.0, deadline - time.monotonic()))
            baseline = motion(anchored)
            quiet_until = time.monotonic() + args.settle_seconds
            while time.monotonic() < quiet_until and motion(state(control)) == baseline:
                time.sleep(0.5)
            if motion(state(control)) == baseline:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "controller never held a settled anchor within %.0fs; last=%r"
                    % (args.anchor_timeout, state(control)))
        if errors:
            raise AssertionError("load driver failed: %s" % errors[0])
        baseline = motion(anchored)
        print("anchored at %s:%s after %s trigger(s) (%s of them fingerprint), "
              "%s completed flip(s), %s client transfer(s)"
              % (anchored["flipctl_anchor_io"], anchored["flipctl_anchor_ex"],
                 anchored["flipctl_triggers"], baseline[0], baseline[1], baseline[2]))

        # ---- NEGATIVE: sweep parse-pass occupancy, hold the mix ----------------------------------
        sizes = (2, 16)
        deadline = time.monotonic() + args.hold_seconds
        index = 0
        worst = 0.0
        while time.monotonic() < deadline:
            batch[0] = sizes[index % len(sizes)]
            index += 1
            phase_end = min(deadline, time.monotonic() + args.batch_period)
            while time.monotonic() < phase_end:
                if errors:
                    raise AssertionError("load driver failed: %s" % errors[0])
                row = state(control)
                check("stationary multi-key mix must not move the controller "
                      "(batch=%d)" % batch[0], motion(row), baseline)
                reading = detector(control)
                if reading:
                    worst = max(worst, reading[0] / reading[1])
                time.sleep(0.25)
        # The controller must come back to rest on the same split.  Waiting for that, rather than
        # sampling `anchored` at one instant, keeps the rate detector -- whose band this battery's
        # paced load cannot honour -- from deciding the verdict; a controller that really was
        # oscillating would never satisfy it.
        held = wait_for(control, "the controller to be at rest after the constant-mix hold",
                        lambda r: r.get("flipctl_state") == "anchored", 90)
        check("stationary multi-key mix completes no flip", motion(held), baseline)
        # The defect, stated as the controller's own arithmetic: a workload whose commands, keys
        # and value bytes never change must never present the mix detector with a distance that
        # reaches its band.  The unpatched tree reaches 204x here.
        check("constant mix keeps the mix distance inside its own band (worst %.3fx)" % worst,
              worst < 1.0, True)
        print("negative: %.0fs of constant mix with sweeping parse-pass occupancy -- "
              "fingerprint_triggers=%s completed=%s transferred=%s, anchor %s:%s (unmoved); "
              "worst mix distance = %.4f of its band; total triggers %s -> %s"
              % (args.hold_seconds, baseline[0], baseline[1], baseline[2],
                 held["flipctl_anchor_io"], held["flipctl_anchor_ex"], worst,
                 anchored["flipctl_triggers"], held["flipctl_triggers"]))

        # ---- POSITIVE: a real mix change must still be SEEN and acted on --------------------------
        before_triggers = int(held["flipctl_triggers"])
        batch[0] = 8
        mode[0] = "single"
        # Watch the detector itself.  A counter would let a rate trigger stand in for the mix
        # trigger; the distance/band ratio cannot be satisfied by anything but the mix detector
        # actually seeing the change, which is the property the fix could have broken.
        seen = 0.0
        end = time.monotonic() + args.mix_timeout
        while time.monotonic() < end and seen <= 1.0:
            if errors:
                raise AssertionError("load driver failed: %s" % errors[0])
            reading = detector(control)
            if reading and reading[1] > 0:
                seen = max(seen, reading[0] / reading[1])
            time.sleep(0.1)
        check("a real mix change clears the mix detector's own band (reached %.2fx)" % seen,
              seen > 1.0, True)
        final = wait_for(control, "the mix-change maneuver to re-anchor",
                         lambda r: r.get("flipctl_state") == "anchored" and
                         int(r.get("flipctl_triggers", "0")) > before_triggers,
                         args.mix_timeout)
        print("positive: multi-key -> single-key GET drove the mix distance to %.2fx its band "
              "and the controller re-maneuvered and re-anchored at %s:%s (triggers %s -> %s)"
              % (seen, final["flipctl_anchor_io"], final["flipctl_anchor_ex"],
                 before_triggers, final["flipctl_triggers"]))
    finally:
        stop.set()
        for thread in threads:
            thread.join(10)
        control.close()

    if errors:
        raise AssertionError("load driver failed: %s" % errors[0])
    print("ok: flip multi-key hold (%d checks)" % CHECKS[0])


if __name__ == "__main__":
    main()
