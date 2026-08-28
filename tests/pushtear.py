#!/usr/bin/env python3
"""Out-of-band frame vs. zero-copy (borrowed) reply battery.

Usage: pushtear.py HOST PORT [--tls CERTDIR --tls-port N] [--iters N]

WHAT THIS COVERS THAT NOTHING ELSE DID
--------------------------------------
An out-of-band frame -- a pub/sub delivery, a CLIENT TRACKING invalidation or a
MONITOR feed line -- used to be parked on the newest live op's `reply`. That is
the reply's TAIL when it is copied and its HEAD when it is BORROWED (serve emits
[direct+reply][borrow][CRLF], and a borrowed GET writes only "$<len>\\r\\n" into
the sink), so the frame landed between a bulk header and its zero-copy body and
desynchronised the connection by exactly the frame length. Silently.

The discriminating geometry is a CROSS that no existing battery makes:

    value size >= zc-min   (below it the reply is COPIED and the old parking was
                            correct -- zc.py uses 2MB values but emits no pushes,
                            pubsub.py/tracking.py emit pushes but use 5-byte
                            values, so the cell was never entered)
  x ROB state              (quiesced = safe, what every existing test hits;
                            Done-but-unretired = the deterministic tear;
                            Issued = the racy heap-corruption variant)
  x producer               (pub/sub, tracking invalidation, MONITOR)
  x protocol               (RESP3 for pub/sub and tracking pushes; RESP3 AND RESP2
                            for protocol-agnostic MONITOR delivery)

EVERY CELL PROVES ITS OWN GEOMETRY
----------------------------------
"No tear" is worthless unless the run actually reached the non-quiesced state.
The server exports two proof-of-mechanism counters in INFO:

    oob_frames_segmented   a frame appended while the ROB was NOT quiesced
    oob_frames_deferred    a frame raised from INSIDE a retire drain

A cell that finishes clean but moved neither counter FAILS with
"geometry never constructed" rather than passing quietly. Sections that need a
borrow additionally require zc_sends to move.

THE ORACLE IS THE BYTES, NOT THE FRAME COUNT
--------------------------------------------
Every check re-parses the whole received stream with a strict incremental RESP
reader that refuses malformed input and refuses leftover bytes, then compares
the bulk body byte-for-byte against what was written. A splice fails all three
ways at once (wrong body, bad terminator, trailing garbage), so no cell can
false-pass by looking only for "did a push arrive".

REJECTED RECIPE, recorded so it is not retried: a blocking command cannot be the
head-holder. BLPOP sets scatter_barrier and the parse loop refuses to parse
behind a barrier, so nothing can be pipelined behind a blocked op. PUBLISH works
instead: pubsub_start_publish takes no barrier and deliveries run strictly before
publish results.
"""

import os
import socket
import ssl
import sys
import time

HOST = "127.0.0.1"
PORT = 0
TLS_DIR = None
TLS_PORT = 0
ITERS = 40

PASS = 0
FAIL = 0
CELLS = []          # (name, verdict, detail) -- printed as a cell MAP, never an aggregate


def ok(name, detail=""):
    global PASS
    PASS += 1
    CELLS.append((name, "ok", detail))


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    CELLS.append((name, "FAIL", detail))


class Malformed(Exception):
    pass


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.append(b"$%d\r\n" % len(arg))
        out.append(arg)
        out.append(b"\r\n")
    return b"".join(out)


# ---- a strict incremental RESP2/RESP3 reader -------------------------------------------------
# Strict on purpose: it is the tear detector. A frame spliced into a bulk body makes the body
# wrong, makes the two bytes after it not CRLF, and leaves the value's tail in the stream as
# garbage. Any one of those raises here.

def _line(buf, i):
    end = buf.find(b"\r\n", i)
    if end < 0:
        raise Malformed("unterminated line at %d: %r" % (i, buf[i:i + 40]))
    return buf[i:end], end + 2


def parse_one(buf, i):
    """Returns (kind, value, next_index). value is bytes for scalars, list for aggregates."""
    if i >= len(buf):
        raise Malformed("truncated frame")
    kind = buf[i:i + 1]
    if kind in (b"+", b"-", b":", b",", b"#", b"(", b"="):
        body, j = _line(buf, i + 1)
        return kind, body, j
    if kind == b"_":
        body, j = _line(buf, i + 1)
        if body:
            raise Malformed("RESP3 null carries a payload: %r" % body)
        return kind, None, j
    if kind == b"$":
        head, j = _line(buf, i + 1)
        n = int(head)
        if n < 0:
            return kind, None, j
        body = buf[j:j + n]
        if len(body) != n:
            raise Malformed("bulk short by %d bytes" % (n - len(body)))
        if buf[j + n:j + n + 2] != b"\r\n":
            raise Malformed("bulk of %d not CRLF-terminated: %r"
                            % (n, buf[j + n:j + n + 12]))
        return kind, body, j + n + 2
    if kind in (b"*", b">", b"~", b"%"):
        head, j = _line(buf, i + 1)
        n = int(head)
        if n < 0:
            return kind, None, j
        if kind == b"%":
            n *= 2
        items = []
        for _ in range(n):
            k, v, j = parse_one(buf, j)
            items.append((k, v))
        return kind, items, j
    raise Malformed("unknown type byte %r at %d (context %r)"
                    % (kind, i, buf[max(0, i - 24):i + 24]))


def parse_all(buf):
    """Every top-level frame, or an exception. Leftover bytes are a failure, not a remainder:
    this battery always reads to a quiescent point before parsing."""
    out = []
    i = 0
    while i < len(buf):
        kind, value, i = parse_one(buf, i)
        out.append((kind, value))
    return out


class Conn:
    def __init__(self, tls=False, timeout=10):
        port = TLS_PORT if tls else PORT
        raw = socket.create_connection((HOST, port), timeout=timeout)
        if tls:
            ctx = ssl.create_default_context(cafile=os.path.join(TLS_DIR, "ca.crt"))
            ctx.check_hostname = False
            raw = ctx.wrap_socket(raw)
        self.sock = raw
        self.sock.settimeout(timeout)
        self.buf = b""

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def send_raw(self, blob):
        """ONE write. Pipelining in a single sendall is what puts two commands in one parse
        pass, which is how the head-holder geometries are constructed."""
        self.sock.sendall(blob)

    def drain(self, wait=0.5, expect=0, contains=None):
        """Read until the stream parses cleanly into at least `expect` top-level frames, or until
        `wait` elapses. Returns raw bytes -- the parsing is the caller's, because the raw stream is
        the evidence and a TORN stream must reach the oracle unmodified.

        `expect` is a fast path, not a check: a clean run stops in microseconds while a torn one
        never parses and therefore waits the whole window before failing. So a passing run is
        quick and a failing one still shows every byte the server sent."""
        deadline = time.time() + wait
        out = b""
        while True:
            if out and (expect or contains):
                try:
                    enough = len(parse_all(out)) >= expect
                    if enough and (contains is None or contains in out):
                        break
                except Malformed:
                    pass
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(1 << 20)
            except (socket.timeout, ssl.SSLWantReadError):
                break
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        self.sock.settimeout(10)
        return out

    def command(self, *args, wait=0.5, expect=1, contains=None):
        self.send(*args)
        return self.drain(wait, expect, contains)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def admin_info():
    c = Conn()
    raw = c.command("INFO", "everything", wait=0.8)
    c.close()
    stats = {}
    for line in raw.split(b"\r\n"):
        if b":" not in line or line.startswith(b"#") or line.startswith(b"$"):
            continue
        k, _, v = line.partition(b":")
        try:
            stats[k.decode()] = int(v)
        except ValueError:
            stats[k.decode()] = v.decode(errors="replace")
    return stats


def config_get(name):
    c = Conn()
    raw = c.command("CONFIG", "GET", name, wait=0.6)
    c.close()
    frames = parse_all(raw)
    if not frames:
        raise Malformed("CONFIG GET %s returned nothing" % name)
    kind, items = frames[0]
    if kind not in (b"*", b"%") or not items or len(items) < 2:
        raise Malformed("CONFIG GET %s unsupported: %r" % (name, frames[0]))
    return items[1][1].decode()


def config_set(name, value):
    c = Conn()
    raw = c.command("CONFIG", "SET", name, str(value), wait=0.8)
    c.close()
    if not raw.startswith(b"+OK"):
        raise Malformed("CONFIG SET %s %s refused: %r" % (name, value, raw[:80]))


# ---- the shared oracle ------------------------------------------------------------------------

def check_stream(raw, expect_bulk, expect_pushes, label, push_kinds=(b">", b"*")):
    """The whole verdict for one probe, in one place.

      * the stream parses completely, with no leftover bytes
      * exactly one bulk string, byte-identical to what was written
      * at least `expect_pushes` out-of-band frames, each complete
      * the bulk body is not the container of anything else -- guaranteed by the parse:
        a spliced frame makes the body wrong AND the terminator wrong.

    Returns (ok, detail)."""
    try:
        frames = parse_all(raw)
    except Malformed as err:
        head = raw[:160]
        return False, "TORN: %s | head=%r" % (err, head)
    bulks = [v for k, v in frames if k == b"$" and v is not None and len(v) == len(expect_bulk)]
    if not bulks:
        return False, "no bulk of %d bytes in %d frames: %r" % (
            len(expect_bulk), len(frames), [k for k, _ in frames])
    for body in bulks:
        if body != expect_bulk:
            first = next((i for i in range(len(body)) if body[i] != expect_bulk[i]), 0)
            return False, ("TORN: bulk body differs at byte %d: got %r wanted %r"
                           % (first, body[first:first + 48], expect_bulk[first:first + 48]))
    pushes = [k for k, v in frames if k in push_kinds and isinstance(v, list)]
    if len(pushes) < expect_pushes:
        return False, "LOST: %d out-of-band frames, wanted >= %d (%s)" % (
            len(pushes), expect_pushes, label)
    return True, "%d frames, bulk %dB intact, %d oob" % (len(frames), len(expect_bulk), len(pushes))


def geometry_gate(name, before, after, keys, minimum=1):
    """A cell that never reached its geometry must FAIL, not pass quietly."""
    moved = {k: after.get(k, 0) - before.get(k, 0) for k in keys}
    if all(v < minimum for v in moved.values()):
        bad(name, "geometry NEVER constructed: %s" % moved)
        return False
    return True


# ---- cells ------------------------------------------------------------------------------------

def cell_pubsub_headholder(zc_min, size, tls=False):
    """PUB/SUB x RESP3 x PUBLISH head-holder x value >= zc-min.

    The audit's deterministic recipe. PUBLISH takes ROB slot k and stays not-Done until its
    channel home answers (a cross-thread round trip); GET takes slot k+1, completes in
    microseconds and sits Done-but-unretired behind it, with its "$<len>\\r\\n" header already
    written. The delivery is emitted in PASS A of the outbox flush, strictly before the publish
    result in PASS B -- so it is GUARANTEED to land in the window. That is the cell that spliced.

    RESP3 is required and only here: io_loop's subscriber gate lets a RESP3 subscriber run any
    command, which is what puts a borrowing GET in a subscribed connection's ROB at all."""
    tag = "pubsub/resp3/%dB%s" % (size, "/tls" if tls else "")
    value = bytes((i * 31 + 7) % 251 + 1 for i in range(size))
    before = admin_info()
    failures = []
    conn = Conn(tls=tls)
    try:
        conn.command("HELLO", "3", wait=0.5)
        conn.command("SET", "pt:big", value, wait=1.0)
        ack = conn.command("SUBSCRIBE", "pt:ch", wait=0.6)
        if b"subscribe" not in ack:
            bad(tag, "SUBSCRIBE never acknowledged: %r" % ack[:80])
            return
        for i in range(ITERS):
            probe = encode("PUBLISH", "pt:ch", "hello") + encode("GET", "pt:big")
            conn.send_raw(probe)
            raw = conn.drain(0.9, expect=3)
            good, detail = check_stream(raw, value, 1, tag)
            if not good:
                failures.append("iter %d: %s" % (i, detail))
                break
    finally:
        conn.close()
    after = admin_info()
    if failures:
        bad(tag, failures[0])
        return
    if not geometry_gate(tag, before, after, ["oob_frames_segmented", "oob_frames_deferred"]):
        return
    if zc_min and size >= zc_min and after.get("zc_sends", 0) == before.get("zc_sends", 0):
        bad(tag, "value >= zc-min but zc_sends never moved: no borrow was tested")
        return
    ok(tag, "%d probes, seg+%d def+%d" % (
        ITERS,
        after.get("oob_frames_segmented", 0) - before.get("oob_frames_segmented", 0),
        after.get("oob_frames_deferred", 0) - before.get("oob_frames_deferred", 0)))


def cell_tracking_self(zc_min, size, tls=False):
    """TRACKING x RESP3 x self-write pipeline x value >= zc-min.

    No head-holder needed, and no AOF: the geometry is built out of the retire path itself.
    `SET big <v2>` and `GET big` go out in ONE write, so they take adjacent ROB slots k and k+1
    on the same shard (same key => same worker => in-order completion). Retirement is in order,
    so SET retires first, and the invalidation for `big` fires from INSIDE that retire's
    notification hook -- at which point slot k+1 is the borrowing GET, Done, header written,
    unretired. That is the mid-drain cell, and it is why the send engine has a deferral buffer:
    the connection's newest reply is only partially staged when the frame is produced. RESP2 with
    no REDIRECT correctly has no invalidation channel; the MONITOR cells retain RESP2 coverage."""
    tag = "tracking/self/resp3/%dB%s" % (size, "/tls" if tls else "")
    v1 = bytes((i * 17 + 3) % 251 + 1 for i in range(size))
    v2 = bytes((i * 41 + 9) % 251 + 1 for i in range(size))
    before = admin_info()
    failures = []
    conn = Conn(tls=tls)
    try:
        conn.command("HELLO", "3", wait=0.5)
        reply = conn.command("CLIENT", "TRACKING", "on", wait=0.6)
        if not reply.startswith(b"+OK"):
            bad(tag, "CLIENT TRACKING on refused: %r" % reply[:80])
            return
        conn.command("SET", "pt:trk", v1, wait=1.0)
        for i in range(ITERS):
            # Register the read, so the next write to the key invalidates it.
            got = conn.command("GET", "pt:trk", wait=0.9, expect=1)
            good, detail = check_stream(got, v1 if i % 2 == 0 else v2, 0, tag)
            if not good:
                failures.append("iter %d (priming read): %s" % (i, detail))
                break
            fresh = v2 if i % 2 == 0 else v1
            probe = encode("SET", "pt:trk", fresh) + encode("GET", "pt:trk")
            conn.send_raw(probe)
            raw = conn.drain(0.9, expect=3)
            good, detail = check_stream(raw, fresh, 1, tag)
            if not good:
                failures.append("iter %d: %s" % (i, detail))
                break
    finally:
        conn.close()
    after = admin_info()
    if failures:
        bad(tag, failures[0])
        return
    if after.get("tracking_invalidations", 0) == before.get("tracking_invalidations", 0):
        bad(tag, "no invalidation was ever produced: the producer never fired")
        return
    if not geometry_gate(tag, before, after, ["oob_frames_deferred", "oob_frames_segmented"]):
        return
    if zc_min and size >= zc_min and after.get("zc_sends", 0) == before.get("zc_sends", 0):
        bad(tag, "value >= zc-min but zc_sends never moved: no borrow was tested")
        return
    ok(tag, "%d probes, inval+%d def+%d" % (
        ITERS,
        after.get("tracking_invalidations", 0) - before.get("tracking_invalidations", 0),
        after.get("oob_frames_deferred", 0) - before.get("oob_frames_deferred", 0)))


def cell_tracking_lost(zc_min, size):
    """ITEM 1 -- a parked out-of-band frame must never be DESTROYED.

    Eight worker-side sites call op.reply.clear() on an already-published op, and the CLIENT
    REPLY suppressing serve drops op.reply outright. While pushes lived in op.reply any of them
    could throw an invalidation away, and a lost invalidation leaves a client cache serving stale
    data forever -- a correctness failure with no error on either side.

    Oracle-free check: `tracking_invalidations` counts frames PRODUCED. Count the frames actually
    RECEIVED over a burst and require the two to agree. A destroyed frame moves the counter and
    never reaches the socket, so the equality is exactly the property at issue."""
    tag = "tracking/no-loss/%dB" % size
    value = bytes((i * 13 + 5) % 251 + 1 for i in range(size))
    n = 24
    reader = Conn()
    writer = Conn()
    try:
        reader.command("HELLO", "3", wait=0.5)
        if not reader.command("CLIENT", "TRACKING", "on", wait=0.6).startswith(b"+OK"):
            bad(tag, "CLIENT TRACKING on refused")
            return
        for i in range(n):
            writer.command("SET", "pt:loss:%d" % i, value, wait=0.8)
        # Register n reads, all borrowing when size >= zc-min.
        blob = b"".join(encode("GET", "pt:loss:%d" % i) for i in range(n))
        reader.send_raw(blob)
        got = reader.drain(1.5, expect=n)
        try:
            frames = parse_all(got)
        except Malformed as err:
            bad(tag, "TORN during the priming reads: %s" % err)
            return
        if len(frames) != n:
            bad(tag, "priming reads returned %d frames, wanted %d" % (len(frames), n))
            return
        before = admin_info()
        # Now invalidate all of them from ANOTHER connection while the reader keeps a pipeline of
        # borrowing GETs in flight -- so the frames land on ops in every ROB state there is.
        for i in range(n):
            reader.send_raw(encode("GET", "pt:loss:%d" % i))
            writer.send(*("SET", "pt:loss:%d" % i, value))
        received = reader.drain(2.5, expect=2 * n)
        writer.drain(1.5, expect=n)
        after = admin_info()
        try:
            frames = parse_all(received)
        except Malformed as err:
            bad(tag, "TORN: %s | head=%r" % (err, received[:160]))
            return
        pushes = sum(1 for k, v in frames if k in (b">",) and isinstance(v, list))
        produced = after.get("tracking_invalidations", 0) - before.get("tracking_invalidations", 0)
        if produced == 0:
            bad(tag, "no invalidation produced: the geometry was never built")
            return
        if pushes < produced:
            bad(tag, "LOST: %d invalidations produced, %d reached the client" % (produced, pushes))
            return
        ok(tag, "%d produced, %d delivered, stream intact" % (produced, pushes))
    finally:
        reader.close()
        writer.close()


def cell_monitor(zc_min, size, resp3):
    """MONITOR x (RESP3 | RESP2) x value >= zc-min. Protocol-agnostic producer: the feed line is
    a bare `+status`, so this cell needs neither RESP3 nor a subscription.

    Two sub-shapes, because the feed has two firing points relative to the ROB:
      * SELF traffic -- climon_armed_gate runs at PARSE time, before the current op is published,
        so the feed line for command N targets op N-1. Pipelining `GET big` then `PING` in one
        write aims the PING's feed line straight at the borrowing GET.
      * FOREIGN traffic -- a second connection generates commands continuously while this one
        holds a borrowed GET, which walks the whole ROB-state axis by arrival timing rather than
        by construction. Repetition plus the counters is what makes that honest: if
        oob_frames_segmented never moved, the cell FAILS instead of reporting a clean run."""
    tag = "monitor/%s/%dB" % ("resp3" if resp3 else "resp2", size)
    value = bytes((i * 23 + 11) % 251 + 1 for i in range(size))
    before = admin_info()
    failures = []
    mon = Conn()
    noise = Conn()
    try:
        if resp3:
            mon.command("HELLO", "3", wait=0.5)
        noise.command("SET", "pt:mon", value, wait=1.0)
        started = mon.command("MONITOR", wait=0.6)
        if not started.startswith(b"+OK"):
            bad(tag, "MONITOR refused: %r" % started[:80])
            return
        mon.drain(0.3)
        for i in range(ITERS):
            noise.send(*("SET", "pt:noise:%d" % i, "x"))
            mon.send_raw(encode("GET", "pt:mon") + encode("PING"))
            raw = mon.drain(0.7, expect=3, contains=b"+PONG\r\n")
            noise.drain(0.15, expect=1)
            # The feed lines are `+...` simple strings; the reply set is the bulk plus +PONG.
            good, detail = check_stream(raw, value, 0, tag)
            if not good:
                failures.append("iter %d: %s" % (i, detail))
                break
            if b"+PONG" not in raw:
                failures.append("iter %d: PING reply missing (reply stream shifted)" % i)
                break
    finally:
        mon.close()
        noise.close()
    after = admin_info()
    if failures:
        bad(tag, failures[0])
        return
    if after.get("monitor_feed_lines", 0) == before.get("monitor_feed_lines", 0):
        bad(tag, "monitor_feed_lines never moved: the producer never fired")
        return
    if not geometry_gate(tag, before, after, ["oob_frames_segmented", "oob_frames_deferred"]):
        return
    ok(tag, "%d probes, feed+%d seg+%d" % (
        ITERS,
        after.get("monitor_feed_lines", 0) - before.get("monitor_feed_lines", 0),
        after.get("oob_frames_segmented", 0) - before.get("oob_frames_segmented", 0)))


def cell_xshard_mget(zc_min, size):
    """CROSS-SHARD MGET x borrow x out-of-band frame -- N splice points, not one.

    assemble_mget stages [array header][borrow][...] into the segment queue and leaves the
    reply's TAIL in the Op, so between the last borrowed element and the array's end the frame is
    only PARTIALLY on the wire. The notification/tracking hook fires immediately after that, in
    the same retire callback. This is the cell the deferral buffer exists for.

    The keys must genuinely span shards. They are FOUND by bucketing candidates with DEBUG SHARD,
    never assumed, and a run that cannot find a cross-shard set FAILS rather than testing a
    single-shard MGET and reporting success."""
    tag = "xshard-mget/%dB" % size
    value = bytes((i * 29 + 2) % 251 + 1 for i in range(size))
    c = Conn()
    try:
        # The hash seed is drawn from the kernel at every boot, so the owner of a key name cannot
        # be known in advance: the set is FOUND by bucketing, exactly as the other cross-shard
        # batteries do, and a run that finds only one bucket fails below instead of quietly
        # testing a single-shard MGET.
        shards = {}
        for i in range(96):
            key = "pt:mg:%d" % i
            reply = c.command("DEBUG", "SHARD", key, wait=0.4)
            if reply[:1] != b":":
                bad(tag, "DEBUG SHARD unavailable (needs --enable-debug-command yes): %r"
                    % reply[:60])
                return
            shards.setdefault(int(reply[1:reply.find(b"\r\n")]), []).append(key)
        if len(shards) < 2:
            bad(tag, "no cross-shard key set found in 96 candidates (shards seen: %d)"
                % len(shards))
            return
        keys = [v[0] for v in list(shards.values())[:4]]
        if len(keys) < 2:
            bad(tag, "fewer than two distinct shards: geometry not constructed")
            return
        for k in keys:
            c.command("SET", k, value, wait=1.0)
        c.command("HELLO", "3", wait=0.5)
        if not c.command("CLIENT", "TRACKING", "on", wait=0.6).startswith(b"+OK"):
            bad(tag, "CLIENT TRACKING on refused")
            return
        before = admin_info()
        failures = []
        for i in range(max(8, ITERS // 4)):
            c.send_raw(encode("MGET", *keys))
            primed = c.drain(1.2, expect=1)
            try:
                parse_all(primed)
            except Malformed as err:
                failures.append("iter %d priming MGET: %s" % (i, err))
                break
            # Write one of the tracked keys and re-gather in ONE pass: the invalidation is raised
            # inside the same retire drain that is assembling the MGET.
            c.send_raw(encode("SET", keys[0], value) + encode("MGET", *keys))
            raw = c.drain(1.2, expect=3)
            try:
                frames = parse_all(raw)
            except Malformed as err:
                failures.append("iter %d: TORN: %s | head=%r" % (i, err, raw[:160]))
                break
            arrays = [v for k, v in frames if k == b"*" and isinstance(v, list) and len(v) == len(keys)]
            if not arrays:
                failures.append("iter %d: no MGET array of %d elements" % (i, len(keys)))
                break
            for element_kind, element in arrays[-1]:
                if element_kind != b"$" or element != value:
                    failures.append("iter %d: TORN gather element: %r" % (i, (element or b"")[:48]))
                    break
            if failures:
                break
        after = admin_info()
        if failures:
            bad(tag, failures[0])
            return
        if not geometry_gate(tag, before, after,
                             ["oob_frames_deferred", "oob_frames_segmented"]):
            return
        ok(tag, "%d shards, %d keys, def+%d" % (
            len(shards), len(keys),
            after.get("oob_frames_deferred", 0) - before.get("oob_frames_deferred", 0)))
    finally:
        c.close()


def cell_blocking_reply_survives():
    """ITEM 2 -- a push landing on a parked BLPOP must not swallow its timeout reply.

    blocking_retire synthesises the timeout / UNBLOCKED reply only when the op wrote no bytes
    (`op.reply.empty() && op.direct_len == 0`). A blocked op is the most likely out-of-band target
    there is, because parsing stops behind it and it is therefore the ROB tail for its whole life;
    a frame parked in its reply made that predicate false and the client waited forever for an
    answer that was never emitted.

    This cell fails LOUDLY on the timeout path: no null reply within the window is a FAIL, not a
    slow pass."""
    tag = "blocking/push-then-timeout"
    b = Conn(timeout=12)
    p = Conn()
    try:
        b.command("HELLO", "3", wait=0.5)
        ack = b.command("SUBSCRIBE", "pt:blk", wait=0.6)
        if b"subscribe" not in ack:
            bad(tag, "SUBSCRIBE never acknowledged")
            return
        b.send(*("BLPOP", "pt:nokey", "1"))
        time.sleep(0.15)
        p.command("PUBLISH", "pt:blk", "wake", wait=0.5)
        raw = b.drain(3.0, expect=2)
        try:
            frames = parse_all(raw)
        except Malformed as err:
            bad(tag, "TORN: %s | head=%r" % (err, raw[:160]))
            return
        pushes = [v for k, v in frames if k == b">"]
        nulls = [k for k, v in frames if (k == b"_") or (k == b"*" and v is None)]
        if not pushes:
            bad(tag, "the delivery never arrived: geometry not constructed")
            return
        if not nulls:
            bad(tag, "SWALLOWED: BLPOP timeout reply missing after a push landed on it: %r"
                % raw[:160])
            return
        ok(tag, "push delivered and BLPOP timeout still emitted")
    finally:
        b.close()
        p.close()


def cell_copy_control(size):
    """NEGATIVE CONTROL. Below zc-min the reply is COPIED and the old parking was correct, so this
    cell must be clean on BOTH the broken and the fixed tree. It is here to prove the harness is
    not simply always green: if this cell ever fails, the battery itself is wrong."""
    tag = "control/copying/%dB" % size
    value = bytes((i * 7 + 1) % 251 + 1 for i in range(size))
    conn = Conn()
    try:
        conn.command("HELLO", "3", wait=0.5)
        conn.command("SET", "pt:small", value, wait=0.6)
        if b"subscribe" not in conn.command("SUBSCRIBE", "pt:ch2", wait=0.6):
            bad(tag, "SUBSCRIBE never acknowledged")
            return
        for i in range(ITERS):
            conn.send_raw(encode("PUBLISH", "pt:ch2", "hello") + encode("GET", "pt:small"))
            raw = conn.drain(0.7, expect=3)
            good, detail = check_stream(raw, value, 1, tag)
            if not good:
                bad(tag, "iter %d: %s" % (i, detail))
                return
        ok(tag, "%d probes clean (expected on both trees)" % ITERS)
    finally:
        conn.close()


def main():
    global HOST, PORT, TLS_DIR, TLS_PORT, ITERS
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    HOST, PORT = args[0], int(args[1])
    i = 2
    while i < len(args):
        if args[i] == "--tls" and i + 1 < len(args):
            TLS_DIR = args[i + 1]
            i += 2
        elif args[i] == "--tls-port" and i + 1 < len(args):
            TLS_PORT = int(args[i + 1])
            i += 2
        elif args[i] == "--iters" and i + 1 < len(args):
            ITERS = int(args[i + 1])
            i += 2
        else:
            print("unknown argument %r" % args[i])
            return 2

    info = admin_info()
    for required in ("oob_frames_segmented", "oob_frames_deferred"):
        if required not in info:
            print("pushtear: INFO has no %s -- this server predates the out-of-band frame "
                  "channel, so no cell here can prove it reached its geometry. REFUSING to run."
                  % required)
            return 1

    try:
        zc_min = int(config_get("zc-min"))
    except Exception as err:                                  # noqa: BLE001
        print("pushtear: cannot read zc-min (%s). The value-size axis is the whole battery; "
              "REFUSING to run blind." % err)
        return 1

    # THE AXIS EVERY EXISTING TEST GETS WRONG. Sweep it here rather than trusting the boot:
    # zc-min is live-settable, so one boot covers borrow-off, borrow-always and the real default.
    sweep = []
    if zc_min:
        sweep.append(("boot default", zc_min, max(zc_min, 16384)))
    sweep.append(("forced borrow", 1, 64))
    sweep.append(("borrow disabled", 0, max(zc_min or 16384, 16384)))

    for label, knob, size in sweep:
        try:
            config_set("zc-min", knob)
        except Malformed as err:
            bad("sweep/%s" % label, "CONFIG SET zc-min %d refused: %s" % (knob, err))
            continue
        effective = int(config_get("zc-min"))
        if effective != knob:
            bad("sweep/%s" % label, "zc-min did not take: wanted %d, read %d" % (knob, effective))
            continue
        borrows = knob != 0 and size >= knob
        print("-- zc-min=%d (%s), value=%dB, borrowing=%s" % (knob, label, size, borrows))
        cell_pubsub_headholder(knob, size)
        cell_tracking_self(knob, size)
        cell_monitor(knob, size, resp3=True)
        cell_monitor(knob, size, resp3=False)
        if borrows:
            cell_tracking_lost(knob, size)
            cell_xshard_mget(knob, size)

    config_set("zc-min", zc_min)
    cell_blocking_reply_survives()
    cell_copy_control(64)

    if TLS_DIR and TLS_PORT:
        # TLS IS NOT IMMUNE. serve_tls_impl copies the borrowed value instead of handing it to the
        # kernel, but the concatenation order is identical -- [direct+reply][value][CRLF] -- so the
        # same splice reaches the same place.
        cell_pubsub_headholder(zc_min, max(zc_min or 16384, 16384), tls=True)
        cell_tracking_self(zc_min, max(zc_min or 16384, 16384), tls=True)

    print()
    print("CELL MAP (a pattern, not an aggregate -- the pattern IS the diagnosis):")
    for name, verdict, detail in CELLS:
        print("  %-40s %-4s %s" % (name, verdict, detail))
    print()
    print("pushtear: %d ok, %d FAIL" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
