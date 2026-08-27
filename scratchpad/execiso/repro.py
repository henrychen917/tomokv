#!/usr/bin/env python3
"""t-execiso reproduction probe.

Does a cross-shard read INSIDE MULTI/EXEC tear while the identical BARE read does not?

Arms (each is `readers` reader connections + optionally one writer connection running
MULTI / SET k0..k7 <seq> / EXEC in a loop):

  bare-span      readers issue a plain  MGET k0..k7          keys span >1 owner
  exec-span      readers issue MULTI / MGET k0..k7 / EXEC    keys span >1 owner
  exec-noWriter  same as exec-span, writer disabled          <- must read ZERO
  exec-same      same as exec-span, all keys on ONE owner    <- must read ZERO

`torn` = an MGET reply whose elements are not all equal, i.e. one read that saw two different
transaction generations.  The writer only ever publishes one generation at a time through a single
EXEC ticket, so any mixture is a straddle.

atomic_fanout_cuts is sampled around every arm: it counts reads that pinned a read cut although the
global atomic-activity word read zero.  It is the proof that an arm entered the read-cut machinery
at all.  An arm that tears with fanout_cuts=+0 never entered it.

Usage: repro.py HOST PORT SECONDS [READERS] [--no-debug]
   --no-debug: the target has no DEBUG SHARD (vanilla redis).  Key sets are then taken verbatim
   and the same-owner arm is skipped, because on a single-threaded oracle every key is same-owner.
"""

import socket
import sys
import threading
import time

HOST = sys.argv[1]
PORT = int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
READERS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
HAVE_DEBUG = "--no-debug" not in sys.argv


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=60)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind == b"+":
            return line[1:-2]
        if kind == b"-":
            return RespError(line[1:-2].decode(errors="replace"))
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            data = self.file.read(size)
            self.file.read(2)
            return data
        if kind == b"*":
            count = int(line[1:-2])
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("bad RESP %r" % line[:20])

    def cmd(self, *args):
        self.send(*args)
        return self.read()


ADMIN = Resp()


def info_field(field):
    text = ADMIN.cmd("INFO", "stats")
    if not isinstance(text, (bytes, bytearray)):
        return 0
    for line in text.decode(errors="replace").split("\r\n"):
        if line.startswith(field + ":"):
            return int(line.split(":", 1)[1])
    return 0


def owner(key):
    return int(ADMIN.cmd("DEBUG", "SHARD", key))


# ---- key sets, re-picked on THIS boot's hash seed --------------------------------------------
SPAN_KEYS = ["execiso:%d" % i for i in range(8)]
SAME_KEYS = []
SPAN, SAME_OWNER = [], None
if HAVE_DEBUG:
    picked, seen, probe = [], set(), 0
    while len(picked) < 8 and probe < 8000:
        key = "execiso:%d" % probe
        who = owner(key)
        if who not in seen:
            seen.add(who)
            picked.append(key)
        probe += 1
    if len(picked) == 8:
        SPAN_KEYS = picked
    SPAN = sorted(seen)
    # Same-owner control: eight keys that all land on ONE shard.  A read whose fragments all run
    # in a single owner task cannot straddle anything, so this arm must read zero torn.
    buckets = {}
    probe = 0
    while probe < 20000:
        key = "execsame:%d" % probe
        buckets.setdefault(owner(key), []).append(key)
        if len(buckets[owner(key)]) >= 8:
            SAME_OWNER = owner(key)
            SAME_KEYS = buckets[SAME_OWNER][:8]
            break
        probe += 1


def run_arm(name, keys, in_exec, with_writer):
    for key in keys:
        ADMIN.cmd("SET", key, "0")
    before = info_field("atomic_fanout_cuts")
    stop = threading.Event()
    start = threading.Barrier(READERS + (1 if with_writer else 0))
    lock = threading.Lock()
    stat = {"torn": 0, "reads": 0, "commits": 0}
    errors, samples = [], []

    def writer():
        client = Resp()
        seq = 1
        try:
            start.wait()
            while not stop.is_set():
                assert client.cmd("MULTI") == b"OK"
                for key in keys:
                    assert client.cmd("SET", key, str(seq)) == b"QUEUED"
                reply = client.cmd("EXEC")
                assert reply == [b"OK"] * len(keys), reply
                with lock:
                    stat["commits"] += 1
                seq += 1
        except Exception as exc:
            with lock:
                errors.append("writer:%s" % exc)
        finally:
            client.close()

    def reader(rid):
        client = Resp()
        try:
            start.wait()
            while not stop.is_set():
                if in_exec:
                    assert client.cmd("MULTI") == b"OK"
                    assert client.cmd("MGET", *keys) == b"QUEUED"
                    reply = client.cmd("EXEC")
                    values = reply[0] if isinstance(reply, list) and reply else None
                else:
                    values = client.cmd("MGET", *keys)
                with lock:
                    stat["reads"] += 1
                    if not values or any(v != values[0] for v in values[1:]):
                        stat["torn"] += 1
                        if len(samples) < 2:
                            samples.append(repr(values))
        except Exception as exc:
            with lock:
                errors.append("reader%d:%s" % (rid, exc))
        finally:
            client.close()

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(READERS)]
    if with_writer:
        threads.append(threading.Thread(target=writer))
    for thread in threads:
        thread.start()
    time.sleep(SECONDS)
    stop.set()
    for thread in threads:
        thread.join(60)
    cuts = info_field("atomic_fanout_cuts") - before
    rate = 100.0 * stat["torn"] / stat["reads"] if stat["reads"] else 0.0
    print("%-14s reads=%-8d commits=%-7d torn=%-7d rate=%7.3f%%  fanout_cuts=+%-8d %s%s"
          % (name, stat["reads"], stat["commits"], stat["torn"], rate, cuts,
             ("errors=%r " % errors[:1]) if errors else "", samples[:1]),
          flush=True)
    return stat, rate, cuts


print("geometry: span keys over owners %s ; same-owner set on shard %s (%d keys)"
      % (SPAN or "unknown", SAME_OWNER, len(SAME_KEYS)), flush=True)
if HAVE_DEBUG and len(SPAN) < 2:
    raise SystemExit("REFUSE: span key set does not span >1 owner; the arm could not straddle")

run_arm("bare-span", SPAN_KEYS, in_exec=False, with_writer=True)
run_arm("exec-span", SPAN_KEYS, in_exec=True, with_writer=True)
run_arm("exec-noWriter", SPAN_KEYS, in_exec=True, with_writer=False)
if SAME_KEYS:
    run_arm("exec-same", SAME_KEYS, in_exec=True, with_writer=True)
else:
    print("exec-same      skipped (no DEBUG SHARD / no 8-key single-owner set)", flush=True)

for key in SPAN_KEYS + SAME_KEYS:
    ADMIN.cmd("DEL", key)
ADMIN.close()
