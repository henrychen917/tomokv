#!/usr/bin/env python3
"""SCAN-family completeness under a table resize. Usage: tests/concur.py HOST PORT

THE CONTRACT UNDER TEST (Redis's, and ours -- see scan_cursor_next in src/store/flatstore.h):
an element that is present for the WHOLE of a completed iteration is returned at least once, no
matter how many times the table was rebuilt underneath the cursor. Elements added or removed
during the iteration have Redis's usual unspecified visibility, and duplicates are allowed. Only
OMISSION of a continuously-present element is a defect.

The defect this guards: a cursor that is a raw physical slot index. Doubling the table moves a key
from a slot AHEAD of the cursor to one BEHIND it and the key is never emitted, even though nothing
ever deleted it.

Every arm names both quantities it compares (live vs seen) and every arm has a control that must
read ZERO:
  - CHURN arms mutate an UNRELATED key/member set while a base set is walked. Base is never
    touched, so missed==0 is required, and INFO keyspace_rehashes / the collection cardinality
    must MOVE, or the arm proved nothing (see the FIRED assertions).
  - QUIET arms run the identical walk with no mutation at all. They must read zero rehashes and
    zero misses -- that is the proof the detector is capable of reporting zero, which is what
    makes a non-zero reading in a CHURN arm mean something.
  - SSCAN and HSCAN are structurally immune by different mechanisms (generation-restart cursor /
    bit-reversed home cursor) and are carried here as always-zero rows: if they ever go non-zero
    the harness, not the fix, is what changed.
"""

import socket
import sys
import threading
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
# `oracle` runs the identical detector against vanilla Redis, which has no keyspace_rehashes
# counter. That is the THIRD control: the same arms must read zero against the server whose
# semantics we are copying. It is opt-in precisely so a tomokv run can never silently skip the
# FIRED assertions and pass vacuously.
ORACLE = "oracle" in sys.argv[3:]

FAILURES = []
PASSES = 0


def encode(args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.extend((b"$%d\r\n" % len(arg), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=60)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("connection closed")
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body
        if kind == b"-":
            raise RuntimeError(body.decode())
        if kind == b":":
            return int(body)
        if kind == b"$":
            n = int(body)
            return None if n == -1 else self.file.read(n + 2)[:-2]
        if kind == b"*":
            n = int(body)
            return None if n == -1 else [self.read() for _ in range(n)]
        raise RuntimeError("unexpected reply type %r" % line)

    def cmd(self, *args):
        self.sock.sendall(encode(list(args)))
        return self.read()

    def pipe(self, commands, chunk=2000):
        out = []
        for i in range(0, len(commands), chunk):
            part = commands[i:i + chunk]
            self.sock.sendall(b"".join(encode(c) for c in part))
            out.extend(self.read() for _ in part)
        return out

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def report(name, ok, detail):
    global PASSES
    if ok:
        PASSES += 1
        print("  ok   %-34s %s" % (name, detail))
    else:
        FAILURES.append(name)
        print("  FAIL %-34s %s" % (name, detail))


def info_stat(conn, field):
    body = conn.cmd("INFO", "stats")
    if isinstance(body, bytes):
        for line in body.split(b"\r\n"):
            if line.startswith(field.encode() + b":"):
                return int(line.split(b":", 1)[1])
    if ORACLE:
        return None
    raise RuntimeError("INFO stats has no %s (a build without the counter cannot prove the "
                       "resize fired, so this test refuses to pass vacuously)" % field)


def rehash_delta(after, before):
    return None if after is None or before is None else after - before


def walk_scan(conn, first_args, count, between=None):
    """Walk a cursor to completion. `between` runs after each call and can mutate the server.

    The cursor is always the last positional argument: `SCAN cur`, `ZSCAN key cur`.
    """
    cursor, seen, calls = b"0", [], 0
    while True:
        reply = conn.cmd(*(first_args + [cursor, "COUNT", str(count)]))
        calls += 1
        cursor = reply[0]
        seen.append(reply[1])
        if between:
            between(calls)
        if cursor == b"0":
            break
        if calls > 400000:
            raise RuntimeError("cursor never returned to 0 after %d calls" % calls)
    return seen, calls


# --------------------------------------------------------------------------------------------
# ARM 1: keyspace SCAN, concurrent churn of unrelated keys (the shape a real client hits).
# --------------------------------------------------------------------------------------------
def arm_scan_concurrent(label, churn, trials=2, base=500):
    total_missed, fired = 0, 0
    for trial in range(trials):
        walker, mutator = Conn(), Conn()
        walker.cmd("FLUSHALL")
        walker.pipe([["SET", "base:%05d" % i, "1"] for i in range(base)])
        before = info_stat(walker, "keyspace_rehashes")
        stop = threading.Event()
        errors = []

        # Bounded, for the same reason as the collection arm: a mutator that outruns the walker
        # forever turns a measurement into a hang.
        def run_churn():
            try:
                n = 0
                for _ in range(40 if churn else 0):
                    if stop.is_set():
                        return
                    mutator.pipe([["SET", "churn:%06d" % (n + j), "1"] for j in range(500)])
                    n += 500
                    if n % 5000 == 0:
                        mutator.pipe([["DEL", "churn:%06d" % j] for j in range(n - 5000, n)])
                    time.sleep(0.001)
                while not stop.is_set():
                    mutator.cmd("PING")              # CONTROL arm does only this
                    time.sleep(0.001)
            except Exception as exc:                 # noqa: BLE001 - reported, not swallowed
                errors.append(exc)

        thread = threading.Thread(target=run_churn)
        thread.start()
        time.sleep(0.05)
        try:
            batches, calls = walk_scan(walker, ["SCAN"], 20)
        finally:
            stop.set()
            thread.join()
        seen = set(k.decode() for batch in batches for k in batch if k.startswith(b"base:"))
        live = set(k.decode() for k in walker.cmd("KEYS", "base:*"))
        rehashes = rehash_delta(info_stat(walker, "keyspace_rehashes"), before)
        fired += rehashes or 0
        if len(live) != base:
            report("%s trial%d precondition" % (label, trial), False,
                   "base set was disturbed: %d of %d live" % (len(live), base))
        missed = sorted(live - seen)
        total_missed += len(missed)
        detail = ("calls=%d rehashes_during_walk=%s base_live=%d base_seen=%d MISSED=%d %s"
                  % (calls, rehashes, len(live), len(seen), len(missed), missed[:4]))
        if missed:
            key = missed[0]
            detail += " | EXISTS %s -> %r (never deleted)" % (key, walker.cmd("EXISTS", key))
        if errors:
            detail += " | churn errors: %r" % errors
        report("%s trial%d" % (label, trial), not missed and not errors, detail)
        walker.cmd("FLUSHALL")
        walker.close()
        mutator.close()
    return total_missed, fired


# --------------------------------------------------------------------------------------------
# ARM 2: keyspace SCAN, DETERMINISTIC single connection. No threads, no timing: the walk is
# suspended at a known point, the resize is forced, and the walk is resumed.
# --------------------------------------------------------------------------------------------
def arm_scan_deterministic(label, pad, base=2000, per_burst=1000, every=4, max_bursts=120):
    conn = Conn()
    conn.cmd("FLUSHALL")
    conn.pipe([["SET", "base:%05d" % i, "1"] for i in range(base)])
    before = info_stat(conn, "keyspace_rehashes")

    # SUSTAINED churn across the WHOLE walk, in modest bursts, from the walking connection itself:
    # no threads, no sleeps, one deterministic command order. Sustained matters. A single burst big
    # enough to double the table also drains the entire incremental rehash before the walk resumes,
    # and a fully-drained doubling happens to be survivable even by a physical-slot cursor, because
    # doubling preserves a home's low bits. What a physical cursor cannot survive is a rehash still
    # IN FLIGHT while the cursor advances, which is the ordinary state of a busy server. Each burst
    # adds a pad block and drops the block added two bursts ago, so the key count stays bounded and
    # the walk terminates, while the table keeps growing and reclaiming underneath the cursor.
    state = {"fired": 0}

    def between(calls):
        if calls % every or state["fired"] >= max_bursts:
            return
        index = state["fired"]
        state["fired"] += 1
        if not pad:
            conn.pipe([["PING"]] * 64)               # CONTROL: same shape, no geometry change
            return
        block = [["SET", "pad:%d:%05d" % (index, i), "1"] for i in range(per_burst)]
        if index >= 2:
            block += [["DEL", "pad:%d:%05d" % (index - 2, i)] for i in range(per_burst)]
        conn.pipe(block)

    batches, calls = walk_scan(conn, ["SCAN"], 50, between=between)
    seen = set(k.decode() for batch in batches for k in batch if k.startswith(b"base:"))
    live = set(k.decode() for k in conn.cmd("KEYS", "base:*"))
    rehashes = rehash_delta(info_stat(conn, "keyspace_rehashes"), before)
    ok = True
    if len(live) != base:
        report("%s precondition" % label, False, "base disturbed: %d of %d" % (len(live), base))
        ok = False
    if pad and rehashes == 0:
        report("%s FIRED" % label, False,
               "no table rebuild happened during the walk; the arm proves nothing")
        ok = False
    if not pad and rehashes:
        report("%s FIRED" % label, False,
               "control arm rebuilt the table %d times; it is not a control" % rehashes)
        ok = False
    missed = sorted(live - seen)
    detail = ("calls=%d rehashes_during_walk=%s base_live=%d base_seen=%d MISSED=%d %s"
              % (calls, rehashes, len(live), len(seen), len(missed), missed[:4]))
    if missed:
        detail += " | EXISTS %s -> %r (never deleted)" % (missed[0], conn.cmd("EXISTS", missed[0]))
    report(label, ok and not missed, detail)
    conn.cmd("FLUSHALL")
    conn.close()
    return len(missed), rehashes


# --------------------------------------------------------------------------------------------
# ARM 3: collection scans. ZSCAN shares the keyspace defect; SSCAN and HSCAN are immune by
# construction and are carried as always-zero rows.
# --------------------------------------------------------------------------------------------
SPECS = {
    "SSCAN": ("cs:set", lambda m: ["SADD", "cs:set", m], "SCARD", "SISMEMBER", 1),
    "HSCAN": ("cs:hash", lambda m: ["HSET", "cs:hash", m, "v"], "HLEN", "HEXISTS", 2),
    "ZSCAN": ("cs:zset", lambda m: ["ZADD", "cs:zset", "1", m], "ZCARD", "ZSCORE", 2),
}
SPEC_REMOVE = {
    "SSCAN": lambda m: ["SREM", "cs:set", m],
    "HSCAN": lambda m: ["HDEL", "cs:hash", m],
    "ZSCAN": lambda m: ["ZREM", "cs:zset", m],
}


def arm_collection_deterministic(scanner, label, pad, base=4000, per_burst=200, every=1,
                                 max_bursts=500, start_fraction=0.5):
    key, add, card_cmd, probe, step = SPECS[scanner]
    remove = SPEC_REMOVE[scanner]
    conn = Conn()
    conn.cmd("DEL", key)
    conn.pipe([add("base:%05d" % i) for i in range(base)])
    card_before = conn.cmd(card_cmd, key)
    peak = [card_before]

    # A QUIET dry run first. It measures how many calls the walk takes, and it is itself a control
    # that must miss nothing. The churned walk then starts its bursts near the END of that count,
    # which is where a physical-position cursor is most exposed: everything not yet migrated is
    # ahead of the cursor, and a rehash that starts there drops roughly the fraction of the table
    # the cursor has already passed. Bursts are BOUNDED because SSCAN's cursor restarts at slot
    # zero on every rebuild, so churn that never stops would keep restarting it forever.
    quiet_batches, quiet_calls = walk_scan(conn, [scanner, key], 50)
    quiet_seen = set()
    for batch in quiet_batches:
        for i in range(0, len(batch), step):
            if batch[i].startswith(b"base:"):
                quiet_seen.add(batch[i].decode())
    report("%s dry run (CONTROL)" % label, len(quiet_seen) == base,
           "calls=%d base_seen=%d of %d, no mutation at all" % (quiet_calls, len(quiet_seen), base))

    first_burst = max(2, int(quiet_calls * start_fraction))
    state = {"fired": 0}

    def between(calls):
        if calls < first_burst or calls % every or state["fired"] >= max_bursts:
            return
        index = state["fired"]
        state["fired"] += 1
        if not pad:
            conn.pipe([["PING"]] * 64)
            return
        block = [add("pad:%d:%05d" % (index, i)) for i in range(per_burst)]
        if index >= 2:
            block += [remove("pad:%d:%05d" % (index - 2, i)) for i in range(per_burst)]
        conn.pipe(block)
        peak.append(conn.cmd(card_cmd, key))

    batches, calls = walk_scan(conn, [scanner, key], 50, between=between)
    seen = set()
    for batch in batches:
        for i in range(0, len(batch), step):
            if batch[i].startswith(b"base:"):
                seen.add(batch[i].decode())
    members = ["base:%05d" % i for i in range(base)]
    present = conn.pipe([[probe, key, m] for m in members])
    live = set(m for m, v in zip(members, present) if v not in (0, None))
    card_after = conn.cmd(card_cmd, key)
    card_peak = max(peak)
    ok = True
    if len(live) != base:
        report("%s precondition" % label, False, "base disturbed: %d of %d" % (len(live), base))
        ok = False
    if pad and card_peak <= card_before:
        report("%s FIRED" % label, False,
               "cardinality never grew past %d: no rebuild, the arm proves nothing" % card_before)
        ok = False
    if not pad and card_peak != card_before:
        report("%s FIRED" % label, False, "control arm mutated the collection")
        ok = False
    missed = sorted(live - seen)
    detail = ("calls=%d card=%d->peak %d->%d base_live=%d base_seen=%d MISSED=%d %s"
              % (calls, card_before, card_peak, card_after, len(live), len(seen),
                 len(missed), missed[:4]))
    if missed:
        detail += " | %s %s -> %r (never removed)" % (probe, missed[0],
                                                      conn.cmd(probe, key, missed[0]))
    report(label, ok and not missed, detail)
    conn.cmd("DEL", key)
    conn.close()
    return len(missed)


def arm_collection_concurrent(scanner, label, base=3000, add_batch=2000, rounds=80):
    key, add, card_cmd, probe, step = SPECS[scanner]
    remove = SPEC_REMOVE[scanner]
    walker, mutator = Conn(), Conn()
    walker.cmd("DEL", key)
    walker.pipe([add("base:%05d" % i) for i in range(base)])
    card_before = walker.cmd(card_cmd, key)
    stop = threading.Event()
    errors = []
    grew = [card_before]

    # Churn is BOUNDED: unbounded growth would outrun any walker and the arm would hang instead of
    # measuring anything. Within the bound it is allowed to GROW several table generations before
    # dropping back, because one rebuild that completes between two calls is much less hostile to a
    # cursor than a rebuild that is still draining while the cursor moves. After `rounds` the
    # mutator idles so the walk can end; the peak cardinality is the FIRED evidence.
    def run_churn():
        try:
            n, dropped = 0, 0
            for round_index in range(rounds):
                if stop.is_set():
                    break
                mutator.pipe([add("churn:%06d" % (n + j)) for j in range(add_batch)])
                n += add_batch
                grew.append(mutator.cmd(card_cmd, key))
                if round_index % 10 == 9:
                    mutator.pipe([remove("churn:%06d" % j) for j in range(dropped, n)])
                    dropped = n
                time.sleep(0.001)
            while not stop.is_set():
                mutator.cmd("PING")
                time.sleep(0.001)
        except Exception as exc:                     # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run_churn)
    thread.start()
    time.sleep(0.05)
    try:
        batches, calls = walk_scan(walker, [scanner, key], 20)
    finally:
        stop.set()
        thread.join()
    seen = set()
    for batch in batches:
        for i in range(0, len(batch), step):
            if batch[i].startswith(b"base:"):
                seen.add(batch[i].decode())
    members = ["base:%05d" % i for i in range(base)]
    present = walker.pipe([[probe, key, m] for m in members])
    live = set(m for m, v in zip(members, present) if v not in (0, None))
    card_after = walker.cmd(card_cmd, key)
    card_peak = max(grew)
    ok = True
    if len(live) != base:
        report("%s precondition" % label, False, "base disturbed: %d of %d" % (len(live), base))
        ok = False
    if card_peak <= card_before:
        report("%s FIRED" % label, False, "collection never grew during the walk")
        ok = False
    missed = sorted(live - seen)
    detail = ("calls=%d card=%d->peak %d->%d base_live=%d base_seen=%d MISSED=%d %s"
              % (calls, card_before, card_peak, card_after, len(live), len(seen),
                 len(missed), missed[:4]))
    if missed:
        detail += " | %s %s -> %r (never removed)" % (probe, missed[0],
                                                      walker.cmd(probe, key, missed[0]))
    if errors:
        detail += " | churn errors: %r" % errors
    report(label, ok and not missed and not errors, detail)
    walker.cmd("DEL", key)
    walker.close()
    mutator.close()
    return len(missed)


def main():
    print("SCAN-family completeness under resize (%s:%d)" % (HOST, PORT))

    print(" -- deterministic single-connection arms (no threads, no timing) --")
    arm_scan_deterministic("SCAN churn   (deterministic)", pad=True)
    arm_scan_deterministic("SCAN quiet   (CONTROL)", pad=False)
    for scanner in ("ZSCAN", "SSCAN", "HSCAN"):
        arm_collection_deterministic(scanner, "%s churn   (deterministic)" % scanner, pad=True)
    arm_collection_deterministic("ZSCAN", "ZSCAN quiet   (CONTROL)", pad=False)

    print(" -- concurrent arms (second connection churns an unrelated set) --")
    missed, fired = arm_scan_concurrent("SCAN churn  ", churn=True)
    if fired == 0 and not ORACLE:
        report("SCAN churn FIRED", False,
               "no table rebuild during any walk; the concurrent arm proves nothing")
    quiet_missed, quiet_fired = arm_scan_concurrent("SCAN quiet  (CONTROL)", churn=False, trials=1)
    if quiet_fired:
        report("SCAN quiet FIRED", False,
               "control arm rebuilt the table %d times; it is not a control" % quiet_fired)
    for scanner in ("ZSCAN", "SSCAN", "HSCAN"):
        arm_collection_concurrent(scanner, "%s churn  " % scanner)

    print("")
    if FAILURES:
        print("CONCUR: %d passed, %d FAILED -> %s" % (PASSES, len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("CONCUR: %d checks passed, 0 failed" % PASSES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
