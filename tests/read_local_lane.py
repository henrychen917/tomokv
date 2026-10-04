#!/usr/bin/env python3
"""Armed local-read LANE ADMISSION battery (P128.md).

Usage: read_local_lane.py HOST PORT
  RL1: read_local_lane.py HOST PORT --mget-fence (also needs --atomic 1)
  boot: --thread-mode 1s|2s --overlap 0|1 --read-local 1 --enable-debug-command yes
  serverless: read_local_lane.py --self-test [transient|delayed-drain|never-drains|leak-full|leak-quota]
  RL1 harness: read_local_lane.py --self-test mget-fence[-old|-unarmed|-stale]

The fused thread's local-read lane holds kInboxSlots (1024) entries. A connection may pipeline up
to kRobWindow (64) ops, so a thread that has accepted more than 16 deep-pipelining connections can
be asked for more local reads in one rotation than its lane holds. The shipped rule is: the excess
is DEFERRED (the frame stays at rpos and is re-parsed by a later pass of the same thread, where it
is still served locally) and, while the lane is under pressure, the lane is divided among the
thread's active connections so that no connection can crowd out the ones the rotation parses last.
The former rule demoted the excess to the shard owner as an ordinary task; 7/8 of those tasks were
cross-thread, and they were the seed of the p128 / 2048-connection pure-read collapse.

WHY THIS BATTERY DRIVES A CAP INSTEAD OF LOAD. Oversubscribing a 1024-entry lane by traffic is a
RATE RACE against the drain, and a test client cannot win it: the fused thread empties the lane
every rotation, far faster than one Python process can fill it. Piling on connections does not
help -- the gate measured 256 connections x 64 deep = 2624 pipelined frames producing ZERO lane
events, because the frames were never in flight at once. So the anti-vacuity checks below could
only fire on a saturated rig, and a row that fires only on its author's rig is not a gate row.

Instead, DEBUG READ-LOCAL-LANE-CAP lowers the ADMISSION threshold (the ring keeps its kInboxSlots
entries and its masking; only the parser's "has room" test moves). One connection pipelining more
than the cap in a single write then oversubscribes the lane INSIDE ONE PARSE PASS -- before any
drain can run -- so the mechanism fires deterministically with a handful of connections, on any
box, at any speed. The cap derives to kInboxSlots whenever it is unset, which is what production
always runs; phase 1 below measures the uncapped behaviour precisely so the capped result has a
control to be compared against.

Checks (all counter deltas over this battery's own traffic -- the vacuous-validation rule):
  control    with the cap unset, record the same traffic's lane deltas; the capped phase must
             produce strictly more, which is what proves the CAP is the reason it fires
  lane full  read_local_defer_lane_full  > 0   the lane WAS oversubscribed -- otherwise every
                                                other check here would be vacuous
  no demote  clean traffic completes 100% locally; the serverless core route fixture also
             observes actual owner publication (zero), independent of telemetry
  fair share read_local_defer_quota      > 0   the pressure window armed and divided the lane
  local      clean GETs: exact hit count and zero fallbacks; separate mixed-write traffic keeps
             the original >=95% shared-GET floor for legitimate RYOW/sequence fallbacks
  order      every connection receives every reply, in order, with the expected value; the SET
             that follows the deferred GETs on the same connection and the GET behind it prove
             frame order and read-your-own-write survive a deferral
  liveness   every round completes (a deferred frame must be re-parsed without an external wake)
  restore    after setting the cap back to 0, one uncounted clean round and bounded INFO polling
             drain transient pressure; measured deferrals must then exactly match the control
"""
import sys
import select
import time

import _lib

DEPTH = 64          # GETs per connection per round == kRobWindow
CONNS = 16          # small and deterministic: the cap, not the load, creates the pressure
ROUNDS = 6
CAP = 8             # effective lane capacity while the mechanism is under test
ROUND_DEADLINE_S = 20.0
DRAIN_DEADLINE_S = 2.0
DRAIN_POLL_S = 0.01
DRAIN_QUIET_S = 0.05
REMOVED_KEYS = ("read_local_fallback_lane_full", "read_local_mget_fallback_lane_full",
                "read_local_mget_generation_retries")
COUNTERS = ("read_local_hits", "read_local_fallbacks",
            "read_local_defer_lane_full", "read_local_defer_quota")
DEFERRALS = ("read_local_defer_lane_full", "read_local_defer_quota")


def assert_retired_keys_absent(table):
    for key in REMOVED_KEYS:
        if key in table:
            raise AssertionError("retired INFO key is still present: %s" % key)


def counters(conn, names=COUNTERS):
    table = _lib.info(conn, "stats")
    assert_retired_keys_absent(table)
    out = {}
    for key in names:
        if key not in table:
            raise AssertionError("INFO stats has no %s; the battery cannot prove its mechanism"
                                 % key)
        out[key] = int(table[key])
    return out


MGET_COUNTERS = ("read_local_mget_local_hits", "read_local_mget_fallbacks",
                 "read_local_mget_fallback_inflight_write",
                 "atomic_inflight")


def mget_fence():
    """Hold a precise, cross-owner MSET at the ROB head using the existing commit latch.

    N disjoint MGETs must complete on the lane BEFORE that MSET can retire. Old RL1 code
    stops at one hit indefinitely; a final N-hit count after reading the replies would not
    discriminate it. The last MGET conflicts with the held write and must demote for RYOW.
    No timing race: the latch stays armed through the counter and no-reply assertions.
    """
    host, port = _lib.host_port()
    ctl = _lib.Conn(host, port, timeout=ROUND_DEADLINE_S)
    rep = _lib.Report("read_local_mget_fence")
    try:
        for knob in ("read-local", "atomic"):
            cfg = ctl.cmd("CONFIG", "GET", knob)
            if not (isinstance(cfg, list) and len(cfg) == 2 and cfg[1] == b"1"):
                raise AssertionError("needs --%s 1: %r" % (knob, cfg))
        server = _lib.info(ctl, "server")
        if server.get("read_local") != "1" or int(server["read_local_active_threads"]) == 0:
            raise AssertionError("read-local connection needs an active reader lane")
        ctl.must("DEBUG", "READ-LOCAL-LANE-CAP", "0")
        topo = _lib.topology(ctl)
        # Find two write owners and two other shards. Read keys are on untouched shards, so
        # the held group's foreign-read filter cannot demote these MGETs by a cell collision.
        keys = {}
        for key, shard, owner in _lib.probe_keys(ctl, "rl:fence", topo):
            keys.setdefault(shard, (key, owner))
            first = next(iter(keys))
            second = next((s for s in keys if keys[s][1] != keys[first][1]), None)
            clean = [s for s in keys if s not in (first, second)]
            if second is not None and len(clean) >= 2:
                break
        else:
            raise AssertionError("MGET fence geometry needs two owners and four shards")
        writes = [keys[s][0] for s in (first, second)]
        shared = [keys[s][0] for s in clean[:2]]
        values = [b"left", b"right"]
        for key, value in zip(shared, values):
            ctl.must("SET", key, value)

        for depth in (8, 32):
            # A missing arm is retried only on a fresh connection and fresh write state.
            # Once the pending group and first hit exist, any failure is final.
            for attempt in range(3):
                c = _lib.Conn(host, port, timeout=ROUND_DEADLINE_S, buffering=1 << 16)
                try:
                    for key in writes:
                        ctl.must("SET", key, b"old")
                    # No writes on c before its first read: prove that the connection arms
                    # cleanly, rather than accepting a pre-arming transient as test coverage.
                    before_arm = counters(ctl, MGET_COUNTERS)
                    if c.cmd("MGET", *shared) != values:
                        raise AssertionError("arming MGET reply mismatch")
                    base = counters(ctl, MGET_COUNTERS)
                    if base["atomic_inflight"] != 0:
                        raise AssertionError("setup atomic groups must drain before the fence arm")
                    if (base["read_local_mget_local_hits"] -
                            before_arm["read_local_mget_local_hits"] != 1):
                        raise AssertionError("arming MGET must complete on the lane")
                    frames, replies = [], []
                    for index in range(depth):
                        # Alternating key order catches reply reordering; repeated keys catch
                        # accidental GET-shaped replies without depending on missing-key rules.
                        order = (0, 1, 0) if index % 2 == 0 else (1, 0, 1)
                        frames.append(_lib.encode("MGET", *(shared[i] for i in order)))
                        replies.append([values[i] for i in order])
                    new = b"new:%d:%d" % (depth, attempt)
                    payload = _lib.encode("MSET", writes[0], new, writes[1], new)
                    payload += b"".join(frames)
                    payload += _lib.encode("MGET", *writes, shared[0])
                    expected = [b"OK"] + replies + [[new, new, values[0]]]
                    entered = False
                    with _lib.armed(ctl, "ATOMIC-COMMIT-HOLD", 1):
                        c.sock.sendall(payload)
                        deadline = time.monotonic() + DRAIN_DEADLINE_S
                        while True:
                            now = counters(ctl, MGET_COUNTERS)
                            hits = now["read_local_mget_local_hits"] - base["read_local_mget_local_hits"]
                            pending = now["atomic_inflight"] > 0
                            entered |= pending and hits > 0
                            if select.select([c.sock], [], [], 0)[0]:
                                raise AssertionError("held MSET must prevent every ROB reply retirement")
                            ryow = (now["read_local_mget_fallback_inflight_write"] -
                                    base["read_local_mget_fallback_inflight_write"])
                            if (hits == depth and ryow == 1) or time.monotonic() >= deadline:
                                break
                            time.sleep(DRAIN_POLL_S)
                        if entered:
                            if not pending:
                                raise AssertionError("commit hold ended before fence observation")
                            if hits != depth:
                                raise AssertionError("RL1: N MGET lane hits before ROB retirement: "
                                                     "got %d, want %d" % (hits, depth))
                            if (ryow != 1 or now["read_local_mget_fallbacks"] -
                                    base["read_local_mget_fallbacks"] != 1):
                                raise AssertionError("only the conflicting trailing MGET must demote for RYOW")
                    got = [c.read() for _ in expected]
                    if got != expected:
                        raise AssertionError("MGET pipeline replies/order/RYOW: got %r want %r"
                                             % (got, expected))
                    if entered:
                        rep.check("p%d: N lane hits with retirement blocked; ordered replies + RYOW"
                                  % depth, True, "hits=%d; RYOW demotions=%d" % (hits, ryow))
                        break
                finally:
                    c.close()
            else:
                raise AssertionError("MGET fence window never opened after 3 fresh arms (p%d)" % depth)
    finally:
        ctl.close()
    rep.finish()


def mget_fence_self_test(trace):
    """Exercise the live harness's actual held-window verdict and cleanup without a server.

    The old trace reaches N total hits on release, so checking only final totals would pass it.
    Production fence logic itself is tested separately by build/rlfence-unit and a reverted copy.
    """
    import io
    from types import SimpleNamespace
    from unittest.mock import patch

    if trace not in ("mget-fence", "mget-fence-old", "mget-fence-unarmed", "mget-fence-stale"):
        raise AssertionError("unknown MGET fence trace: %s" % trace)
    stats = dict.fromkeys(MGET_COUNTERS, 0)
    data, clients = {}, []
    state = {"held": False, "late_hits": 0, "clock": 0.0, "bursts": 0}
    read_resp = _lib.Conn.read
    read_line = _lib.Conn._line

    class TraceConn:
        def __init__(self, *args, **kwargs):
            self.sock = self
            self.replies = []
            self.closed = False
            clients.append(self)

        def cmd(self, *args):
            if args[:2] == ("CONFIG", "GET"):
                return [args[2].encode(), b"1"]
            if args == ("INFO", "server"):
                return b"read_local:1\r\nread_local_active_threads:6\r\n"
            if args == ("INFO", "stats"):
                return "".join("%s:%d\r\n" % item for item in stats.items()).encode()
            if args[:2] == ("DEBUG", "READ-LOCAL-LANE-CAP"):
                return b"OK"
            if args[:2] == ("DEBUG", "ATOMIC-COMMIT-HOLD"):
                state["held"] = bool(int(args[2]))
                if not state["held"]:
                    stats["atomic_inflight"] = 0
                    stats["read_local_mget_local_hits"] += state["late_hits"]
                    state["late_hits"] = 0
                return b"OK"
            if args[0] == "SET":
                data[args[1].encode()] = args[2]
                return b"OK"
            if args[0] == "MGET":
                stats["read_local_mget_local_hits"] += 1
                return [data[key.encode()] for key in args[1:]]
            raise AssertionError("unexpected MGET fence trace command: %r" % (args,))

        must = cmd

        def sendall(self, payload):
            assert state["held"]
            state["bursts"] += 1
            wire = SimpleNamespace(file=io.BytesIO(payload))
            wire._line = lambda: read_line(wire)
            wire.read = lambda: read_resp(wire)
            commands = []
            while wire.file.tell() < len(payload):
                commands.append(wire.read())
            head, *reads = commands
            assert head[0] == b"MSET" and all(cmd[0] == b"MGET" for cmd in reads)
            for key, value in zip(head[1::2], head[2::2]):
                data[key] = value
            self.replies = [b"OK"] + [[data[key] for key in cmd[1:]] for cmd in reads]
            if trace == "mget-fence-stale":
                self.replies[-1][0] = b"old"
            depth = len(reads) - 1
            hits = 1 if trace == "mget-fence-old" else depth
            stats["read_local_mget_local_hits"] += hits
            stats["atomic_inflight"] = 0 if trace == "mget-fence-unarmed" else 1
            state["late_hits"] = depth - hits
            if hits == depth:
                stats["read_local_mget_fallbacks"] += 1
                stats["read_local_mget_fallback_inflight_write"] += 1

        def read(self):
            assert not state["held"], "live harness must not read replies while the latch is held"
            return self.replies.pop(0)

        def close(self):
            self.closed = True

    def sleep(seconds):
        state["clock"] += seconds

    with patch.object(_lib, "Conn", TraceConn), \
            patch.object(_lib, "host_port", return_value=("serverless", 0)), \
            patch.object(_lib, "topology", return_value=None), \
            patch.object(_lib, "probe_keys", return_value=iter(
                [("a", 0, 0), ("p", 1, 1), ("b", 2, 0), ("c", 3, 1)])), \
            patch.object(select, "select", return_value=([], [], [])), \
            patch.object(time, "monotonic", side_effect=lambda: state["clock"]), \
            patch.object(time, "sleep", side_effect=sleep):
        try:
            mget_fence()
        except SystemExit as exc:
            if exc.code != 0:
                raise
        finally:
            assert not state["held"] and all(c.closed for c in clients), "trace cleanup"
    assert state["bursts"] == 2
    print("read_local_lane serverless mget-fence PASS (held-window verdict, replies and RYOW)")


def burst_round(conns, shared, values, r, mixed=True):
    """One round: every connection pipelines DEPTH shared GETs + SET own-key + GET own-key in a
    single write, so a connection's whole window reaches the parser in one pass. Returns
    (ok, detail, elapsed)."""
    want = values + ([b"OK", b"r%d" % r] if mixed else [])
    t0 = time.monotonic()
    for i, c in enumerate(conns):
        payload = b"".join(_lib.encode("GET", k) for k in shared)
        if mixed:
            payload += _lib.encode("SET", "rl:lane:own:%d" % i, "r%d" % r)
            payload += _lib.encode("GET", "rl:lane:own:%d" % i)
        c.sock.sendall(payload)
    for i, c in enumerate(conns):
        try:
            got = [c.read() for _ in range(len(want))]
        except Exception as exc:   # a hang here is a deferred frame nobody re-parsed
            return False, "round %d conn %d: %r" % (r, i, exc), time.monotonic() - t0
        if got != want:
            bad = next(j for j in range(len(want)) if got[j] != want[j])
            return False, "round %d conn %d reply %d: got %r want %r" % (
                r, i, bad, got[bad], want[bad]), time.monotonic() - t0
    return True, "", time.monotonic() - t0


def drive(conns, shared, values, first_round, rounds, mixed=True):
    """rounds rounds of burst traffic. Returns (ok, detail, slowest, shared_gets)."""
    slow = 0.0
    for r in range(first_round, first_round + rounds):
        ok, detail, elapsed = burst_round(conns, shared, values, r, mixed)
        slow = max(slow, elapsed)
        if not ok:
            return False, detail, slow, 0
    return True, "", slow, DEPTH * len(conns) * rounds


def wait_for_lane_drain(ctl):
    """Return the baseline after both deferral counters stay unchanged for a quiet interval.

    All settle replies have already arrived. INFO stability observes the remaining accounting;
    it cannot prove that an idle lane's cap/quota state is correct. The next measured burst must
    still match the control exactly. A busy counter restarts only the quiet interval, never the
    absolute deadline, and even an INFO read is bounded by the time left.
    """
    deadline = time.monotonic() + DRAIN_DEADLINE_S
    quiet_since = time.monotonic()
    previous = None
    timeout = ctl.sock.gettimeout()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("deferral counters kept changing")
            ctl.sock.settimeout(min(timeout, remaining) if timeout is not None else remaining)
            current = counters(ctl)
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError("INFO did not complete before the drain deadline")
            if previous is None or any(current[k] != previous[k] for k in DEFERRALS):
                quiet_since = now
            elif now - quiet_since >= DRAIN_QUIET_S:
                return current
            previous = current
            time.sleep(min(DRAIN_POLL_S, deadline - now))
    except TimeoutError as exc:
        raise AssertionError("cap reset restores derived-lane pressure: settle deferral counters "
                             "did not drain within %.2fs: %r (%s)"
                             % (DRAIN_DEADLINE_S, previous, exc)) from exc
    finally:
        ctl.sock.settimeout(timeout)


def settle_reset_lane(ctl, conns, shared, values):
    """One uncounted round of the exact clean traffic, then a bounded drain; never retry it."""
    before = counters(ctl)
    ok, detail, slow, reads = drive(conns, shared, values, 0, 1, mixed=False)
    if not ok or slow >= ROUND_DEADLINE_S:
        raise AssertionError("clean settle order/liveness: %s (%.3fs)" % (detail, slow))
    drained = wait_for_lane_drain(ctl)
    if (drained["read_local_hits"] - before["read_local_hits"] != reads
            or drained["read_local_fallbacks"] != before["read_local_fallbacks"]):
        raise AssertionError("clean settle GETs must all complete locally: before=%r after=%r / %d"
                             % (before, drained, reads))
    return drained


def main():
    host, port = _lib.host_port()
    ctl = _lib.Conn(host, port)
    cfg = ctl.cmd("CONFIG", "GET", "read-local")
    if not (isinstance(cfg, list) and len(cfg) == 2 and cfg[1] == b"1"):
        raise AssertionError("needs --read-local 1 (CONFIG GET read-local -> %r)" % (cfg,))
    server = _lib.info(ctl, "server")
    if server.get("read_local") != "1" or int(server["read_local_active_threads"]) == 0:
        raise AssertionError("read-local was requested but no reader lane is active: %r" % server)
    probe = ctl.cmd("DEBUG", "READ-LOCAL-LANE-CAP", "0")
    if isinstance(probe, Exception) or probe != b"OK":
        raise AssertionError("needs DEBUG READ-LOCAL-LANE-CAP (--enable-debug-command yes) -> %r"
                      % (probe,))
    rep = _lib.Report("read_local_lane")

    shared = ["rl:lane:k%d" % i for i in range(DEPTH)]
    values = [b"v%d" % i for i in range(DEPTH)]
    for key, value in zip(shared, values):
        ctl.must("SET", key, value)
    # Retry only an unentered capacity/quota window, on fresh connections each time.
    # A reply, liveness or locality failure is immediately fatal; no relaxed tolerance.
    for attempt in range(3):
        conns = [_lib.Conn(host, port, timeout=ROUND_DEADLINE_S, buffering=1 << 16)
                 for _ in range(CONNS)]
        for i, c in enumerate(conns):
            c.must("SET", "rl:lane:own:%d" % i, b"init")
            assert c.cmd("GET", shared[0]) == values[0]  # drain setup writes before clean witness
        phases = []
        for phase, cap in enumerate((0, CAP, 0)):
            ctl.must("DEBUG", "READ-LOCAL-LANE-CAP", str(cap))
            if phase == 2:
                base = settle_reset_lane(ctl, conns, shared, values)
            else:
                base = counters(ctl)
            ok, detail, slow, reads = drive(conns, shared, values, 0, ROUNDS, mixed=False)
            now = counters(ctl)
            d = {k: now[k] - base[k] for k in COUNTERS}
            if not ok or slow >= ROUND_DEADLINE_S:
                raise AssertionError("clean order/liveness at cap %d: %s (%.3fs)" % (cap, detail, slow))
            if d["read_local_hits"] != reads or d["read_local_fallbacks"] != 0:
                raise AssertionError("clean GETs must all complete locally at cap %d: %r / %d"
                                     % (cap, d, reads))
            phases.append(d)
        control, capped, restored = phases
        if (capped["read_local_defer_lane_full"] > control["read_local_defer_lane_full"]
                and capped["read_local_defer_quota"] > 0):
            break
        for c in conns:
            c.close()
    else:
        raise AssertionError("capacity/quota window never opened after 3 fresh arms: %r" % phases)

    rep.check("removed INFO keys absent (not zero-valued)", True, ", ".join(REMOVED_KEYS))
    rep.check("clean GETs: exact local completions, zero fallbacks, ordered replies and liveness",
              True, "%d reads in each of control/cap/reset" % reads)
    rep.check("the CAP fired: capped deferrals > uncapped, fair-share quota > 0", True,
              "control=%r capped=%r" % (control, capped))
    restored_pressure = all(restored[k] == control[k] for k in DEFERRALS)
    reset_detail = "control=%r restored=%r" % (control, restored)
    if not restored_pressure:
        reset_detail = ("deferrals persist after a drained settle round: cap reset leaks state; "
                        + reset_detail)
    rep.check("cap reset restores derived-lane pressure", restored_pressure, reset_detail)

    # Independent mixed-write check: these legitimate RYOW/sequence fallbacks do not weaken
    # the exact clean-read proof above. Preserve the old shared-read floor and every reply.
    ctl.must("DEBUG", "READ-LOCAL-LANE-CAP", str(CAP))
    base = counters(ctl)
    ok, detail, slow, shared_gets = drive(conns, shared, values, 1, ROUNDS)
    now = counters(ctl)
    d = {k: now[k] - base[k] for k in COUNTERS}
    rep.check("mixed order + RYOW across deferral: every expected reply", ok, detail)
    rep.check("mixed liveness: every round completes", ok and slow < ROUND_DEADLINE_S,
              "slowest=%.3fs" % slow)
    rep.check("mixed shared GETs served locally (>= 95%%)",
              ok and d["read_local_hits"] >= 0.95 * shared_gets,
              "hits=%d of %d; fallbacks=%d" % (d["read_local_hits"], shared_gets,
                                              d["read_local_fallbacks"]))
    ctl.must("DEBUG", "READ-LOCAL-LANE-CAP", "0")
    base = counters(ctl)
    ok, detail, slow, restored_gets = drive(conns, shared, values, ROUNDS + 1, 1)
    now = counters(ctl)
    rep.check("mixed cap reset: local, ordered and live", ok and slow < ROUND_DEADLINE_S
              and now["read_local_hits"] - base["read_local_hits"] >= 0.95 * restored_gets, detail)
    for c in conns:
        c.close()
    ctl.close()
    rep.finish()


def self_test(trace):
    """Replay main's real phase/polling/verdict logic without sockets or a server.

    The synthetic drive emits seven deferrals on the first traffic after cap reset, matching the
    reported transient. Idle INFO cannot consume that traffic-triggered residue. Cap=8 produces
    pressure on every round. This proves the battery's discrimination, not server scheduling.
    Failure traces deliberately leave main's named assertion/exit 1 visible to the caller.
    """
    if trace.startswith("mget-fence"):
        return mget_fence_self_test(trace)
    from unittest.mock import patch

    if trace not in ("transient", "delayed-drain", "never-drains", "leak-full", "leak-quota"):
        raise AssertionError("unknown serverless trace: %s" % trace)
    stats = dict.fromkeys(COUNTERS, 0)
    data = {}
    clock = [0.0]
    state = {"cap": 0, "residue": False, "reset": False, "settled": False}
    late_updates = []
    drives = []
    polls = []

    class TraceConn:
        def __init__(self, host, port, timeout=30.0, **kwargs):
            self.sock = self
            self.timeout = timeout

        def gettimeout(self):
            return self.timeout

        def settimeout(self, timeout):
            self.timeout = timeout

        def cmd(self, *args):
            if args == ("CONFIG", "GET", "read-local"):
                return [b"read-local", b"1"]
            if args == ("INFO", "server"):
                return b"read_local:1\r\nread_local_active_threads:6\r\n"
            if args == ("INFO", "stats"):
                if state["settled"]:
                    if trace == "never-drains":
                        stats[DEFERRALS[0]] += 1
                    while late_updates and clock[0] >= late_updates[0]:
                        late_updates.pop(0)
                        stats[DEFERRALS[1]] += 1
                    polls.append((clock[0], tuple(stats[k] for k in DEFERRALS)))
                return "".join("%s:%d\r\n" % item for item in stats.items()).encode()
            if args[:2] == ("DEBUG", "READ-LOCAL-LANE-CAP"):
                cap = int(args[2])
                if state["cap"] and cap == 0:
                    state["residue"] = state["reset"] = True
                state["cap"] = cap
                return b"OK"
            if args[0] == "SET":
                data[args[1]] = args[2]
                return b"OK"
            if args[0] == "GET":
                stats["read_local_hits"] += 1
                return data[args[1]]
            raise AssertionError("unexpected trace command: %r" % (args,))

        must = cmd

        def close(self):
            pass

    def trace_drive(conns, shared, values, first_round, rounds, mixed=True):
        assert len(conns) == CONNS and len(shared) == len(values) == DEPTH
        drives.append((rounds, mixed))
        reads = DEPTH * len(conns) * rounds
        stats["read_local_hits"] += reads + (len(conns) * rounds if mixed else 0)
        if state["cap"]:
            for key in DEFERRALS:
                stats[key] += (DEPTH // state["cap"] - 1) * len(conns) * rounds
        elif state["residue"]:
            for key in DEFERRALS:
                stats[key] += 7
            state["residue"] = False
        if state["reset"] and not mixed:
            if trace in ("leak-full", "leak-quota"):
                stats[DEFERRALS[trace == "leak-quota"]] += rounds
            if not state["settled"]:
                state["settled"] = True
                if trace == "delayed-drain":
                    late_updates.extend([clock[0] + 0.02, clock[0] + 0.04])
        return True, "", 0.001, reads

    def sleep(seconds):
        clock[0] += seconds

    with patch.object(_lib, "Conn", TraceConn), \
            patch.object(_lib, "host_port", return_value=("serverless", 0)), \
            patch(__name__ + ".drive", trace_drive), \
            patch.object(time, "monotonic", side_effect=lambda: clock[0]), \
            patch.object(time, "sleep", side_effect=sleep):
        try:
            main()
        except SystemExit as exc:
            if exc.code != 0:
                raise
    assert drives == [(ROUNDS, False), (ROUNDS, False), (1, False),
                      (ROUNDS, False), (ROUNDS, True), (1, True)], drives
    assert len(polls) >= 2 and clock[0] >= DRAIN_QUIET_S, polls
    if trace == "delayed-drain":
        assert not late_updates and clock[0] >= 0.04 + DRAIN_QUIET_S, polls
    print("read_local_lane serverless %s PASS (one settle round; exact reset deltas)" % trace)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test(sys.argv[2] if len(sys.argv) > 2 else "transient")
    elif len(sys.argv) == 4 and sys.argv[3] == "--mget-fence":
        mget_fence()
    else:
        main()
