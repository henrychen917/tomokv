#!/usr/bin/env python3
"""Epoch-MVCC torn-read, overlapping-writer, window, and live-flip gate."""

import socket
import sys
import threading
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
FAIL = 0


def note(name, ok, extra=""):
    global FAIL
    print(("  ok   " if ok else "  FAIL ") + name + (" " + extra if extra else ""), flush=True)
    if not ok:
        FAIL += 1


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind == b"+":
            return line[1:-2]
        if kind == b"-":
            raise RuntimeError(line[1:-2].decode(errors="replace"))
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return data
        if kind == b"*":
            count = int(line[1:-2])
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("bad RESP type %r" % line[:20])

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()


def config(name, value):
    c = Resp()
    try:
        return c.cmd("CONFIG", "SET", name, str(value)) == b"OK"
    finally:
        c.close()


def stats():
    c = Resp()
    try:
        body = c.cmd("INFO", "STATS").decode()
    finally:
        c.close()
    result = {}
    for line in body.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.startswith("atomic_"):
                result[key] = int(value)
    return result


def mset(client, keys, signature, value_bytes=0):
    args = ["MSET"]
    pad = b"x" * value_bytes
    encoded = signature.encode() + pad
    for key in keys:
        args.extend((key, encoded))
    return client.cmd(*args)


def signature(values):
    if not values or any(value is None for value in values):
        return None
    heads = [value.split(b"x", 1)[0] for value in values]
    return heads[0] if all(head == heads[0] for head in heads) else b"TORN"


def hammer(prefix, atomic, seconds=2.0, writers=2, readers=4):
    keys = ["%s:k%d" % (prefix, i) for i in range(8)]
    config("atomic", atomic)
    init = Resp()
    mset(init, keys, "%s:init" % prefix)
    init.close()
    stop = threading.Event()
    start = threading.Barrier(writers + readers)
    lock = threading.Lock()
    torn = 0
    reads = 0
    errors = []
    completed = set()

    def writer(wid):
        nonlocal errors
        client = Resp()
        seq = 0
        try:
            start.wait()
            while not stop.is_set():
                sig = "%s:w%d:%d" % (prefix, wid, seq)
                if mset(client, keys, sig) != b"OK":
                    raise AssertionError("MSET did not return OK")
                with lock:
                    completed.add(sig.encode())
                seq += 1
        except Exception as exc:
            with lock:
                errors.append("writer%d:%s" % (wid, exc))
        finally:
            client.close()

    def reader(rid):
        nonlocal torn, reads, errors
        client = Resp()
        try:
            start.wait()
            while not stop.is_set():
                values = client.cmd("MGET", *keys)
                sig = signature(values)
                with lock:
                    reads += 1
                    if sig == b"TORN":
                        torn += 1
        except Exception as exc:
            with lock:
                errors.append("reader%d:%s" % (rid, exc))
        finally:
            client.close()

    threads = ([threading.Thread(target=writer, args=(i,), daemon=True) for i in range(writers)] +
               [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(readers)])
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=10)
    final = Resp()
    final_values = final.cmd("MGET", *keys)
    final.close()
    return torn, reads, errors, signature(final_values), completed


# Gate-open proof: the test must actually catch the old first-hop physical tear.
off_torn, off_reads, off_errors, _, _ = hammer(
    "at:off", 0, seconds=3.0, writers=4, readers=8)
note("OFF control exposes torn MSET-8", off_torn > 0 and not off_errors,
     "torn=%d reads=%d errors=%r" % (off_torn, off_reads, off_errors))

# Main atomic arm. Both counters are vacuous-validation guards.
before = stats()
on_torn, on_reads, on_errors, _, _ = hammer("at:on", 1, seconds=2.5)
after = stats()
pred_delta = after.get("atomic_predecessor_reads", 0) - before.get("atomic_predecessor_reads", 0)
promo_delta = after.get("atomic_promotions", 0) - before.get("atomic_promotions", 0)
# V2 batches reclamation on owner passes and the 50ms low-frequency sweep instead of posting a
# cleanup task for every retired group. Give that deliberately cold path one bounded tick to fire.
deadline = time.time() + 1.5
while promo_delta == 0 and time.time() < deadline:
    time.sleep(0.05)
    after = stats()
    promo_delta = after.get("atomic_promotions", 0) - before.get("atomic_promotions", 0)
note("ON MSET-8/MGET-8 torn-free", on_torn == 0 and on_reads > 0 and not on_errors,
     "torn=%d reads=%d errors=%r" % (on_torn, on_reads, on_errors))
note("ON exercised predecessor resolution", pred_delta > 0, "delta=%d" % pred_delta)
note("ON exercised promotion", promo_delta > 0, "delta=%d" % promo_delta)
note("atomic_inflight returns to idle", after.get("atomic_inflight", -1) == 0,
     "value=%d" % after.get("atomic_inflight", -1))

# Two overlapping atomic writers on exactly the same key set. The final state after the cleanup
# opportunity supplied by the last MGET must be one complete group, never the physical inversion.
ov_torn, ov_reads, ov_errors, ov_final, ov_completed = hammer(
    "at:overlap", 1, seconds=2.5, writers=2, readers=5)
note("overlapping atomic writers never mix", ov_torn == 0 and ov_reads > 0 and not ov_errors,
     "torn=%d reads=%d errors=%r" % (ov_torn, ov_reads, ov_errors))
note("promotion leaves one exact final group",
     ov_final not in (None, b"TORN") and ov_final in ov_completed,
     "final=%r completed=%d" % (ov_final, len(ov_completed)))

# Admission liveness: with a one-group window, concurrent large groups must generate stalls and all
# stalled connections must resume after retire. Large values widen the admission interval without
# adding sleeps or server-side parking.
config("atomic", 1)
config("atomic-window", 1)
window_before = stats().get("atomic_window_stalls", 0)
window_run = format(time.time_ns() & 0xfffffff, "x")
gate = threading.Barrier(17)
window_errors = []


def window_writer(wid):
    client = Resp()
    # Thousands of tombstones make validate long enough for other IO threads to encounter the
    # global admission cap; unlike large values, the frames themselves stay cheap to receive.
    keys = ["aw%s:%x:%x" % (window_run, wid, i) for i in range(512)]
    try:
        gate.wait()
        if not isinstance(client.cmd("DEL", *keys), int):
            raise AssertionError("bad window reply")
    except Exception as exc:
        window_errors.append(str(exc))
    finally:
        client.close()


window_threads = [threading.Thread(target=window_writer, args=(i,), daemon=True) for i in range(16)]
for thread in window_threads:
    thread.start()
gate.wait()
for thread in window_threads:
    thread.join(timeout=30)
window_after = stats().get("atomic_window_stalls", 0)
note("atomic-window stalls and resumes",
     all(not thread.is_alive() for thread in window_threads) and not window_errors and
     window_after > window_before,
     "stalls=%d errors=%r" % (window_after - window_before, window_errors))
config("atomic-window", 256)

# Live CONFIG flips under active traffic are a liveness/safety arm. OFF intervals deliberately do
# not promise atomicity; after ending ON, one final group must be read intact.
flip_stop = threading.Event()
flip_errors = []


def flip_writer():
    client = Resp()
    keys = ["at:flip:k%d" % i for i in range(8)]
    seq = 0
    try:
        while not flip_stop.is_set():
            mset(client, keys, "flip:%d" % seq)
            seq += 1
    except Exception as exc:
        flip_errors.append(str(exc))
    finally:
        client.close()


thread = threading.Thread(target=flip_writer, daemon=True)
thread.start()
for i in range(40):
    if not config("atomic", i & 1):
        flip_errors.append("CONFIG SET failed")
flip_stop.set()
thread.join(timeout=15)
config("atomic", 1)
check = Resp()
flip_keys = ["at:flip:k%d" % i for i in range(8)]
mset(check, flip_keys, "flip:final")
flip_final = signature(check.cmd("MGET", *flip_keys))
check.close()
note("CONFIG SET atomic flip under load", not thread.is_alive() and not flip_errors and
     flip_final == b"flip:final", "errors=%r final=%r" % (flip_errors, flip_final))

print("ATOMIC_TORN " + ("PASS" if FAIL == 0 else "FAIL %d" % FAIL), flush=True)
sys.exit(1 if FAIL else 0)
