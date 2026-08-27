#!/usr/bin/env python3
"""EXEC visibility to concurrent readers -- the cross-shard read fan-out gate.

Usage: execatomic.py HOST PORT

THE DEFECT THIS GATE LOCKS
--------------------------
EXEC is all-or-nothing to concurrent readers in BOTH atomic modes.  That is not an accident of
--atomic 1: EXEC force-admits through the atomic group window even at --atomic 0 (multi.inc), its
queued writes are installed as private candidates at epoch zero, and the last participating owner
draws and release-publishes exactly ONE ticket for the whole transaction (multi.inc:1352).  A
reader must therefore see either every write of a transaction or none of them.

It did not.  A cross-shard READ resolves each of its fragments on that fragment's own owner, at
that fragment's own moment.  Whether the read pinned a cut was decided from `tracking` --  a live
sample of the global atomic-activity word (scatter_engine.inc) -- and EXEC is itself what writes
that word, so between two transactions the word reads zero and the read went out with NO cut.
Every fragment then answered "newest committed right now", and a transaction that published its
one ticket while the fan-out was in flight was seen by the fragments that ran after it and missed
by the ones that ran before: one MGET, two transactions, e.g. [238,238,239,238,238,238,238,238].

Contention did not cause it.  Contention only stretched the fan-out from microseconds to
milliseconds, which is why a quiet gate saw 0/18 and eight spinners saw 15/20.

NOT VACUOUS, BY CONSTRUCTION
----------------------------
- GEOMETRY.  The hash seed is drawn from the kernel at every boot, so this battery asks
  DEBUG SHARD for the real owner of every key and refuses to pass unless the read spans more than
  one owner.  A single-owner read resolves in one task and cannot straddle anything.
- DETERMINISM.  DEBUG ATOMIC-FANOUT-DEFER parks every fragment of a cross-shard read except the one
  on its lead shard.  A park, not a stall: the executor stays free, so the transaction being raced
  really does run and commit inside the window.  The straddle is then produced on demand instead of
  once per few thousand contended reads.
- THE WINDOW REALLY OPENED.  Each armed round asserts the transaction's own reply landed BEFORE the
  parked read's reply, and that the read was held for a real fraction of the requested park.  An
  unarmed control round asserts the same shape completes in a small fraction of that time, so a
  passing armed round cannot be explained by "the hook did nothing".
- COUNTERS.  atomic_fanout_cuts counts exactly the reads that pinned a cut although the tracking
  word read zero -- the path the fix added.  At --atomic 0 the battery asserts it advanced.
- NEGATIVE CONTROL.  A pinned cut must be a cut, not a freeze: a transaction that commits BEFORE
  the read is issued must be fully visible to it.

Boot: --enable-debug-command yes.  Without it the armed arms cannot run and the battery says so.
"""

import socket
import sys
import threading
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
FAIL = 0
KEYS = ["execatomic:%d" % i for i in range(8)]
HOLD_US = 400000          # 400ms park for the fan-out window
ROUNDS = 4


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
        self.send(*args)
        return self.read()


ADMIN = Resp()


def info_field(field):
    text = ADMIN.cmd("INFO", "stats")
    if not isinstance(text, (bytes, bytearray)):
        return None
    for line in text.decode(errors="replace").split("\r\n"):
        if line.startswith(field + ":"):
            return int(line.split(":", 1)[1])
    return None


def set_atomic(value):
    return ADMIN.cmd("CONFIG", "SET", "atomic", str(value)) == b"OK"


def arm(microseconds):
    return ADMIN.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", str(microseconds)) == b"OK"


def transaction(client, keys, value):
    """MULTI + SET every key + EXEC on one connection; returns the EXEC reply."""
    if client.cmd("MULTI") != b"OK":
        raise AssertionError("MULTI refused")
    for key in keys:
        if client.cmd("SET", key, value) != b"QUEUED":
            raise AssertionError("SET was not queued")
    return client.cmd("EXEC")


# ---- geometry oracle -----------------------------------------------------------------------
HAVE_DEBUG = not isinstance(ADMIN.cmd("DEBUG", "SHARD", KEYS[0]), (RespError, Exception))
SPAN = []
WALK_KEYS = []
WALK_SPAN = []
if HAVE_DEBUG:
    # Re-pick the key set on THIS boot's hash seed so the read really does fan out.  A set that
    # collapsed onto one owner would be serialised by that owner and prove nothing.
    picked, seen, probe = [], set(), 0
    while len(picked) < 8 and probe < 5000:
        key = "execatomic:%d" % probe
        owner = int(ADMIN.cmd("DEBUG", "SHARD", key))
        if owner not in seen:
            seen.add(owner)
            picked.append(key)
        probe += 1
    if len(picked) == 8:
        KEYS = picked
    SPAN = sorted(seen)
    # A whole-owner walker (KEYS) carries a fragment for EVERY shard, and its lead fragment is
    # shard 0.  A key set that misses shard 0 would leave the lead fragment holding none of the
    # keys under test, so it could not straddle anything and the arm would pass vacuously.  This
    # second set therefore covers every owner the router hands out.
    walk, walk_seen, probe = [], set(), 0
    while probe < 600:
        key = "execwalk:%d" % probe
        owner = int(ADMIN.cmd("DEBUG", "SHARD", key))
        if owner not in walk_seen:
            walk_seen.add(owner)
            walk.append(key)
        probe += 1
    WALK_KEYS = walk
    WALK_SPAN = sorted(walk_seen)
note("geometry: reads fan out over more than one owner",
     HAVE_DEBUG and len(SPAN) > 1 and len(WALK_SPAN) > 1 and WALK_SPAN[0] == 0,
     "keyed=%d over %s; walker=%d over %s%s"
     % (len(KEYS), SPAN, len(WALK_KEYS), WALK_SPAN, "" if HAVE_DEBUG else " (DEBUG disabled)"))


# ---- 1. deterministic straddle ---------------------------------------------------------------
def straddle_arm(mode, kind):
    """Park a cross-shard read across a whole transaction and demand one generation back."""
    if not HAVE_DEBUG:
        note("deterministic EXEC straddle: %s (atomic %d)" % (kind, mode), False,
             "needs --enable-debug-command yes")
        return
    keys = WALK_KEYS if kind == "KEYS" else KEYS
    torn, detail, opened, before_cuts = 0, [], 0, info_field("atomic_fanout_cuts")
    for round_id in range(ROUNDS):
        old, new = "g%d-old" % round_id, "g%d-new" % round_id
        writer = Resp()
        if kind in ("EXISTS", "KEYS"):
            # The transaction must CREATE the keys, otherwise an existence read answers the same
            # before and after it and the arm could not tear even on an unfixed engine.
            for key in keys:
                ADMIN.cmd("DEL", key)
        else:
            for key in keys:
                ADMIN.cmd("SET", key, old)
        if not arm(HOLD_US):
            note("deterministic EXEC straddle: %s (atomic %d)" % (kind, mode), False, "arm refused")
            writer.close()
            return
        reader = Resp()
        started = time.time()
        if kind == "MGET":
            reader.send("MGET", *keys)
        elif kind == "EXISTS":
            reader.send("EXISTS", *keys)
        else:
            reader.send("KEYS", "execwalk:*")
        time.sleep(0.05)                     # the lead fragment has answered; the rest are parked
        exec_started = time.time()
        reply = transaction(writer, keys, new)
        exec_done = time.time()
        writer.close()
        values = reader.read()
        elapsed = time.time() - started
        reader.close()
        arm(0)
        if reply != [b"OK"] * len(keys):
            detail.append("round %d EXEC=%r" % (round_id, reply))
            torn += 1
            continue
        # The window really opened: the whole transaction completed while the read was parked.
        if exec_done < started or elapsed < HOLD_US / 4e6:
            detail.append("round %d window did not open (read %.3fs, exec ended %.3fs in)"
                          % (round_id, elapsed, exec_done - started))
        else:
            opened += 1
        if kind == "MGET":
            ok = values and all(value == values[0] for value in values[1:])
            # The cut was pinned before the transaction arrived, so the answer is the OLD world.
            ok = ok and values[0] == old.encode()
        elif kind == "EXISTS":
            ok = values in (0, len(keys))
        else:
            mine = set(keys)
            ok = len([k for k in (values or []) if k.decode() in mine]) in (0, len(keys))
        if not ok:
            torn += 1
            if len(detail) < 3:
                detail.append("round %d saw %r" % (round_id, values))
    cuts = (info_field("atomic_fanout_cuts") or 0) - (before_cuts or 0)
    ok = torn == 0 and opened == ROUNDS
    if mode == 0:
        # The guarded path is exactly "pinned a cut although the tracking word read zero".
        ok = ok and cuts > 0
    note("deterministic EXEC straddle: %s (atomic %d)" % (kind, mode), ok,
         "rounds=%d torn=%d windows_opened=%d fanout_cuts=+%d %r"
         % (ROUNDS, torn, opened, cuts, detail[:2]))


# ---- 2. the park is what parks (unarmed control) ---------------------------------------------
def unarmed_control(mode):
    if not HAVE_DEBUG:
        note("unarmed control completes far inside the park budget (atomic %d)" % mode, False,
             "needs --enable-debug-command yes")
        return
    arm(0)
    for key in KEYS:
        ADMIN.cmd("SET", key, "control")
    reader = Resp()
    started = time.time()
    reader.send("MGET", *KEYS)
    values = reader.read()
    elapsed = time.time() - started
    reader.close()
    ok = elapsed < HOLD_US / 4e6 and values == [b"control"] * len(KEYS)
    note("unarmed control completes far inside the park budget (atomic %d)" % mode, ok,
         "elapsed=%.4fs budget=%.3fs" % (elapsed, HOLD_US / 1e6))


# ---- 3. a cut is a cut, not a freeze ----------------------------------------------------------
def visibility_control(mode):
    """A transaction that commits BEFORE the read is issued must be fully visible to it."""
    if not HAVE_DEBUG:
        note("committed transaction is fully visible to a later read (atomic %d)" % mode, False,
             "needs --enable-debug-command yes")
        return
    for key in KEYS:
        ADMIN.cmd("SET", key, "stale")
    writer = Resp()
    reply = transaction(writer, KEYS, "fresh")
    writer.close()
    arm(HOLD_US)
    reader = Resp()
    reader.send("MGET", *KEYS)
    values = reader.read()
    reader.close()
    arm(0)
    ok = reply == [b"OK"] * len(KEYS) and values == [b"fresh"] * len(KEYS)
    note("committed transaction is fully visible to a later read (atomic %d)" % mode, ok,
         "values=%r" % (values[:3],))


# ---- 4. read-your-writes survives the pinned cut ----------------------------------------------
def ryow_control(mode):
    """The cut must never hide the reading connection's OWN writes, plain or transactional."""
    client = Resp()
    try:
        for index, key in enumerate(KEYS):
            client.cmd("SET", key, "own%d" % index)
        plain = client.cmd("MGET", *KEYS)
        ok = plain == [("own%d" % i).encode() for i in range(len(KEYS))]
        reply = transaction(client, KEYS, "txn")
        ok = ok and reply == [b"OK"] * len(KEYS)
        after = client.cmd("MGET", *KEYS)
        ok = ok and after == [b"txn"] * len(KEYS)
        note("own plain and transactional writes stay visible under the cut (atomic %d)" % mode,
             ok, "plain=%r after=%r" % (plain[:2], after[:2]))
    finally:
        client.close()


# ---- 5. unarmed stress: the shape the contended box used to fail -----------------------------
def stress_arm(mode, seconds=2.0, readers=4):
    for key in KEYS:
        ADMIN.cmd("SET", key, "0")
    before_cuts = info_field("atomic_fanout_cuts") or 0
    stop = threading.Event()
    start = threading.Barrier(readers + 1)
    lock = threading.Lock()
    state = {"torn": 0, "reads": 0, "commits": 0}
    errors = []
    samples = []

    def writer():
        client = Resp()
        seq = 1
        try:
            start.wait()
            while not stop.is_set():
                reply = transaction(client, KEYS, str(seq))
                if reply != [b"OK"] * len(KEYS):
                    raise AssertionError("bad EXEC %r" % (reply,))
                with lock:
                    state["commits"] += 1
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
                values = client.cmd("MGET", *KEYS)
                with lock:
                    state["reads"] += 1
                    if not values or any(v != values[0] for v in values[1:]):
                        state["torn"] += 1
                        if len(samples) < 2:
                            samples.append(repr(values))
        except Exception as exc:
            with lock:
                errors.append("reader%d:%s" % (rid, exc))
        finally:
            client.close()

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader, args=(i,)) for i in range(readers)
    ]
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(35)
    alive = [t.name for t in threads if t.is_alive()]
    cuts = (info_field("atomic_fanout_cuts") or 0) - before_cuts
    ok = (not errors and not alive and state["torn"] == 0 and
          state["reads"] > 100 and state["commits"] > 10)
    if mode == 0:
        # Proves the readers really went through the newly-guarded path during THIS arm.
        ok = ok and cuts > 0
    note("concurrent MGET never straddles a transaction (atomic %d)" % mode, ok,
         "reads=%d commits=%d torn=%d fanout_cuts=+%d errors=%r %s"
         % (state["reads"], state["commits"], state["torn"], cuts, errors[:1], samples[:1]))


for atomic_mode in (0, 1):
    note("CONFIG SET atomic %d" % atomic_mode, set_atomic(atomic_mode))
    unarmed_control(atomic_mode)
    straddle_arm(atomic_mode, "MGET")
    straddle_arm(atomic_mode, "EXISTS")
    straddle_arm(atomic_mode, "KEYS")
    visibility_control(atomic_mode)
    ryow_control(atomic_mode)
    stress_arm(atomic_mode)

if HAVE_DEBUG:
    arm(0)
for key in KEYS + WALK_KEYS:
    ADMIN.cmd("DEL", key)
ADMIN.close()

if FAIL:
    raise SystemExit("%d EXEC fan-out checks failed" % FAIL)
print("EXEC fan-out battery passed", flush=True)
