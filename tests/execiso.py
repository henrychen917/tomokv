#!/usr/bin/env python3
"""Cross-shard reads inside EXEC remain coherent under concurrent writes.

Usage: execiso.py HOST PORT

Write units hold read/write claims until their one commit. The directed arms
add a distinct marker write, park their read fragments, and require foreign
writers to wait without cancelling or replaying the holder. Pure read-only
EXEC uses MGET's registered cut; the bare reference arms retain their atomic
transaction writer and finite read cut. Geometry is discovered on every boot.

Boot with --enable-debug-command yes. Both atomic settings are exercised.
"""

import socket
import sys
import threading
import time

import _lib


HOST, PORT = sys.argv[1], int(sys.argv[2])
FAIL = 0
HOLD_US = 300000          # 300ms park for the in-EXEC fan-out window
ROUNDS = 3


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
READ_LOCAL = b"\r\nread_local:1\r\n" in ADMIN.cmd("INFO", "server")


def info_field(field):
    text = ADMIN.cmd("INFO", "stats")
    if not isinstance(text, (bytes, bytearray)):
        return 0
    for line in text.decode(errors="replace").split("\r\n"):
        if line.startswith(field + ":"):
            return int(line.split(":", 1)[1])
    return 0


def set_atomic(value):
    return ADMIN.cmd("CONFIG", "SET", "atomic", str(value)) == b"OK"


def arm(microseconds):
    return ADMIN.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", str(microseconds)) == b"OK"


def transaction(client, commands):
    """MULTI + every command + EXEC on one connection; returns the EXEC reply."""
    if client.cmd("MULTI") != b"OK":
        raise AssertionError("MULTI refused")
    for command in commands:
        if client.cmd(*command) != b"QUEUED":
            raise AssertionError("%r was not queued" % (command,))
    return client.cmd("EXEC")


def string_writer(keys, value):
    return [("SET", key, value) for key in keys]


def set_writer(keys, old, new):
    # One transaction, one ticket: every set must flip generation together.
    commands = []
    for key in keys:
        commands.append(("SREM", key, old))
        commands.append(("SADD", key, new))
    return commands


# ---- geometry oracle -----------------------------------------------------------------------
KEYS = ["execiso:%d" % i for i in range(8)]
SETS = ["execisoset:%d" % i for i in range(8)]
SAME = []
HAVE_DEBUG = not isinstance(ADMIN.cmd("DEBUG", "SHARD", KEYS[0]), (RespError, Exception))
SPAN, SET_SPAN, SAME_OWNER = [], [], None
if HAVE_DEBUG:
    def pick_spanning(prefix, wanted=8, limit=8000):
        picked, seen, probe = [], set(), 0
        while len(picked) < wanted and probe < limit:
            key = "%s:%d" % (prefix, probe)
            owner = int(ADMIN.cmd("DEBUG", "SHARD", key))
            if (owner not in seen and
                    (len(picked) != 1 or shard_owner[owner] != shard_owner[next(iter(seen))])):
                seen.add(owner)
                picked.append(key)
            probe += 1
        return picked, sorted(seen)

    # DEBUG SHARD returns a shard ID, not an executor ID. Prove the participating owners.
    geometry = _lib.Conn(HOST, PORT)
    try:
        shard_owner = _lib.topology(geometry).shard_owner
    finally:
        geometry.close()
    picked, span_shards = pick_spanning("execiso")
    SPAN = sorted({shard_owner[sid] for sid in span_shards})
    if len(picked) == 8:
        KEYS = picked
    picked, set_span_shards = pick_spanning("execisoset")
    SET_SPAN = sorted({shard_owner[sid] for sid in set_span_shards})
    if len(picked) == 8:
        SETS = picked
    # A same-owner set of eight keys: its read resolves inside ONE owner task, so it cannot
    # straddle anything and must therefore never pay for a cut.
    buckets, probe = {}, 0
    while probe < 20000 and not SAME:
        key = "execisosame:%d" % probe
        owner = int(ADMIN.cmd("DEBUG", "SHARD", key))
        buckets.setdefault(owner, []).append(key)
        if len(buckets[owner]) >= 8:
            SAME_OWNER, SAME = owner, buckets[owner][:8]
        probe += 1
note("geometry: in-EXEC reads fan out over more than one owner",
     HAVE_DEBUG and len(SPAN) > 1 and len(SET_SPAN) > 1 and len(SAME) == 8,
     "strings=%d over %s; sets=%d over %s; same-owner=%d on shard %s%s"
     % (len(KEYS), SPAN, len(SETS), SET_SPAN, len(SAME), SAME_OWNER,
        "" if HAVE_DEBUG else " (DEBUG disabled)"))


# ---- 1. deterministic in-EXEC straddle --------------------------------------------------------
def straddle_arm(mode, kind):
    """Park an in-EXEC cross-shard read across a whole foreign transaction; demand ONE generation.

    `kind` also selects the BARE reference arm, which runs the identical shape without MULTI: the
    contract is stated relative to bare, so bare is measured in the same battery.
    """
    label = "deterministic in-EXEC straddle: %s (atomic %d)" % (kind, mode)
    if not HAVE_DEBUG:
        note(label, False, "needs --enable-debug-command yes")
        return
    keys = SETS if kind == "SUNION" else KEYS
    torn, detail, opened = 0, [], 0
    before_cuts = info_field("atomic_exec_read_cuts")
    before_dooms = info_field("atomic_txn_dooms")
    before_retries = info_field("atomic_txn_retries")
    before_waits = info_field("atomic_txn_writer_waits")
    for round_id in range(ROUNDS):
        old, new = "g%d-old" % round_id, "g%d-new" % round_id
        if kind == "EXISTS":
            for key in keys:
                ADMIN.cmd("DEL", key)
            commands = string_writer(keys, new)
        elif kind == "SUNION":
            for key in keys:
                ADMIN.cmd("DEL", key)
                ADMIN.cmd("SADD", key, old)
            commands = set_writer(keys, old, new)
        else:
            for key in keys:
                ADMIN.cmd("SET", key, old)
            commands = string_writer(keys, new)

        if not arm(HOLD_US):
            note(label, False, "arm refused")
            return
        reader = Resp()
        started = time.time()
        # Issue MULTI/<read>/EXEC and DO NOT read the EXEC reply yet: the lead fragment answers
        # immediately, the rest are parked, and the foreign transaction runs inside that window.
        if reader.cmd("MULTI") != b"OK":
            note(label, False, "MULTI refused")
            reader.close()
            return
        read_cmd = {"MGET": ("MGET",) + tuple(keys),
                    "EXISTS": ("EXISTS",) + tuple(keys),
                    "SUNION": ("SUNION",) + tuple(keys)}[kind]
        marker = next("execiso-marker:%d:%d" % (round_id, i) for i in range(4096)
                      if ADMIN.cmd("DEBUG", "SHARD", "execiso-marker:%d:%d" % (round_id, i)) ==
                         ADMIN.cmd("DEBUG", "SHARD", keys[0]))
        assert reader.cmd("INCR", marker) == b"QUEUED"
        if reader.cmd(*read_cmd) != b"QUEUED":
            note(label, False, "read was not queued")
            reader.close()
            return
        reader.send("EXEC")
        time.sleep(0.05)                     # the lead fragment has answered; the rest are parked
        arm(0)                              # replacement attempts must not inherit the park
        writer = Resp()
        waits = info_field("atomic_txn_writer_waits")
        for command in commands:
            writer.send(*command)
        end = time.monotonic() + HOLD_US / 1e6
        while info_field("atomic_txn_writer_waits") == waits and time.monotonic() < end:
            time.sleep(.001)
        blocked = info_field("atomic_txn_writer_waits") > waits
        outer = reader.read()
        exec_done = time.time()
        reply = [writer.read() for command in commands]
        writer.close()
        elapsed = time.time() - started
        reader.close()
        arm(0)

        expected_writes = len(commands)
        if not isinstance(reply, list) or len(reply) != expected_writes or \
                any(isinstance(r, RespError) for r in reply):
            detail.append("round %d foreign writes=%r" % (round_id, reply))
            torn += 1
            continue
        if not isinstance(outer, list) or len(outer) != 2:
            detail.append("round %d in-EXEC reply=%r" % (round_id, outer))
            torn += 1
            continue
        values = outer[1]
        # The window opened only if a foreign writer encountered the held claim.
        if not blocked or exec_done < started or elapsed < HOLD_US / 4e6:
            detail.append("round %d window did not open (read %.3fs, foreign exec ended %.3fs in)"
                          % (round_id, elapsed, exec_done - started))
        else:
            opened += 1
        if kind == "MGET":
            ok = bool(values) and all(value == values[0] for value in values[1:])
            # Claims keep the old generation stable until this write unit commits.
            ok = ok and values[0] == old.encode()
        elif kind == "EXISTS":
            ok = values == 0
        else:
            ok = isinstance(values, list) and len(values) == 1 and values[0] == old.encode()
        if not ok:
            torn += 1
            if len(detail) < 3:
                detail.append("round %d saw %r" % (round_id, values))
    cuts = info_field("atomic_exec_read_cuts") - before_cuts
    dooms = info_field("atomic_txn_dooms") - before_dooms
    retries = info_field("atomic_txn_retries") - before_retries
    waits = info_field("atomic_txn_writer_waits") - before_waits
    ok = torn == 0 and opened == ROUNDS and cuts >= ROUNDS and dooms == 0 and retries == 0 and waits > 0
    note(label, ok, "rounds=%d torn=%d windows_opened=%d exec_read_cuts=+%d dooms=+%d retries=+%d %r"
         % (ROUNDS, torn, opened, cuts, dooms, retries, detail[:2]))


# ---- 2. the bar itself: the same shape run BARE ------------------------------------------------
def bare_reference_arm(mode):
    """EXEC is measured against bare, so bare is measured here, under the same armed park."""
    label = "bare reference: the same parked MGET straddle is clean (atomic %d)" % mode
    if not HAVE_DEBUG:
        note(label, False, "needs --enable-debug-command yes")
        return
    torn, detail, opened = 0, [], 0
    # The historical fanout counter counts only tracking-OFF cuts: old-generation
    # debt can keep tracking on even after CONFIG atomic 0. Its delta is diagnostic.
    # On an armed local boot, WATCH fallback proves owner routing in either atomic mode.
    cut_counter = "read_local_mget_fallback_watch" if READ_LOCAL else "atomic_fanout_cuts"
    require_counter = READ_LOCAL
    registered = 0
    for round_id in range(ROUNDS):
        old, new = "b%d-old" % round_id, "b%d-new" % round_id
        for key in KEYS:
            ADMIN.cmd("SET", key, old)
        if not arm(HOLD_US):
            note(label, False, "arm refused")
            return
        reader = Resp()
        # This reference specifically tests the scatter read-cut path. WATCH routes a bare
        # MGET through its owners without putting it inside MULTI. An enabled local lane
        # otherwise pauses before capture and can validly return the entire newer image;
        # that is not the pinned-cut witness this reference claims. Keep the exact OLD-world
        # oracle and require the real fanout-cut counter, including on local-read boots.
        if reader.cmd("WATCH", KEYS[0]) != b"OK":
            raise AssertionError("could not route the bare reference through its shard owners")
        before_cut = info_field(cut_counter)
        started = time.time()
        reader.send("MGET", *KEYS)
        time.sleep(0.05)
        # Sample before the writer: its transaction cannot satisfy the bare-read witness.
        registered += info_field(cut_counter) > before_cut
        writer = Resp()
        reply = transaction(writer, string_writer(KEYS, new))
        exec_done = time.time()
        writer.close()
        values = reader.read()
        elapsed = time.time() - started
        reader.close()
        arm(0)
        if reply != [b"OK"] * len(KEYS):
            detail.append("round %d foreign EXEC=%r" % (round_id, reply))
            torn += 1
            continue
        if exec_done >= started and elapsed >= HOLD_US / 4e6:
            opened += 1
        else:
            detail.append("round %d window did not open (%.3fs)" % (round_id, elapsed))
        if not values or any(v != values[0] for v in values[1:]) or values[0] != old.encode():
            torn += 1
            if len(detail) < 3:
                detail.append("round %d saw %r" % (round_id, values))
    note(label, torn == 0 and opened == ROUNDS and (registered == ROUNDS or not require_counter),
         "rounds=%d torn=%d windows_opened=%d route_witness=%d (%s) %r"
         % (ROUNDS, torn, opened, registered, cut_counter if require_counter else "exact pinned-old oracle", detail[:2]))


# ---- 3. the park is what parks (unarmed control) ----------------------------------------------
def unarmed_control(mode):
    label = "unarmed in-EXEC read completes far inside the park budget (atomic %d)" % mode
    if not HAVE_DEBUG:
        note(label, False, "needs --enable-debug-command yes")
        return
    arm(0)
    for key in KEYS:
        ADMIN.cmd("SET", key, "control")
    reader = Resp()
    started = time.time()
    reply = transaction(reader, [("MGET",) + tuple(KEYS)])
    elapsed = time.time() - started
    reader.close()
    ok = elapsed < HOLD_US / 4e6 and reply == [[b"control"] * len(KEYS)]
    note(label, ok, "elapsed=%.4fs budget=%.3fs" % (elapsed, HOLD_US / 1e6))


# ---- 4. a cut is a cut, not a freeze -----------------------------------------------------------
def visibility_control(mode):
    """A transaction that commits BEFORE the reader's EXEC is issued must be fully visible to it."""
    label = "committed transaction is fully visible to a later in-EXEC read (atomic %d)" % mode
    if not HAVE_DEBUG:
        note(label, False, "needs --enable-debug-command yes")
        return
    for key in KEYS:
        ADMIN.cmd("SET", key, "stale")
    writer = Resp()
    reply = transaction(writer, string_writer(KEYS, "fresh"))
    writer.close()
    arm(HOLD_US)
    reader = Resp()
    outer = transaction(reader, [("MGET",) + tuple(KEYS)])
    reader.close()
    arm(0)
    ok = reply == [b"OK"] * len(KEYS) and outer == [[b"fresh"] * len(KEYS)]
    note(label, ok, "values=%r" % (outer[0][:3] if isinstance(outer, list) and outer else outer,))


# ---- 5. read-your-writes survives the pinned cut ------------------------------------------------
def ryow_control(mode):
    """The cut must never hide the reading connection's own writes -- plain, or earlier in the
    SAME transaction. The in-transaction case is the load-bearing one: those writes are private
    epoch-zero candidates, visible only through the read context's origin_conn_id overlay."""
    client = Resp()
    try:
        for index, key in enumerate(KEYS):
            client.cmd("SET", key, "own%d" % index)
        outer = transaction(client, [("MGET",) + tuple(KEYS)])
        ok = outer == [[("own%d" % i).encode() for i in range(len(KEYS))]]
        note("own plain writes stay visible to a later in-EXEC read (atomic %d)" % mode, ok,
             "values=%r" % (outer[0][:2] if isinstance(outer, list) and outer else outer,))
        # SET k0 then MGET, inside ONE transaction: the MGET must see the write it follows.
        inner = transaction(client, [("SET", KEYS[0], "mine"), ("MGET",) + tuple(KEYS)])
        ok = (isinstance(inner, list) and len(inner) == 2 and inner[0] == b"OK" and
              inner[1][0] == b"mine" and inner[1][1:] ==
              [("own%d" % i).encode() for i in range(1, len(KEYS))])
        note("own in-transaction write is visible to a later read in the same EXEC (atomic %d)"
             % mode, ok, "values=%r" % (inner[1][:2] if isinstance(inner, list) and
                                        len(inner) == 2 else inner,))
    finally:
        client.close()


# ---- 6. scope: a same-owner in-EXEC read must pay nothing ---------------------------------------
def scope_control(mode):
    label = "same-owner in-EXEC read registers NO cut (atomic %d)" % mode
    if not SAME:
        note(label, False, "no 8-key single-owner set found")
        return
    for key in SAME:
        ADMIN.cmd("SET", key, "same")
    before = info_field("atomic_exec_read_cuts")
    client = Resp()
    outer = transaction(client, [("MGET",) + tuple(SAME)])
    client.close()
    cuts = info_field("atomic_exec_read_cuts") - before
    ok = cuts == 0 and outer == [[b"same"] * len(SAME)]
    note(label, ok, "exec_read_cuts=+%d owner=%s" % (cuts, SAME_OWNER))


def cost_control(mode):
    """A write-only transaction must register no cut: the fix is off for everything it does not
    need to be on for, and this is the arm that would catch it being on."""
    before = info_field("atomic_exec_read_cuts")
    client = Resp()
    reply = transaction(client, string_writer(KEYS, "writeonly"))
    client.close()
    cuts = info_field("atomic_exec_read_cuts") - before
    ok = cuts == 0 and reply == [b"OK"] * len(KEYS)
    note("write-only transaction registers NO cut (atomic %d)" % mode, ok,
         "exec_read_cuts=+%d" % cuts)


# ---- 7. unarmed stress: the shape that reproduced the defect ------------------------------------
def stress_arm(mode, seconds=2.0, readers=3):
    for key in KEYS:
        ADMIN.cmd("SET", key, "0")
    before_cuts = info_field("atomic_exec_read_cuts")
    stop = threading.Event()
    start = threading.Barrier(readers + 1)
    lock = threading.Lock()
    state = {"torn": 0, "reads": 0, "commits": 0}
    errors, samples = [], []

    def writer():
        client = Resp()
        seq = 1
        try:
            start.wait()
            while not stop.is_set():
                reply = transaction(client, string_writer(KEYS, str(seq)))
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
                outer = transaction(client, [("MGET",) + tuple(KEYS)])
                values = outer[0] if isinstance(outer, list) and outer else None
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
        thread.join(60)
    alive = [t.name for t in threads if t.is_alive()]
    cuts = info_field("atomic_exec_read_cuts") - before_cuts
    ok = (not errors and not alive and state["torn"] == 0 and
          state["reads"] > 100 and state["commits"] > 10 and cuts >= state["reads"])
    note("concurrent in-EXEC MGET never straddles a transaction (atomic %d)" % mode, ok,
         "reads=%d commits=%d torn=%d exec_read_cuts=+%d errors=%r %s"
         % (state["reads"], state["commits"], state["torn"], cuts, errors[:1], samples[:1]))


for atomic_mode in (0, 1):
    note("CONFIG SET atomic %d" % atomic_mode, set_atomic(atomic_mode))
    unarmed_control(atomic_mode)
    straddle_arm(atomic_mode, "MGET")
    straddle_arm(atomic_mode, "EXISTS")
    straddle_arm(atomic_mode, "SUNION")
    bare_reference_arm(atomic_mode)
    visibility_control(atomic_mode)
    ryow_control(atomic_mode)
    scope_control(atomic_mode)
    cost_control(atomic_mode)
    stress_arm(atomic_mode)

if HAVE_DEBUG:
    arm(0)
for key in KEYS + SETS + SAME:
    ADMIN.cmd("DEL", key)
ADMIN.close()

if FAIL:
    raise SystemExit("%d in-EXEC isolation checks failed" % FAIL)
print("in-EXEC isolation battery passed", flush=True)
