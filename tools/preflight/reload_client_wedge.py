#!/usr/bin/env python3
"""reload_client_wedge.py -- does DEBUG RELOAD leave PRE-EXISTING connections unable to get replies?

FOUND BY the stress_validation soak, 2026-08-02, phase numa1 cycle 2:

    20:37:17.332  DB saved on disk
    20:37:17.620  DB reloaded by DEBUG RELOAD        <- 288 ms, clean, logged success
    20:37:47.445  FAIL [bulk-conn] TimeoutError      <- exactly 30 s later = the client's OWN timeout

The reload was fast and succeeded. The server stayed up, kept accepting NEW connections and
answered PING. But two long-lived connections -- a bulk load lane and the control connection --
received no further replies and sat until their own socket timeouts fired. Zero crash markers.

This is DISTINCT from the two DEBUG RELOAD defects already on file:
  * J3 (fixed) -- emptyData() missed the shard dbs, so rdbLoad hit duplicate keys and the server
    took a Guru. That was a CRASH; here the server is healthy throughout.
  * J6 (retracted, twice, on bad evidence) -- I previously claimed orphaned sockets from
    connected_clients being per-io-thread, and from a probe whose key encoding was wrong. Neither
    of those is what this is: the evidence here is a reply that never arrives on a connection that
    is still open, measured against a control connection opened after the reload.

WHAT THIS SEPARATES
    IDLE lane      -- connected BEFORE the reload, sends NOTHING across it, used only afterwards.
    INFLIGHT lane  -- has pipelined commands outstanding AT the moment the reload runs.
    FRESH lane     -- connected AFTER the reload. The control: if this also fails, the server is
                      simply down and the test says nothing about connection orphaning.

    IDLE ok + INFLIGHT wedged  => replies for commands dispatched across the reload are LOST;
                                  the connection itself is fine.
    IDLE wedged too            => the breakage is at connection level, not per-command.
    FRESH wedged               => server-wide, not an orphaning bug at all.

EXIT 0 = no wedge observed, 1 = wedge reproduced, 2 = could not set up
"""

import argparse, select, socket, sys, threading, time


def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class C:
    def __init__(self, host, port, name, timeout=10.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.name = name

    def send(self, b):
        self.s.sendall(b)

    def _fill(self, timeout):
        self.s.settimeout(timeout)
        d = self.s.recv(1 << 20)
        if not d:
            raise ConnectionError("closed by peer")
        self.buf += d

    def read(self, timeout=10.0):
        """One reply, or TimeoutError. Deliberately simple: this probe only issues commands whose
        replies are a single line or a single bulk string."""
        end = time.time() + timeout
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, rest = self.buf[:i], self.buf[i + 2:]
                t = line[:1]
                if t in (b"+", b":", b"-"):
                    # STRIP the sigil. Returning it made every `== "PONG"` compare false, so a
                    # perfectly healthy control read as a failure and the whole first two runs
                    # scored INVALID. The status text is what callers compare against.
                    self.buf = rest
                    return line[1:].decode()
                if t == b"$":
                    n = int(line[1:])
                    if n == -1:
                        self.buf = rest
                        return None
                    if len(rest) >= n + 2:
                        self.buf = rest[n + 2:]
                        return rest[:n].decode()
                if t == b"*":
                    # only used for small arrays here; fall through to more data
                    pass
            left = end - time.time()
            if left <= 0:
                raise TimeoutError("no reply within %.1fs" % timeout)
            self._fill(left)

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7996)
    ap.add_argument("--keys", type=int, default=300000)
    ap.add_argument("--inflight-conns", type=int, default=8)
    ap.add_argument("--inflight-depth", type=int, default=256)
    ap.add_argument("--reply-timeout", type=float, default=10.0)
    # Which mutation to fire under load. emptyData()'s shard fold dispatches a per-worker sentinel
    # through the SAME queue as normal commands, so a flush is ordered wrt in-flight work by
    # construction; rdbLoad writes the shared node dbs from the main thread and is not. Running
    # both separates "the flush loses replies" from "the load does", which decides whether this is
    # a test-command defect or a production one (FLUSHALL is production; DEBUG RELOAD is not).
    ap.add_argument("--fire", default="DEBUG RELOAD",
                    help="command to run under load: 'DEBUG RELOAD', 'FLUSHALL', "
                         "'DEBUG RELOAD NOSAVE NOFLUSH MERGE', ...")
    a = ap.parse_args()

    a_fire = a.fire
    VAL = "v" * 32
    try:
        ctl = C(a.host, a.port, "ctl", timeout=120.0)
    except OSError as e:
        print("SETUP could not connect: %s" % e)
        return 2

    # Seed. The soak was at ~300k keys when it wedged; a tiny keyspace makes the reload so fast
    # that any window closes before we can be inside it.
    print("seeding %d keys ..." % a.keys, flush=True)
    B = 5000
    for base in range(0, a.keys, B):
        pipe = b"".join(enc("SET", "wk:%d" % i, VAL) for i in range(base, min(base + B, a.keys)))
        ctl.send(pipe)
        for _ in range(min(B, a.keys - base)):
            ctl.read(60.0)
    ctl.send(enc("DBSIZE"))
    print("seeded; dbsize=%s" % ctl.read(60.0), flush=True)

    # IDLE lane: open now, touch nothing until after the reload.
    idle = C(a.host, a.port, "idle", timeout=a.reply_timeout)

    # INFLIGHT lanes, driven by ONE select() loop rather than one thread each.
    #
    # WHY THIS MATTERS, and why the first version of this probe could not be trusted: with a thread
    # per lane, all of them are Python threads contending for the GIL while parsing tens of millions
    # of replies. A lane that simply does not get SCHEDULED for `reply-timeout` seconds raises
    # exactly the same TimeoutError as a lane the server never answered. That first version
    # "reproduced" reply loss 3 runs of 3 and then 0 of 2 after edits that could not possibly have
    # affected the server -- which is the signature of measuring the client, not the server.
    # A single select() loop has no such failure mode: every socket is polled by the same thread, so
    # a timeout means the bytes genuinely did not arrive.
    inflight = [C(a.host, a.port, "inflight%d" % i, timeout=a.reply_timeout)
                for i in range(a.inflight_conns)]
    for c in inflight:
        c.s.setblocking(False)
    bursts = [b"".join(enc("GET", "wk:%d" % (i * 1000 + j)) for j in range(a.inflight_depth))
              for i in range(len(inflight))]
    sent = [0] * len(inflight)
    got = [0] * len(inflight)
    errs = [None] * len(inflight)
    pend = [b""] * len(inflight)
    outst = [0] * len(inflight)
    last_rx = [time.time()] * len(inflight)

    def drain(i):
        """Consume complete replies buffered on lane i. All replies here are GET bulk strings."""
        c = inflight[i]
        n, k = 0, 0
        b = c.buf
        while True:
            j = b.find(b"\r\n", k)
            if j < 0:
                break
            if b[k:k + 1] != b"$":
                k = j + 2; n += 1; continue          # +OK / :N / -ERR
            ln = int(b[k + 1:j])
            if ln == -1:
                k = j + 2; n += 1; continue
            if len(b) < j + 2 + ln + 2:
                break
            k = j + 2 + ln + 2; n += 1
        if k:
            c.buf = b[k:]
        got[i] += n
        outst[i] -= n
        if n:
            last_rx[i] = time.time()
        return n

    def pump_until(deadline, stall_limit):
        """Run every lane until `deadline`. Returns the list of lanes that went `stall_limit`
        seconds with no bytes while still owed replies."""
        stalled = set()
        while time.time() < deadline:
            for i, c in enumerate(inflight):
                if not pend[i] and outst[i] <= a.inflight_depth // 2:
                    pend[i] = bursts[i]
                    sent[i] += a.inflight_depth
                    outst[i] += a.inflight_depth
            rl = [c.s for i, c in enumerate(inflight) if outst[i] > 0 and errs[i] is None]
            wl = [c.s for i, c in enumerate(inflight) if pend[i] and errs[i] is None]
            if not rl and not wl:
                break
            r, w, _ = select.select(rl, wl, [], 0.25)
            byfd = {c.s: i for i, c in enumerate(inflight)}
            for sk in w:
                i = byfd[sk]
                try:
                    nb = sk.send(pend[i]); pend[i] = pend[i][nb:]
                except Exception as e:
                    errs[i] = "send %s: %s" % (type(e).__name__, e)
            for sk in r:
                i = byfd[sk]
                try:
                    d = sk.recv(1 << 20)
                    if not d:
                        errs[i] = "closed by peer"; continue
                    inflight[i].buf += d
                    drain(i)
                except BlockingIOError:
                    pass
                except Exception as e:
                    errs[i] = "recv %s: %s" % (type(e).__name__, e)
            now = time.time()
            for i in range(len(inflight)):
                if outst[i] > 0 and errs[i] is None and now - last_rx[i] > stall_limit:
                    stalled.add(i)
        return sorted(stalled)

    def fresh_ping(tag):
        """Open a NEW connection and PING it. Returns (ok, seconds, err).

        The error is RETURNED, not swallowed: an earlier version discarded it, and a failure that
        took 0.003s -- i.e. an immediate exception, not a timeout -- was indistinguishable from a
        server that was refusing to answer. Those need completely different diagnoses."""
        t = time.time()
        try:
            f = C(a.host, a.port, tag, timeout=a.reply_timeout)
            f.send(enc("PING"))
            r = f.read(a.reply_timeout)
            f.close()
            return r == "PONG", time.time() - t, ("got %r" % r if r != "PONG" else "")
        except Exception as e:
            return False, time.time() - t, "%s: %s" % (type(e).__name__, e)

    # Warm the lanes so the pipelines are genuinely deep before anything is fired.
    pump_until(time.time() + 2.0, stall_limit=1e9)

    # CONTROL, and the whole reason this probe can conclude anything. If a fresh connection cannot
    # be served under this load even WITHOUT the mutation, then a failure afterwards says nothing
    # about the mutation -- it is just the load. Filing a DEBUG RELOAD defect without this control
    # is exactly how J6 got filed, and retracted, twice.
    pre_ok, pre_s, pre_e = fresh_ping("pre")
    print("control: fresh conn under load, BEFORE %s -> ok=%s in %.3fs %s"
          % (a_fire, pre_ok, pre_s, pre_e), flush=True)

    # Fire the mutation from ONE otherwise-idle thread, so the select loop keeps servicing every
    # lane throughout. This is the only thread besides the driver, and it spends its life blocked
    # on a single reply, so it cannot starve the loop the way the old thread-per-lane design did.
    fired = {}

    def fire_it():
        t = time.time()
        try:
            ctl.send(enc(*a_fire.split()))
            fired["reply"] = ctl.read(120.0)
        except Exception as e:
            fired["reply"] = "%s: %s" % (type(e).__name__, e)
        fired["secs"] = time.time() - t

    th = threading.Thread(target=fire_it, daemon=True)
    print("issuing %s under load ..." % a_fire, flush=True)
    th.start()
    # Keep pumping across the whole mutation, and for a generous window after it, watching for a
    # lane that stops receiving while still owed replies.
    while th.is_alive():
        pump_until(time.time() + 0.25, stall_limit=1e9)
    th.join(timeout=5.0)
    reload_secs = fired.get("secs", 0.0)
    r = fired.get("reply")
    print("%s -> %r in %.3fs" % (a_fire, r, reload_secs), flush=True)

    post_ok, post_s, post_e = fresh_ping("post")
    print("fresh conn under load, AFTER %s -> ok=%s in %.3fs %s"
          % (a_fire, post_ok, post_s, post_e), flush=True)

    # THE MEASUREMENT. Keep pumping well past the mutation. A lane that receives nothing for
    # `reply-timeout` seconds while still owed replies is stalled; if it is STILL owed them after
    # this whole window, they never came.
    stalled = pump_until(time.time() + a.reply_timeout * 2, stall_limit=a.reply_timeout)
    owed_before_quiesce = [sent[i] - got[i] for i in range(len(inflight))]

    # Stop issuing, then drain only. Anything that arrives now was LATE, not lost.
    for i in range(len(inflight)):
        pend[i] = b""
    late_start = sum(got)
    t_end = time.time() + 5.0
    while time.time() < t_end:
        rl = [c.s for i, c in enumerate(inflight) if outst[i] > 0 and errs[i] is None]
        if not rl:
            break
        r2, _, _ = select.select(rl, [], [], 0.25)
        byfd = {c.s: i for i, c in enumerate(inflight)}
        for sk in r2:
            i = byfd[sk]
            try:
                d = sk.recv(1 << 20)
                if not d:
                    errs[i] = "closed by peer"; continue
                inflight[i].buf += d
                drain(i)
            except Exception:
                pass
    late = sum(got) - late_start

    fresh_ok, fresh_s, fresh_e = fresh_ping("fresh")
    print("fresh conn QUIESCED (load stopped) -> ok=%s in %.3fs %s"
          % (fresh_ok, fresh_s, fresh_e), flush=True)

    idle_ok = False
    idle_err = ""
    try:
        idle.send(enc("PING"))
        idle_ok = idle.read(a.reply_timeout) == "PONG"
    except Exception as e:
        idle_err = "%s: %s" % (type(e).__name__, e)

    wedged = [i for i in range(len(inflight)) if sent[i] - got[i] > 0 or errs[i]]
    total_sent, total_got = sum(sent), sum(got)

    print("")
    print("mutation_secs      = %.3f" % reload_secs)
    print("fresh PRE          = %s in %.3fs   (control, under load) %s" % (pre_ok, pre_s, pre_e))
    print("fresh POST         = %s in %.3fs   (under the same load) %s" % (post_ok, post_s, post_e))
    print("fresh QUIESCED     = %s in %.3fs   (load stopped) %s" % (fresh_ok, fresh_s, fresh_e))
    print("idle_conn_ok       = %s   %s" % (idle_ok, idle_err))
    print("lanes stalled >%.0fs = %s" % (a.reply_timeout, stalled))
    print("inflight replies   = %d received of %d sent (still owed %d)"
          % (total_got, total_sent, total_sent - total_got))
    print("late replies       = %d arrived only after issuing stopped" % late)
    for i in wedged[:6]:
        print("    lane %d: owed %d, err=%s" % (i, sent[i] - got[i], errs[i]))

    ctl.close(); idle.close()
    for c in inflight:
        c.close()

    # ---- verdict, in the order that keeps the attribution honest ----
    if not pre_ok:
        print("\nRESULT INVALID the control failed: a fresh connection could not be served under "
              "this load BEFORE the mutation, so nothing here is attributable to it. Lower "
              "--inflight-conns/--inflight-depth until the control passes, then re-run.")
        return 2
    if not fresh_ok:
        print("\nRESULT SERVER NOT SERVING with the load stopped, after %s returned %r. That is a "
              "server-wide wedge, not per-connection reply loss." % (a_fire, r))
        return 1
    lost = total_sent - total_got
    if lost > 0 or not idle_ok:
        which = []
        if lost:
            which.append("%d replies never arrived on lanes %s" % (lost, wedged))
        if not idle_ok:
            which.append("the IDLE connection stopped answering")
        print("\nRESULT REPLY LOSS on %s: %s. Control passed before the mutation and a fresh "
              "connection works after it, and %d replies arrived late (so the drain window was "
              "long enough to catch a mere stall)." % (a_fire, "; ".join(which), late))
        return 1
    print("\nRESULT clean: %s under load lost nothing (%d replies, %d late, 0 owed)."
          % (a_fire, total_got, late))
    return 0


if __name__ == "__main__":
    sys.exit(main())
