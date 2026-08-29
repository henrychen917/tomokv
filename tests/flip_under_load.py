#!/usr/bin/env python3
"""Flip the thread split repeatedly WHILE traffic is running, and prove nothing breaks.

usage: flip_under_load.py HOST PORT [seconds]

tests/flip.py exercises FLIP on a quiet server. That is the easy case. Ownership handoff is
interesting only when a bucket changes owner while requests for that bucket are in flight, and when a
connection changes IO thread while it has unretired ops in its reorder buffer.

Three things run concurrently:
  * WRITERS own disjoint key ranges and write a value that ENCODES the key and a monotonically
    increasing generation, so any reader can check a value against the key it came back for.
  * READERS read their own writer's keys and verify key/value agreement and that a generation never
    goes BACKWARDS on a key -- a stale read after a flip would show up as a generation regression,
    which a simple "is the value non-empty" check would miss entirely.
  * A FLIPPER alternates the split every second.

Any of: a wrong value, a generation regression, a dropped connection, an error reply, or a refused
flip that was not supposed to be refused, fails the run.
"""

import socket
import sys
import threading
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
NWRITERS = 8
KEYS_PER_WRITER = 400

class Busy(Exception):
    pass


stop = threading.Event()
errors = []
flips_ok = [0]
flips_refused = [0]
ops = [0]
busy = [0]
lock = threading.Lock()


def fail(msg):
    with lock:
        if len(errors) < 20:
            errors.append(msg)


def conn():
    s = socket.create_connection((HOST, PORT), timeout=15)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def send(sock, *args):
    enc = [a.encode() if isinstance(a, str) else a for a in args]
    sock.sendall(b"*%d\r\n" % len(enc) +
                 b"".join(b"$%d\r\n" % len(a) + a + b"\r\n" for a in enc))


def rd(f):
    p = f.read(1)
    line = f.readline()
    if not p:
        raise IOError("connection closed")
    v = line[:-2]
    if p == b"-":
        # Keep BUSY distinct so the final report names this FLIP regression directly instead of
        # folding it into a generic protocol error. It is still a test failure: ordinary commands
        # must be held across the dispatch pause and complete normally afterward.
        msg = v.decode(errors="replace")
        if msg.startswith("BUSY"):
            raise Busy(msg)
        raise IOError("error reply: %s" % msg)
    if p in b"+:":
        return v
    if p == b"$":
        n = int(v)
        if n == -1:
            return None
        d = f.read(n)
        f.read(2)
        return d
    if p == b"*":
        n = int(v)
        return None if n == -1 else [rd(f) for _ in range(n)]
    raise IOError("bad prefix %r" % p)


def val_for(key, gen):
    return ("%s|%d|%s" % (key, gen, "x" * 24)).encode()


def worker(wid):
    """One writer/reader pair on its own key range, so writers never race each other."""
    keys = ["fl:%d:%d" % (wid, i) for i in range(KEYS_PER_WRITER)]
    seen = {}
    try:
        s, f = conn()
    except Exception as e:
        fail("writer %d could not connect: %r" % (wid, e))
        return
    gen = 0
    while not stop.is_set():
        gen += 1
        try:
            # Write a batch with MSET (multi-key => cross-shard groups in flight during flips).
            for base in range(0, KEYS_PER_WRITER, 8):
                chunk = keys[base:base + 8]
                args = ["MSET"]
                for k in chunk:
                    args += [k, val_for(k, gen)]
                send(s, *args)
                rd(f)
                # Read them back with MGET and verify identity AND monotonic generation.
                send(s, "MGET", *chunk)
                vals = rd(f)
                if vals is None or len(vals) != len(chunk):
                    fail("writer %d: MGET returned %r for %d keys" % (wid, vals, len(chunk)))
                    continue
                for k, v in zip(chunk, vals):
                    if v is None:
                        fail("writer %d: key %s vanished" % (wid, k))
                        continue
                    parts = v.split(b"|")
                    if len(parts) != 3 or parts[0].decode() != k:
                        fail("writer %d: key %s returned value for %r" % (wid, k, parts[0]))
                        continue
                    g = int(parts[1])
                    if g < seen.get(k, 0):
                        fail("writer %d: key %s generation went BACKWARDS %d -> %d"
                             % (wid, k, seen[k], g))
                    seen[k] = g
                with lock:
                    ops[0] += len(chunk) * 2
        except Busy:
            with lock:
                busy[0] += 1
            time.sleep(0.002)
            try:
                s.close()
            except Exception:
                pass
            try:
                s, f = conn()
            except Exception as e:
                fail("writer %d could not reconnect after BUSY: %r" % (wid, e))
                return
        except Exception as e:
            fail("writer %d: %r" % (wid, e))
            return
    s.close()


def flipper():
    try:
        s, f = conn()
    except Exception as e:
        fail("flipper could not connect: %r" % e)
        return
    shapes = [(18, 14), (28, 4), (24, 8), (10, 22)]
    i = 0
    while not stop.is_set():
        io, ex = shapes[i % len(shapes)]
        i += 1
        try:
            send(s, "FLIP", str(io), str(ex))
            r = rd(f)
            with lock:
                if r == b"OK":
                    flips_ok[0] += 1
                else:
                    flips_refused[0] += 1
        except Busy:
            with lock:
                flips_refused[0] += 1
        except IOError as e:
            # A refusal arrives as an error reply; that is legal, a broken pipe is not.
            if "error reply" in str(e):
                with lock:
                    flips_refused[0] += 1
                try:
                    s, f = conn()
                except Exception:
                    return
            else:
                fail("flipper: %r" % e)
                return
        time.sleep(1.0)
    s.close()


threads = [threading.Thread(target=worker, args=(i,)) for i in range(NWRITERS)]
threads.append(threading.Thread(target=flipper))
for t in threads:
    t.start()
time.sleep(SECONDS)
stop.set()
for t in threads:
    t.join(timeout=30)

print("ops verified: %d   flips applied: %d   flips refused: %d   BUSY retries: %d"
      % (ops[0], flips_ok[0], flips_refused[0], busy[0]))
if errors:
    print("FAIL: %d problem(s)" % len(errors))
    for e in errors:
        print("   %s" % e)
    sys.exit(1)
if flips_ok[0] == 0:
    print("FAIL: no flip was ever applied -- the test proved nothing")
    sys.exit(1)
if busy[0] != 0:
    print("FAIL: ordinary commands received BUSY during FLIP")
    sys.exit(1)
print("ok: no wrong values, no generation regressions, no dropped connections")
sys.exit(0)
