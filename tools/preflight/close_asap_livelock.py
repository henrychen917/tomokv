#!/usr/bin/env python3
"""close_asap_livelock.py -- reproduce docs/BUGS.md N: the freeClientsInAsyncFreeQueue livelock.

THE DEFECT (observed live 2026-08-03, all-thread stack in the run-5 artifacts):
freeClient() returns early via freeClientAsync(c) when a real client still has worker commands in
flight (c->dispatchid != c->flushid). freeClientsInAsyncFreeQueue() clears CLIENT_CLOSE_ASAP just
before that call -- it must, or freeClient() would delete the list node itself and the drain would
delete it a second time -- and clearing it disarms freeClientAsync()'s re-entry guard. So the
client is re-appended to the TAIL of the list the drain is walking. listNext() reaches it, tries
again, re-appends, forever, allocating one list node per turn. The pass never returns to the event
loop, so handleWorkerReplies() never advances flushid, so the condition never clears.

WHAT IT LOOKS LIKE FROM OUTSIDE, and why it was misdiagnosed twice: the looping thread starves the
main thread on the allocator lock, main stops driving the FLATSTORE resize coordinator, and that
subsystem's 2-second watchdog fires. The log therefore accuses the resize machinery. PING keeps
answering (it lands on a different IO thread and needs no worker), so a PING-based liveness control
reports a healthy server -- which is exactly the wrong control, see docs/BUGS.md M and N.

TO REPRODUCE IT you need clients closed WHILE they have dispatched-but-undrained worker commands,
i.e. dispatchid != flushid at the moment the drain calls freeClient(). Mass closes alone are NOT
enough and a first version of this probe proved it: 40 rounds and 2560 connections killed
mid-pipeline against a KNOWN-BAD binary, no wedge. beforeSleepIO() runs handleWorkerReplies()
immediately before freeClientsInAsyncFreeQueue(), so flushid has normally caught up by the time
the drain looks.

The window only opens when the workers CANNOT drain -- which is exactly what a FLATSTORE resize
does: it parks every worker at its pop point until the table is rebuilt. That is why every observed
occurrence sat next to a resize event, and why the resize watchdog looked like the culprit. So this
probe drives continuous keyspace growth to force repeated table rebuilds, and fires the mass closes
into that park window. CLIENT_EX_PENDING does not save the real client here: it is set only on
FAKES (fake->flags / sub->flags), never on a real one, so both the drain's guard and
freeClientAsync()'s guard are inert for the client that matters.

VERDICT: this probe FAILS if the server stops making progress. It reports the gate counter
(tomokv_close_deferred_ring) so a PASS cannot be vacuous -- a run in which the deferral never
engaged proves nothing about the deferral, and says so.
"""
import argparse, socket, struct, sys, time


def conn(port, timeout=5.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def enc(*parts):
    # Coerce str -> bytes here rather than at every call site. Doing it per-site is how the first
    # run died: one `str` literal reached the bytes formatter and the probe reported FAIL before
    # it had tested anything, which reads exactly like a real failure.
    out = bytearray(b"*%d\r\n" % len(parts))
    for p in parts:
        if isinstance(p, str):
            p = p.encode()
        out += b"$%d\r\n%s\r\n" % (len(p), p)
    return bytes(out)


class Ctl:
    """Monitor connection. Deliberately separate from the load, and deliberately NOT the thing we
    trust for liveness on its own -- see info_field/progress below."""

    def __init__(self, port):
        self.port = port
        self.s = conn(port)
        self.buf = b""

    def cmd(self, *parts, budget=5.0):
        self.s.settimeout(budget)
        self.s.sendall(enc(*parts))
        end = time.time() + budget
        while time.time() < end:
            i = self.buf.find(b"\r\n")
            if i >= 0 and self.buf[:1] in (b"+", b"-", b":"):
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                return line.decode(errors="replace")
            if self.buf[:1] == b"$":
                i = self.buf.find(b"\r\n")
                if i >= 0:
                    n = int(self.buf[1:i])
                    if n == -1:
                        self.buf = self.buf[i + 2:]
                        return None
                    if len(self.buf) >= i + 2 + n + 2:
                        body = self.buf[i + 2:i + 2 + n]
                        self.buf = self.buf[i + 2 + n + 2:]
                        return body.decode(errors="replace")
            d = self.s.recv(1 << 20)
            if not d:
                raise ConnectionError("server closed the monitor connection")
            self.buf += d
        raise TimeoutError("no reply within %.1fs" % budget)

    def info_field(self, section, field, budget=5.0):
        txt = self.cmd("INFO", section, budget=budget)
        for line in (txt or "").splitlines():
            if line.startswith(field + ":"):
                return int(line.split(":", 1)[1])
        return None


def burst(port, conns, depth, keyspace, payload):
    """Open `conns` connections, each pipelining `depth` worker-routed commands, then close them
    all abruptly WITHOUT reading replies -- so every one of them is freed with fakes still in
    flight (dispatchid != flushid), which is the precondition for the defect."""
    socks = []
    for i in range(conns):
        try:
            s = conn(port, timeout=5.0)
        except Exception:
            break
        socks.append(s)
    # Fill every connection first, so the closes land together rather than trickling.
    for i, s in enumerate(socks):
        pipe = bytearray()
        for j in range(depth):
            k = b"sv:bulk:%d" % ((i * depth + j) % keyspace)
            pipe += enc(b"SET", k, payload) if (j & 1) else enc(b"GET", k)
        try:
            s.sendall(pipe)
        except Exception:
            pass
    for s in socks:
        try:
            # SO_LINGER 0 => RST. An abrupt reset is the harshest form of the close and the one
            # the churn lane produces under load; a graceful FIN would let the server drain first
            # and would quietly stop reproducing the window.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.close()
        except Exception:
            pass
    return len(socks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--conns", type=int, default=64)
    ap.add_argument("--depth", type=int, default=256)
    ap.add_argument("--keyspace", type=int, default=200000)
    ap.add_argument("--value", type=int, default=64)
    ap.add_argument("--grow-per-round", type=int, default=60000,
                    help="new keys per round; drives the FLATSTORE resize that parks the workers")
    ap.add_argument("--stall-budget", type=float, default=20.0,
                    help="seconds of no command progress before we call it wedged")
    a = ap.parse_args()

    payload = b"v" * a.value
    ctl = Ctl(a.port)

    # The grower. Its job is to keep the flat table crossing its resize trigger, so that workers
    # are parked in a quiesce when the mass closes land. Without this the defect does not
    # reproduce even on a known-bad binary (see the module docstring).
    grow = conn(a.port, timeout=30.0)
    grow_n = [0]

    def grow_chunk(nkeys):
        pipe = bytearray()
        for _ in range(nkeys):
            pipe += enc(b"SET", b"grow:%d" % grow_n[0], payload)
            grow_n[0] += 1
        try:
            grow.sendall(pipe)
            need, got = nkeys, 0
            grow.settimeout(30.0)
            while got < need:
                d = grow.recv(1 << 20)
                if not d:
                    return False
                got += d.count(b"\r\n")
        except Exception:
            return False
        return True
    try:
        base = ctl.info_field("stats", "total_commands_processed")
    except Exception as e:
        print("FAIL	could not read INFO before the test: %s" % e)
        return 1
    if base is None:
        print("FAIL	total_commands_processed missing from INFO stats")
        return 1

    opened = 0
    last_total, last_move = base, time.time()
    for r in range(1, a.rounds + 1):
        # Grow FIRST so a rebuild is likely in flight (or imminent) when the closes land.
        if not grow_chunk(a.grow_per_round):
            print("FAIL	round %d: the growth connection stopped responding -- the server is not "
                  "serving writes any more. Commands last moved at %d." % (r, last_total))
            return 1
        opened += burst(a.port, a.conns, a.depth, a.keyspace, payload)

        # Progress check. total_commands_processed must advance by MORE than our own probes.
        # If INFO itself stops answering that is a HARDER symptom, not a softer one -- it means the
        # IO thread serving us is gone too -- so it must not be swallowed as a retry.
        try:
            cur = ctl.info_field("stats", "total_commands_processed", budget=5.0)
        except Exception as e:
            # one reconnect: our own connection may have been on a thread that just died
            try:
                ctl2 = Ctl(a.port)
                cur = ctl2.info_field("stats", "total_commands_processed", budget=5.0)
                globals()["_"] = ctl2
            except Exception:
                waited = time.time() - last_move
                print("FAIL	round %d: INFO unanswerable for %.0fs (%s). Commands last moved at "
                      "%d. This is the wedge: the drain thread is looping and the server can no "
                      "longer answer." % (r, waited, type(e).__name__, last_total))
                return 1
        if cur is not None and cur > last_total + 50:
            last_total, last_move = cur, time.time()
        elif time.time() - last_move > a.stall_budget:
            print("FAIL	round %d: total_commands_processed stuck at %d for %.0fs while %d "
                  "connections were opened and killed. The server is wedged."
                  % (r, last_total, time.time() - last_move, opened))
            return 1

    # Liveness AND the gate. A server that survived but never entered the deferral tested nothing.
    try:
        deferred = ctl.info_field("stats", "tomokv_close_deferred_ring", budget=5.0)
    except Exception:
        deferred = None
    if deferred is None:
        try:
            deferred = Ctl(a.port).info_field("stats", "tomokv_close_deferred_ring", budget=5.0)
        except Exception:
            deferred = None

    try:
        pong = Ctl(a.port).cmd("PING", budget=5.0)
    except Exception as e:
        print("FAIL	server will not accept a fresh connection at the end: %s" % e)
        return 1
    if pong != "+PONG":
        print("FAIL	fresh connection did not answer PING (got %r)" % pong)
        return 1

    if deferred is None:
        print("PASS-UNGATED	survived %d rounds / %d killed connections, but "
              "tomokv_close_deferred_ring is not exported by this build, so it is NOT proven that "
              "the deferral was ever entered. Treat as inconclusive for the fix." % (a.rounds, opened))
        return 0
    if deferred == 0:
        print("PASS-UNGATED	survived %d rounds / %d killed connections, but "
              "tomokv_close_deferred_ring=0: the ring-not-drained window was NEVER entered, so "
              "this run says nothing about the fix. Raise --depth/--conns." % (a.rounds, opened))
        return 0
    print("PASS	%d rounds, %d connections killed mid-pipeline, no wedge; "
          "tomokv_close_deferred_ring=%d (deferral engaged, so the fixed path was exercised)"
          % (a.rounds, opened, deferred))
    return 0


if __name__ == "__main__":
    sys.exit(main())
