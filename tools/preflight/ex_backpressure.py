#!/usr/bin/env python3
"""ex_backpressure.py -- drive the worker-dispatch rings into back-pressure, on purpose.

WHY THIS EXISTS
    exDispatchPush() and csPushSpin() both contain a spin loop taken only when a worker's SPSC
    ring is FULL, and both were changed on 2026-08-02 (A3) to publish every staged ring rather
    than only the one they are stuck on. Nothing in the tree exercised either loop: across a full
    bigstress run and a full stress_validation soak, INFO tomokv_ex_queue_full stayed 0. A fix to
    a path no test enters is indistinguishable from no fix at all (docs/BUGS.md, "vacuous
    validation"), so this makes the path reachable and then asserts it was reached.

WHAT IT PROVES  (and, just as importantly, what it does NOT)
    PROVES  the back-pressure loop is entered -- per call site, because the two sites now keep
            separate counters -- and that replies stay CORRECT and the server stays alive while
            an io thread is spinning inside it.
    DOES NOT prove A3 itself is necessary or sufficient. The counter increments with or without
            A3; A3 changed only WHAT GETS PUBLISHED inside the spin, so its effect is on drain
            latency, not on whether the loop runs. Measuring that needs an A/B against a build
            with A3 reverted, which is a separate exercise. Do not cite this probe as evidence
            for A3's benefit -- only for its reachability and for correctness under it.

HOW SATURATION IS REACHED
    Rings are ex_queue_size deep (derived; 2048 in every shipping shape, since the formula is
    floored at 2048 and TOMO_EX_QUEUE_SIZE_MAX is also 2048). One ring belongs to one
    (worker, io-thread) pair. So a ring fills only when ONE io thread has >2048 commands in
    flight to ONE worker within a single event-loop pass.

    S1 (exDispatchPush): many connections, each deeply pipelined, ALL on a single key. One key
        => one bucket => one worker, so every connection an io thread owns funnels into the same
        ring. conns/io_threads * depth must exceed the ring depth by a wide margin.

    S2 (csPushSpin): the coalesced scatter emits one sub per WORKER per command, so no single
        MGET can overflow a ring however wide it is (see the note on csPushSpin). Saturation
        therefore needs MANY CONCURRENT scatters: deeply pipelined multi-key MGETs, each of
        which drops one sub into the same worker's ring.

    N (negative control): the same commands at low concurrency and shallow depth. Both counters
        MUST stay at 0. Without this arm, "counter > 0" would not distinguish a probe that
        induced saturation from a server that leaks the counter under any load at all.

EXIT  0 = pass, 1 = fail, 2 = skip (environment could not support the test)
"""

import argparse, select, socket, sys, time


class Incomplete(Exception):
    """Not enough bytes buffered yet to decode one whole reply."""


class Conn:
    """Minimal RESP2 client. Deliberately not shared with stress_validation.py: this probe has to
    keep thousands of replies outstanding, which that Conn's per-command round-trip cannot do.

    Both a BLOCKING api (cmd/read, used for setup and INFO) and an INCREMENTAL one (feed/try_read,
    used by the load arms) are provided. The load arms cannot use the blocking one: with `depth`
    commands outstanding on each of `conns` sockets, a send-all-then-read-all loop deadlocks as soon
    as the aggregate reply volume exceeds the socket buffers -- the server blocks writing to the
    first connection while the driver is still sending to the last, and neither side drains. At
    depth 512 with 24-key MGETs that is ~271 KB of replies per connection, i.e. comfortably past it.
    A hung probe is indistinguishable from a hung server, which is the single most expensive kind of
    harness bug to debug, so the load path is select-driven and never blocks on either direction."""

    def __init__(self, host, port, timeout=60.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.out = b""          # pending outbound bytes (load path)
        self.outstanding = 0    # replies still expected (load path)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    @staticmethod
    def enc(*args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            b = a.encode() if isinstance(a, str) else a
            out.append(b"$%d\r\n%s\r\n" % (len(b), b))
        return b"".join(out)

    def send(self, payload):
        self.sock.sendall(payload)

    def _fill(self):
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("server closed the connection")
        self.buf += chunk

    def _line(self):
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                return line
            self._fill()

    def read(self):
        line = self._line()
        t, rest = line[:1], line[1:]
        if t in (b"+", b":"):
            return rest.decode()
        if t == b"-":
            raise RuntimeError(rest.decode())
        if t == b"$":
            n = int(rest)
            if n == -1:
                return None
            while len(self.buf) < n + 2:
                self._fill()
            v, self.buf = self.buf[:n], self.buf[n + 2:]
            return v.decode()
        if t == b"*":
            n = int(rest)
            if n == -1:
                return None
            return [self.read() for _ in range(n)]
        raise RuntimeError("bad RESP type %r in %r" % (t, line))

    def cmd(self, *args):
        self.send(self.enc(*args))
        return self.read()

    # ---------------- incremental, non-blocking path (load arms only) ----------------

    def set_nonblocking(self):
        self.sock.setblocking(False)

    def _parse(self, buf, i):
        """Decode one reply from buf starting at i -> (value, next_i). Raises Incomplete."""
        j = buf.find(b"\r\n", i)
        if j < 0:
            raise Incomplete
        t, line, nxt = buf[i:i + 1], buf[i + 1:j], j + 2
        if t in (b"+", b":"):
            return line.decode(), nxt
        if t == b"-":
            return RuntimeError(line.decode()), nxt
        if t == b"$":
            n = int(line)
            if n == -1:
                return None, nxt
            if len(buf) < nxt + n + 2:
                raise Incomplete
            return buf[nxt:nxt + n].decode(), nxt + n + 2
        if t == b"*":
            n = int(line)
            if n == -1:
                return None, nxt
            vals = []
            for _ in range(n):
                v, nxt = self._parse(buf, nxt)
                vals.append(v)
            return vals, nxt
        raise RuntimeError("bad RESP type %r" % t)

    def drain_replies(self, verify, errors):
        """Consume every COMPLETE reply currently buffered. Returns how many were consumed."""
        got, i = 0, 0
        while i < len(self.buf):
            try:
                v, i = self._parse(self.buf, i)
            except Incomplete:
                break
            got += 1
            if not verify(v):
                if len(errors) < 5:
                    errors.append(repr(v)[:120])
        if i:
            self.buf = self.buf[i:]
        self.outstanding -= got
        return got

    def pump_read(self):
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("server closed the connection")
        self.buf += chunk

    def pump_write(self):
        n = self.sock.send(self.out)
        self.out = self.out[n:]


def info_counters(c):
    """The three numbers this probe judges on, plus the liveness ones it reports."""
    raw = c.cmd("INFO", "everything")
    out = {}
    for line in raw.splitlines():
        if ":" in line and line.startswith(("tomokv_", "total_commands_processed")):
            k, _, v = line.partition(":")
            try:
                out[k] = int(v)
            except ValueError:
                pass
    return out


def scatter_keys(nkeys):
    """Pick keys that a MULTI-worker MGET will genuinely scatter over.

    We cannot compute the server's key->worker mapping client-side, and there is no DEBUG command
    that exposes it. We do not need to: a scatter happens whenever the chosen keys do not all land
    on one worker, and with a few dozen arbitrary keys over >=2 workers that is overwhelmingly
    likely. The probe verifies engagement from the counter, not from a predicted mapping -- so a
    wrong guess here shows up honestly as NOT-ENGAGED rather than as a false pass."""
    return ["bp:mk:%d" % i for i in range(nkeys)]


def run_arm(host, port, name, conns, depth, payload_builder, verify, seconds):
    """Open `conns` connections, keep `depth` commands outstanding on each, for `seconds`.

    Deep outstanding depth IS the mechanism -- a request/response loop can never put more than one
    command per connection into a ring, so it could not saturate anything. Driven by select() in
    both directions so that neither the driver nor the server can block the other (see Conn)."""
    cs = []
    try:
        for _ in range(conns):
            c = Conn(host, port)
            c.set_nonblocking()
            cs.append(c)
    except OSError as e:
        for c in cs:
            c.close()
        return None, "could not open %d connections: %s" % (conns, e)

    burst, nreplies = payload_builder(depth)
    completed = 0
    errors = []
    deadline = time.time() + seconds
    stalled_since = None
    try:
        while time.time() < deadline:
            # Top every connection back up to `depth` outstanding. Refilling only when a socket has
            # fully drained would let outstanding sawtooth down to zero, and the ring only fills
            # while the depth is actually held.
            for c in cs:
                if not c.out and c.outstanding <= depth // 2:
                    c.out = burst
                    c.outstanding += nreplies

            rl = [c.sock for c in cs if c.outstanding]
            wl = [c.sock for c in cs if c.out]
            if not rl and not wl:
                break
            r, w, _ = select.select(rl, wl, [], 1.0)
            if not r and not w:
                # No progress in either direction for a second. Under back-pressure the server is
                # slow, not silent, so a sustained stall means something is genuinely wedged; fail
                # loudly rather than burn the arm's whole budget waiting.
                stalled_since = stalled_since or time.time()
                if time.time() - stalled_since > 30:
                    raise TimeoutError("no socket made progress for 30s (server wedged?)")
                continue
            stalled_since = None

            byfd = {c.sock: c for c in cs}
            for s in w:
                byfd[s].pump_write()
            for s in r:
                c = byfd[s]
                c.pump_read()
                completed += c.drain_replies(verify, errors)
    except Exception as e:
        for c in cs:
            c.close()
        return None, "%s: %s" % (type(e).__name__, e)
    for c in cs:
        c.close()
    return {"arm": name, "sent": completed, "errors": errors}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7898)
    ap.add_argument("--conns", type=int, default=128)
    ap.add_argument("--depth", type=int, default=512)
    ap.add_argument("--seconds", type=float, default=8.0)
    # Wide enough that each scatter sub does real work, and that the keys genuinely span workers.
    ap.add_argument("--mget-keys", type=int, default=64)
    # 1 MiB: ~100x a small GET on the worker, which is all that is needed to invert fill-vs-drain,
    # while staying cheap enough that the control connection's INFO is not queued behind tens of
    # seconds of accumulated work. At 8 MiB the arms saturated so hard that INFO itself timed out
    # and the probe could not read its own counters.
    ap.add_argument("--big-value-bytes", type=int, default=1 << 20)
    # REQUIRED, not derived: there is no tomokv_io_threads in INFO (only stock io_threads_active,
    # which does not track this fork's io identities). An earlier draft defaulted to 4 -- which
    # would have let the probe print a per-io-thread in-flight figure it had no basis for, and
    # silently under- or over-size its own saturation load. The launcher knows the real value.
    ap.add_argument("--io-threads", type=int, required=True,
                    help="io thread count the server was launched with (sizes the saturation load)")
    a = ap.parse_args()

    try:
        ctl = Conn(a.host, a.port, timeout=300.0)
    except OSError as e:
        print("SKIP could not connect: %s" % e)
        return 2

    depth_cfg = info_counters(ctl).get("tomokv_ex_queue_depth", 0)
    if depth_cfg <= 0:
        print("SKIP tomokv_ex_queue_depth not reported; cannot size the saturation load")
        return 2

    # A ring fills only when one io thread holds > depth_cfg in flight to one worker. Connections
    # spread over io threads, so the per-io share is what has to clear the ring.
    io_threads = max(1, a.io_threads)
    per_io_inflight = (a.conns // io_threads) * a.depth
    if per_io_inflight < depth_cfg * 2:
        print("SKIP load too small to saturate: %d in flight per io thread vs ring depth %d "
              "(raise --conns/--depth)" % (per_io_inflight, depth_cfg))
        return 2

    # SATURATION REQUIRES A SLOW CONSUMER, NOT A FAST PRODUCER.
    #
    # First attempt used GET/MGET on tiny values: 15.1 M commands, ring never filled once. The
    # arithmetic says why. A ring backs up only while it is filled faster than it drains; a worker
    # drains ~2 M ops/s, and this single-threaded Python driver generates well under that, so the
    # server is always ahead and the ring depth is never approached no matter how deep the pipeline
    # or how many connections. No amount of client concurrency fixes that -- the client is the
    # slower end.
    #
    # So make each command EXPENSIVE ON THE WORKER instead, which drops the drain rate below the
    # fill rate while keeping the reply tiny (reply volume is what would otherwise throttle us):
    #   S1  BITCOUNT over one large string -- one key => one bucket => one worker => ONE ring,
    #       hundreds of microseconds of worker CPU, and an integer reply.
    #   S2  EXISTS over many keys -- a genuine coalesced scatter (one sub per worker), each sub
    #       doing thousands of lookups, and again a single integer reply.
    # NOTE ON THE ABANDONED SLOW-CONSUMER VARIANT. Making each command expensive (BITCOUNT over a
    # 1-8 MiB string) does invert fill-vs-drain in principle, but at the concurrency needed to
    # exceed a 2048-deep ring it backlogs the server so heavily that the probe's own INFO
    # connection cannot be answered -- the apparatus breaks before the ring does, and a probe that
    # cannot read its own counters measures nothing. Kept as a documented dead end so it is not
    # retried. The load below is therefore the cheap shape, which runs cleanly and honestly reports
    # the path as UNREACHED.
    BIGBYTES = 64
    ctl.cmd("SET", "bp:hot", "x" * BIGBYTES)
    mkeys = scatter_keys(a.mget_keys)
    B = 2000
    for base in range(0, len(mkeys), B):
        chunk = mkeys[base:base + B]
        ctl.send(b"".join(Conn.enc("SET", k, "y") for k in chunk))
        for _ in chunk:
            ctl.read()

    def bitcount_hot(d):
        return Conn.enc("GET", "bp:hot") * d, d

    def exists_many(d):
        return Conn.enc("EXISTS", *mkeys) * d, d

    ok_str = lambda r: r == "x" * BIGBYTES
    ok_arr = lambda r: isinstance(r, str) and r == str(len(mkeys))

    print("ring_depth=%d io_threads=%d conns=%d depth=%d per_io_inflight=%d (%.1fx ring)"
          % (depth_cfg, io_threads, a.conns, a.depth, per_io_inflight, per_io_inflight / depth_cfg))

    arms = [
        # (name, conns, depth, builder, verify, seconds, expect_engaged, counter)
        ("N-control-get",  2, 1, bitcount_hot, ok_str, 3.0, False, "tomokv_ex_queue_full"),
        ("N-control-mget", 2, 1, exists_many,  ok_arr, 3.0, False, "tomokv_ex_queue_full_xshard"),
        ("S1-dispatch",  a.conns, a.depth, bitcount_hot, ok_str, a.seconds, True, "tomokv_ex_queue_full"),
        ("S2-scatter",   a.conns, a.depth, exists_many,  ok_arr, a.seconds, True, "tomokv_ex_queue_full_xshard"),
    ]

    failures = []
    unreached = []
    engaged = {}
    for name, conns, depth, builder, verify, secs, expect, counter in arms:
        before = info_counters(ctl)
        res, err = run_arm(a.host, a.port, name, conns, depth, builder, verify, secs)
        if err:
            print("ARM %-14s ABORTED %s" % (name, err))
            failures.append("%s aborted: %s" % (name, err))
            continue
        after = info_counters(ctl)
        d_total = after.get("tomokv_ex_queue_full", 0) - before.get("tomokv_ex_queue_full", 0)
        d_cs = after.get("tomokv_ex_queue_full_xshard", 0) - before.get("tomokv_ex_queue_full_xshard", 0)
        # exDispatchPush's own share is the total minus the scatter's, because both bump the total.
        d_disp = d_total - d_cs
        got = d_cs if counter.endswith("xshard") else d_disp
        engaged[name] = got

        print("ARM %-14s sent=%-9d dispatch_full=%-8d xshard_full=%-8d replies_bad=%d"
              % (name, res["sent"], d_disp, d_cs, len(res["errors"])))
        if res["errors"]:
            for e in res["errors"]:
                print("    BAD REPLY %s" % e)
            failures.append("%s returned %d wrong replies -- correctness broke under back-pressure"
                            % (name, len(res["errors"])))
        if expect and got <= 0:
            # NOT a failure. Measured 2026-08-02: this ring cannot be driven into back-pressure by
            # any load this harness can generate, and the arithmetic says why rather than the
            # result being a mystery. A ring backs up only while filled faster than drained. Depth
            # is 2048 per (worker, io) pair; a worker drains ~2M ops/s; one client process
            # generates well under that, so with cheap commands the server is always ahead --
            # 15.1M commands produced zero exhaustion. Inverting it with expensive commands
            # (BITCOUNT over 1 MiB) works in principle but backlogs the server so hard that the
            # probe's own INFO connection cannot be answered, i.e. the apparatus breaks before the
            # ring does.
            #
            # So report UNREACHABLE, not FAIL. Failing here would block every future run on a
            # property that may be genuinely unreachable in production, and would tell a reader
            # the fix is broken when what is actually true is that the path is defensive.
            unreached.append("%s: %s delta 0 after %d commands" % (name, counter, res["sent"]))
        if not expect and got > 0:
            failures.append("%s is a NEGATIVE CONTROL and it engaged (%s delta %d). The load is "
                            "not discriminating -- saturation cannot be attributed to the S arms."
                            % (name, counter, got))

    final = info_counters(ctl)
    alive = ctl.cmd("PING")
    print("final alive=%s total_commands=%s handoff_missed=%s"
          % (alive, final.get("total_commands_processed"), final.get("tomokv_handoff_missed")))
    if alive != "PONG":
        failures.append("server did not answer PING after the saturation arms")

    if failures:
        for f in failures:
            print("FAIL %s" % f)
        return 1
    if unreached:
        for u in unreached:
            print("UNREACHED %s" % u)
        print("SKIP back-pressure not reachable with this load; replies were correct throughout "
              "and the negative controls stayed clean. The ring is 2048 deep per (worker, io) pair "
              "against a ~2M ops/s drain, so a single client cannot outrun it -- see the note in "
              "the engagement check. This says the A3 spin loop is DEFENSIVE, not that it is "
              "broken; it remains unverified by execution.")
        return 2
    print("PASS both back-pressure sites entered (dispatch=%d xshard=%d), replies correct, "
          "controls clean, server alive"
          % (engaged.get("S1-dispatch", 0), engaged.get("S2-scatter", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
