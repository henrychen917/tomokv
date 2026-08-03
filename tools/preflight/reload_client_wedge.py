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
    a = ap.parse_args()

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

    # INFLIGHT lanes: keep a deep pipeline running across the reload.
    inflight = [C(a.host, a.port, "inflight%d" % i, timeout=a.reply_timeout)
                for i in range(a.inflight_conns)]
    stop = threading.Event()
    sent = [0] * len(inflight)
    got = [0] * len(inflight)
    errs = [None] * len(inflight)

    def pump(idx):
        c = inflight[idx]
        burst = b"".join(enc("GET", "wk:%d" % (idx * 1000 + j)) for j in range(a.inflight_depth))
        try:
            while not stop.is_set():
                c.send(burst)
                sent[idx] += a.inflight_depth
                for _ in range(a.inflight_depth):
                    c.read(a.reply_timeout)
                    got[idx] += 1
        except Exception as e:
            errs[idx] = "%s: %s" % (type(e).__name__, e)

    threads = [threading.Thread(target=pump, args=(i,), daemon=True) for i in range(len(inflight))]
    for t in threads:
        t.start()
    time.sleep(1.0)   # let the pipelines get genuinely deep

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

    # CONTROL, and the whole reason this probe can conclude anything. If a fresh connection cannot
    # be served under this load even WITHOUT a reload, then a post-reload failure says nothing
    # about the reload -- it is just the load. Filing a DEBUG RELOAD defect without this control is
    # exactly how J6 got filed, and retracted, twice.
    pre_ok, pre_s, pre_e = fresh_ping("pre")
    print("control: fresh connection under load, BEFORE any reload -> ok=%s in %.3fs"
          % (pre_ok, pre_s) + ("  %s" % pre_e if pre_e else ""), flush=True)

    print("issuing DEBUG RELOAD under load ...", flush=True)
    t0 = time.time()
    ctl.send(enc("DEBUG", "RELOAD"))
    try:
        r = ctl.read(120.0)
    except Exception as e:
        print("RESULT server did not answer DEBUG RELOAD: %s: %s" % (type(e).__name__, e))
        return 1
    reload_secs = time.time() - t0
    print("DEBUG RELOAD -> %r in %.3fs" % (r, reload_secs), flush=True)

    # Fresh connection immediately after the reload, still under the SAME load as the control.
    # This pair (pre vs post) is the measurement; a bare post-reload failure is not.
    post_ok, post_s, post_e = fresh_ping("post")
    print("fresh connection under load, AFTER the reload -> ok=%s in %.3fs  %s" % (post_ok, post_s, post_e),
          flush=True)

    # Give the in-flight lanes a bounded chance to finish what they had outstanding, then stop the
    # load COMPLETELY before the quiesced probes -- otherwise "server is saturated" and "server is
    # wedged" are indistinguishable, which is what made the first run of this probe inconclusive.
    time.sleep(a.reply_timeout + 2.0)
    stop.set()
    for t in threads:
        t.join(timeout=a.reply_timeout + 5.0)
    time.sleep(2.0)

    # FRESH, quiesced: no load at all. If this fails the server is genuinely not serving.
    fresh_ok, fresh_s, fresh_e = fresh_ping("fresh")
    print("fresh connection QUIESCED (load stopped) -> ok=%s in %.3fs  %s" % (fresh_ok, fresh_s, fresh_e),
          flush=True)

    # IDLE lane: was open across the reload but sent nothing during it. Tested only now, with the
    # load stopped, so a failure here cannot be blamed on saturation.
    idle_ok = False
    idle_err = ""
    try:
        idle.send(enc("PING"))
        idle_ok = idle.read(a.reply_timeout) == "PONG"
    except Exception as e:
        idle_err = "%s: %s" % (type(e).__name__, e)

    # THE DECISIVE MEASUREMENT: are the missing replies LOST, or merely LATE? Every wedged lane is
    # given one more quiesced chance to deliver what it was still owed. If they arrive now, the
    # defect is a multi-second STALL under load (bad, but bounded and not data loss). If they never
    # arrive, replies were DROPPED and the connection can never resynchronise -- a different and
    # much more serious defect, because the client is permanently desynchronised from its stream.
    late = 0
    for i, c in enumerate(inflight):
        owed = sent[i] - got[i]
        if owed <= 0:
            continue
        try:
            while owed > 0:
                c.read(3.0)
                late += 1
                got[i] += 1
                owed -= 1
        except Exception:
            pass

    wedged = [i for i, e in enumerate(errs) if e]
    total_sent, total_got = sum(sent), sum(got)   # got[] now includes any LATE arrivals

    print("")
    print("reload_secs        = %.3f" % reload_secs)
    print("fresh PRE-reload   = %s in %.3fs   (control, under load) %s" % (pre_ok, pre_s, pre_e))
    print("fresh POST-reload  = %s in %.3fs   (under the same load) %s" % (post_ok, post_s, post_e))
    print("fresh QUIESCED     = %s in %.3fs   (load stopped) %s" % (fresh_ok, fresh_s, fresh_e))
    print("idle_conn_ok       = %s   %s" % (idle_ok, idle_err))
    print("inflight lanes     = %d, wedged = %d" % (len(inflight), len(wedged)))
    print("inflight replies   = %d received of %d sent (missing %d)"
          % (total_got, total_sent, total_sent - total_got))
    print("late replies       = %d arrived only after the load stopped => stall, not loss" % late)
    for i in wedged[:4]:
        print("    lane %d: %s" % (i, errs[i]))

    ctl.close()
    idle.close()
    for c in inflight:
        c.close()

    # ---- verdict, in the order that keeps the attribution honest ----
    if not pre_ok:
        print("\nRESULT INVALID the control failed: a fresh connection could not be served under "
              "this load BEFORE any reload, so nothing here can be attributed to DEBUG RELOAD. "
              "Lower --inflight-conns/--inflight-depth until the control passes, then re-run.")
        return 2
    if not fresh_ok:
        print("\nRESULT SERVER NOT SERVING even with the load stopped, after a DEBUG RELOAD that "
              "returned +OK. That is a server-wide wedge, not per-connection orphaning.")
        return 1
    if wedged or not idle_ok:
        which = []
        if wedged:
            which.append("INFLIGHT (%d/%d lanes, %d replies never arrived)"
                         % (len(wedged), len(inflight), total_sent - total_got))
        if not idle_ok:
            which.append("IDLE")
        print("\nRESULT WEDGE REPRODUCED on %s, while the control passed before the reload and a "
              "fresh connection works after it => DEBUG RELOAD leaves PRE-EXISTING connections "
              "without replies." % " and ".join(which))
        return 1
    print("\nRESULT no wedge: every pre-existing connection kept getting replies across the reload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
