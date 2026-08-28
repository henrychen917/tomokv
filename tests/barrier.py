#!/usr/bin/env python3
"""Connection parse-barrier ownership battery. Usage: tests/barrier.py HOST PORT

Required boot geometry:

  --enable-debug-command yes, at least two executors, and --shards equal to the
  executor count (with the default round-robin shard placement).

The armed probes deliberately manufacture the otherwise-unreachable overlap between
BarrierOwner::Blocking and BarrierOwner::Debug.  Each blocking command and its ECHO probe are
sent through one socket send(), so the younger frame is already in the same Client's input when
the barrier goes up.  A second connection wakes the blocking command, reads INFO, clears the
latch, and fans CLIENT LIST to every I/O thread.

The BLMOVE source/destination pair is discovered on this boot by bucketing candidate keys with
DEBUG SHARD.  No key name is assumed to imply an owner.
"""

import os
import select
import socket
import sys
import time


if len(sys.argv) != 3:
    raise SystemExit("usage: %s HOST PORT" % sys.argv[0])

HOST, PORT = sys.argv[1], int(sys.argv[2])
HOLD_WINDOW = 0.500
IO_TIMEOUT = 5.0


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


def encode(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=IO_TIMEOUT)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(IO_TIMEOUT)
        # Unbuffered is load-bearing for the silence checks: select() must describe every unread
        # reply, not miss a reply already prefetched into a Python file buffer.
        self.file = self.sock.makefile("rb", buffering=0)
        self.closed = False

    def exact(self, count):
        chunks = []
        while count:
            chunk = self.file.read(count)
            if not chunk:
                raise EOFError("server closed connection mid-reply")
            chunks.append(chunk)
            count -= len(chunk)
        return b"".join(chunks)

    def read(self):
        prefix = self.exact(1)
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError("bad RESP line %r" % (prefix + line,))
        value = line[:-2]
        if prefix == b"+":
            return value
        if prefix == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if prefix == b":":
            return int(value)
        if prefix == b"$":
            size = int(value)
            if size == -1:
                return None
            payload = self.exact(size)
            if self.exact(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return payload
        if prefix in (b"*", b"~", b">"):
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        if prefix in (b"%", b"|"):
            count = int(value)
            return {self.read(): self.read() for _ in range(count)}
        if prefix == b"_":
            if value:
                raise AssertionError("RESP3 null carried a payload: %r" % value)
            return None
        if prefix == b"#":
            return value == b"t"
        if prefix in (b",", b"("):
            return value
        raise AssertionError("unknown RESP prefix %r" % prefix)

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def send_one_write(self, blob):
        """Issue the blocking command and probe in exactly one write(2), or fail geometry."""
        sent = self.sock.send(blob)
        if sent != len(blob):
            raise AssertionError(
                "same-write pipeline geometry failed: write accepted %d of %d bytes" %
                (sent, len(blob)))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def readable(self, timeout):
        return bool(select.select([self.sock], [], [], timeout)[0])

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.file.close()
        finally:
            self.sock.close()


def want(label, actual, expected):
    if actual != expected:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, expected))


def info_fields(conn, section):
    body = conn.command("INFO", section)
    if not isinstance(body, bytes):
        raise AssertionError("INFO %s returned %r" % (section, body))
    fields = {}
    for line in body.split(b"\r\n"):
        if b":" not in line or line.startswith(b"#"):
            continue
        key, value = line.split(b":", 1)
        try:
            fields[key.decode()] = int(value)
        except ValueError:
            fields[key.decode()] = value.decode("utf-8", "replace")
    return fields


def barrier_stats(conn):
    fields = info_fields(conn, "STATS")
    required = ("barrier_owner_overlaps", "barrier_releases_held")
    missing = [name for name in required if name not in fields]
    if missing:
        raise AssertionError(
            "INFO stats omitted %s; a build without the counters cannot prove the hold fired" %
            ", ".join(missing))
    return tuple(fields[name] for name in required)


def blocked_clients(conn):
    fields = info_fields(conn, "CLIENTS")
    if "blocked_clients" not in fields:
        raise AssertionError("INFO clients omitted blocked_clients")
    return fields["blocked_clients"]


def wait_blocked(conn, minimum, timeout=2.0):
    deadline = time.monotonic() + timeout
    seen = -1
    while time.monotonic() < deadline:
        seen = blocked_clients(conn)
        if seen >= minimum:
            return
        time.sleep(0.005)
    raise AssertionError("blocking dispatch never parked: blocked_clients=%d, wanted >=%d" %
                         (seen, minimum))


def wait_counter_deltas(conn, before, minimum, timeout=1.0):
    deadline = time.monotonic() + timeout
    current = barrier_stats(conn)
    while time.monotonic() < deadline:
        if all(current[i] - before[i] >= minimum[i] for i in range(2)):
            break
        time.sleep(0.005)
        current = barrier_stats(conn)
    return current


def memory_shards(conn):
    reply = conn.command("MEMORY", "STATS")
    if isinstance(reply, dict):
        fields = reply
    elif isinstance(reply, list) and len(reply) % 2 == 0:
        fields = dict(zip(reply[0::2], reply[1::2]))
    else:
        raise AssertionError("MEMORY STATS returned %r" % (reply,))
    count = fields.get(b"shards.count", fields.get("shards.count"))
    if not isinstance(count, int):
        raise AssertionError("MEMORY STATS omitted shards.count: %r" % (reply,))
    return count


def placement(conn):
    fields = info_fields(conn, "LB")
    if "lb_io_threads" not in fields or "lb_ex_threads" not in fields:
        raise AssertionError("INFO LB omitted I/O/executor thread counts")
    return fields["lb_io_threads"], fields["lb_ex_threads"]


def shard_of(conn, key):
    shard = conn.command("DEBUG", "SHARD", key)
    if not isinstance(shard, int):
        raise AssertionError(
            "DEBUG SHARD refused (%r); boot with --enable-debug-command yes" % (shard,))
    return shard


def find_cross_owner_pair(conn, stem):
    """Walk and bucket candidates; distinct shards are owners in the required N-shard/N-EX boot."""
    by_shard = {}
    for candidate in range(4096):
        key = "%s:candidate:%04d" % (stem, candidate)
        shard = shard_of(conn, key)
        by_shard.setdefault(shard, key)
        if len(by_shard) >= 2:
            first, second = sorted(by_shard)[:2]
            return by_shard[first], by_shard[second], first, second
    raise AssertionError(
        "DEBUG SHARD found fewer than two distinct owners after 4096 candidates; observed=%r" %
        sorted(by_shard))


def preflight(conn, stem):
    want("DEBUG BARRIER-HOLD 0", conn.command("DEBUG", "BARRIER-HOLD", "0"), b"OK")
    barrier_stats(conn)
    io_threads, ex_threads = placement(conn)
    shard_count = memory_shards(conn)
    if ex_threads < 2:
        raise AssertionError("geometry requires at least 2 executors; INFO LB reports %d" %
                             ex_threads)
    if shard_count != ex_threads:
        raise AssertionError(
            "geometry requires --shards == executor count; MEMORY STATS/INFO LB report %d/%d" %
            (shard_count, ex_threads))
    source, destination, source_shard, destination_shard = find_cross_owner_pair(conn, stem)
    if source_shard == destination_shard:
        raise AssertionError("cross-owner BLMOVE geometry collapsed onto shard %d" % source_shard)
    return {
        "io_threads": io_threads,
        "ex_threads": ex_threads,
        "shards": shard_count,
        "source": source,
        "destination": destination,
        "source_shard": source_shard,
        "destination_shard": destination_shard,
    }


def blocking_probe(admin, geometry, kind, armed, stem, retain, held, keys_used):
    """Run one Blocking+probe script. Returns the exact replies and whether the probe escaped."""
    blocker = Conn()
    record = {
        "kind": kind,
        "conn": blocker,
        "probe": ("%s:%s:probe" % (stem, kind)).encode(),
        "probe_seen": None,
        "probe_reply": None,
    }
    if retain:
        held.append(record)
    try:
        want("%s DEBUG BARRIER-HOLD" % kind,
             blocker.command("DEBUG", "BARRIER-HOLD", "1" if armed else "0"), b"OK")
        base_blocked = blocked_clients(admin)
        value = ("%s:%s:value" % (stem, kind)).encode()
        if kind == "BLPOP":
            key = "%s:blpop:key" % stem
            keys_used.add(key)
            want("BLPOP cleanup", admin.command("DEL", key), 0)
            command = ("BLPOP", key, "0")
            expected = [key.encode(), value]
            wake = ("RPUSH", key, value)
        elif kind == "BLMOVE":
            source, destination = geometry["source"], geometry["destination"]
            keys_used.update((source, destination))
            admin.command("DEL", source, destination)
            command = ("BLMOVE", source, destination, "RIGHT", "LEFT", "0")
            expected = value
            wake = ("RPUSH", source, value)
        else:
            raise AssertionError("unknown blocking probe %s" % kind)

        # ONE syscall carries both frames. A second send would add a race and weaken the test.
        blocker.send_one_write(encode(*command) + encode("ECHO", record["probe"]))
        wait_blocked(admin, base_blocked + 1)
        want("%s wake" % kind, admin.command(*wake), 1)
        want("%s blocking reply" % kind, blocker.read(), expected)
        record["probe_seen"] = blocker.readable(HOLD_WINDOW)
        if record["probe_seen"]:
            record["probe_reply"] = blocker.read()
        return record
    finally:
        if not retain:
            blocker.close()


def run_negative(admin, geometry, stem, held, keys_used):
    want("negative latch clear", admin.command("DEBUG", "BARRIER-HOLD", "0"), b"OK")
    before = barrier_stats(admin)
    errors = []
    fired = 0
    for kind in ("BLPOP", "BLMOVE"):
        try:
            record = blocking_probe(admin, geometry, kind, False, stem + ":negative",
                                    False, held, keys_used)
            fired += 1
            if not record["probe_seen"]:
                errors.append("%s probe did not pass with the latch off" % kind)
            elif record["probe_reply"] != record["probe"]:
                errors.append("%s probe replied %r, wanted %r" %
                              (kind, record["probe_reply"], record["probe"]))
        except Exception as exc:  # surfaced in this cell's single result line
            errors.append("%s: %s" % (kind, exc))
    after = barrier_stats(admin)
    delta = (after[0] - before[0], after[1] - before[1])
    if delta != (0, 0):
        errors.append("latch-off counters moved: overlaps %+d, releases-held %+d" % delta)
    if fired != 2:
        errors.append("identical-script control fired %d/2 blocking arms" % fired)
    if errors:
        raise AssertionError("; ".join(errors))
    return "BLPOP+cross-owner BLMOVE probes passed; counters +0/+0"


def run_armed(admin, geometry, stem, held, keys_used):
    before = barrier_stats(admin)
    errors = []
    fired = 0
    for kind in ("BLPOP", "BLMOVE"):
        try:
            record = blocking_probe(admin, geometry, kind, True, stem + ":armed",
                                    True, held, keys_used)
            fired += 1
            if record["probe_seen"]:
                errors.append("%s probe escaped while the latch was armed: %r" %
                              (kind, record["probe_reply"]))
        except Exception as exc:  # keep the other arm and the counter oracle alive
            errors.append("%s: %s" % (kind, exc))

    after = wait_counter_deltas(admin, before, (2, 2))
    delta = (after[0] - before[0], after[1] - before[1])
    if delta[1] == 0:
        errors.append("geometry never constructed: barrier_releases_held did not move")
    elif delta[1] != 2:
        errors.append("barrier_releases_held moved %+d, wanted exactly +2" % delta[1])
    if delta[0] != 2:
        errors.append("barrier_owner_overlaps moved %+d, wanted exactly +2" % delta[0])
    if fired != 2:
        errors.append("armed scripts reached %d/2 blocking retirements" % fired)
    if errors:
        raise AssertionError("; ".join(errors))
    return ("2/2 probes held; overlaps +2; releases-held +2; BLMOVE shards %d->%d" %
            (geometry["source_shard"], geometry["destination_shard"]))


def run_resume(admin, held):
    errors = []
    try:
        want("resume latch clear", admin.command("DEBUG", "BARRIER-HOLD", "0"), b"OK")
        listing = admin.command("CLIENT", "LIST")
        if not isinstance(listing, bytes):
            errors.append("CLIENT LIST wake returned %r" % (listing,))

        for record in held:
            if record["probe_seen"] is True:
                errors.append("%s probe had already escaped before latch clear" % record["kind"])
                continue
            if record["probe_seen"] is None:
                errors.append("%s armed script never reached its silence check" % record["kind"])
                continue
            if not record["conn"].readable(3.0):
                errors.append("%s probe did not resume after latch clear + CLIENT LIST" %
                              record["kind"])
                continue
            reply = record["conn"].read()
            if reply != record["probe"]:
                errors.append("%s resumed with %r, wanted %r" %
                              (record["kind"], reply, record["probe"]))
    finally:
        for record in held:
            record["conn"].close()
    if len(held) != 2:
        errors.append("resume saw %d/2 armed connections" % len(held))
    if errors:
        raise AssertionError("; ".join(errors))
    return "2/2 held probes resumed after latch clear + CLIENT LIST wake"


def run_production(admin, geometry, stem, held, keys_used):
    want("production latch clear", admin.command("DEBUG", "BARRIER-HOLD", "0"), b"OK")
    before = barrier_stats(admin)
    errors = []
    ordinary = waiter = subscriber = None
    try:
        ordinary, waiter, subscriber = Conn(), Conn(), Conn()
        source, destination = geometry["source"], geometry["destination"]
        keys_used.update((source, destination))

        # Scatter owner: a proven cross-owner two-hop destination write.
        ordinary.command("DEL", source, destination)
        want("production LMOVE setup", ordinary.command("RPUSH", source, "scatter"), 1)
        want("production cross-owner LMOVE",
             ordinary.command("LMOVE", source, destination, "RIGHT", "LEFT"), b"scatter")

        # Blocking owner: ordinary latch-off retirement with a younger same-write probe.
        record = blocking_probe(admin, geometry, "BLPOP", False, stem + ":production",
                                False, held, keys_used)
        if not record["probe_seen"] or record["probe_reply"] != record["probe"]:
            errors.append("production BLPOP probe did not retire normally")

        # Deferred WAIT owner: an unattainable replica count makes the standalone boot park until
        # its deadline. The blocked gauge proves this did not collapse into the immediate arm.
        base_blocked = blocked_clients(admin)
        waiter.send("WAIT", "1000000", "500")
        wait_blocked(admin, base_blocked + 1)
        wait_reply = waiter.read()
        if not isinstance(wait_reply, int):
            errors.append("deferred WAIT returned %r" % (wait_reply,))

        # EXEC owner: two keys on different owners force the fan-out parent path.
        ordinary.command("DEL", source, destination)
        want("production MULTI", ordinary.command("MULTI"), b"OK")
        want("production EXEC source queue", ordinary.command("SET", source, "exec-a"), b"QUEUED")
        want("production EXEC destination queue",
             ordinary.command("SET", destination, "exec-b"), b"QUEUED")
        want("production EXEC", ordinary.command("EXEC"), [b"OK", b"OK"])

        # Pub/sub transition owner, then the CLIENT fan-out owner that also supplies the resume
        # event in cell 3.
        channel = (stem + ":production:channel").encode()
        want("production SUBSCRIBE", subscriber.command("SUBSCRIBE", channel),
             [b"subscribe", channel, 1])
        want("production UNSUBSCRIBE", subscriber.command("UNSUBSCRIBE", channel),
             [b"unsubscribe", channel, 0])
        listing = admin.command("CLIENT", "LIST")
        if not isinstance(listing, bytes):
            errors.append("production CLIENT LIST returned %r" % (listing,))
    except Exception as exc:
        errors.append(str(exc))
    finally:
        for conn in (ordinary, waiter, subscriber):
            if conn is not None:
                conn.close()

    after = barrier_stats(admin)
    delta = (after[0] - before[0], after[1] - before[1])
    if delta[0] != 0:
        errors.append("ordinary traffic created %+d barrier owner overlaps (wanted 0)" % delta[0])
    if delta[1] != 0:
        errors.append("ordinary traffic created %+d held releases (wanted 0)" % delta[1])
    if errors:
        raise AssertionError("; ".join(errors))
    return ("six production owner classes; overlaps +0, releases-held +0 "
            "(cumulative overlaps=%d)" % after[0])


CELL_ORDER = ("armed", "negative control", "resume", "production overlap")


def run_cell(results, name, function):
    try:
        results[name] = (True, function())
    except Exception as exc:
        results[name] = (False, str(exc))


def main():
    stem = "barrier:%d:%d" % (os.getpid(), time.time_ns())
    results = {}
    held = []
    keys_used = set()
    admin = None
    geometry = None
    preflight_error = None

    try:
        try:
            admin = Conn()
            geometry = preflight(admin, stem)
        except Exception as exc:
            preflight_error = str(exc)

        if preflight_error is not None:
            for name in CELL_ORDER:
                results[name] = (False, "preflight failed: " + preflight_error)
        else:
            # The latch is process-global. Run the negative script first so clearing it cannot
            # accidentally release the armed connections before the explicit resume cell.
            run_cell(results, "negative control",
                     lambda: run_negative(admin, geometry, stem, held, keys_used))
            run_cell(results, "armed",
                     lambda: run_armed(admin, geometry, stem, held, keys_used))
            run_cell(results, "resume", lambda: run_resume(admin, held))
            run_cell(results, "production overlap",
                     lambda: run_production(admin, geometry, stem, held, keys_used))
    finally:
        # Never strand a process-global debug latch or an owned connection, even on a failing
        # positive-control build. CLIENT LIST is the cross-I/O wake required by the latch design.
        recovered = False
        if admin is not None and not admin.closed:
            try:
                admin.command("DEBUG", "BARRIER-HOLD", "0")
                admin.command("CLIENT", "LIST")
                if keys_used:
                    admin.command("DEL", *sorted(keys_used))
                recovered = True
            except Exception:
                pass
        if not recovered:
            recovery = None
            try:
                recovery = Conn()
                recovery.command("DEBUG", "BARRIER-HOLD", "0")
                recovery.command("CLIENT", "LIST")
                if keys_used:
                    recovery.command("DEL", *sorted(keys_used))
            except Exception:
                pass
            finally:
                if recovery is not None:
                    recovery.close()
        for record in held:
            record["conn"].close()
        if admin is not None:
            admin.close()

    passed = 0
    for name in CELL_ORDER:
        ok, detail = results.get(name, (False, "cell did not run"))
        passed += int(ok)
        print("  %-4s %-20s %s" % ("ok" if ok else "FAIL", name, detail), flush=True)
    failed = len(CELL_ORDER) - passed
    print("barrier: %d ok, %d FAIL" % (passed, failed), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
