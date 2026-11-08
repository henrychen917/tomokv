#!/usr/bin/env python3
"""Same-connection torn-read probe for atomic multi-key writes.

Target: TomoKV atomic mode (group-scoped MVCC) versus Redis 7.4 as the control.

WRITERS  Writer W loops `MSET a "W:n" b "W:n"` (or `MULTI; SET a "W:n"; SET b "W:n"; EXEC`) with n
         increasing by one per command, --writer-pipeline commands per write.
READERS  Loop over key groups {a, b}. One burst issues the pair GET a, GET b (the order alternates
         per burst by default) --depth times:
           pipe   all pairs of the burst in ONE write (the pairs share one IO parse pass)
           split  per pair, two writes back to back without waiting for the first reply
           seq    strict round trips (send GET, read the reply, send the next GET); the control
NOISE    --lag-noise N   processes keep the owner of the "a" keys busy (LPOS over a long list,
                         or pipelined SETs), so a pipelined GET a tends to execute after GET b.
         --mget-noise N  processes loop MGET over every group key. MGET registers a snapshot,
                         so these move the MVCC reclamation floor; they also check that each
                         MGET is itself untorn.
         --read-delay-us N  TomoKV only: DEBUG ATOMIC-READ-DELAY N (needs
                         --enable-debug-command yes). It holds each plain read on its owner for
                         N us before the owner samples its cleanup cutoff.

ORACLE (Redis semantics). One connection's commands take effect in program order and each write
command is atomic, so the values one connection reads from one group, in reply order, must be
explainable by ONE serial order of the writes. The sound check kept per (connection, group):
  * per writer, observed n never decreases (one writer's commands are serial);
  * once a different value was observed, an earlier writer's latest value never reappears.
With one writer per group this reduces to "values never go backwards". A violation between the
two GETs of one pair is reported as TORN-PAIR: e.g. GET a -> W:n and then GET b -> W:m with m < n,
which is a torn view of one atomic MSET. A violation across pairs or bursts is SESSION-BACKWARDS.

Geometry: on TomoKV with --enable-debug-command yes, DEBUG SHARDS proves that every "a" key and
every "b" key live on two different owner threads. Without DEBUG (Redis) keys are plain names.

Exit status: 0 clean and non-vacuous, 1 violations found, 2 vacuous run or setup error.
"""

import argparse
import atexit
import json
import multiprocessing as mp
import socket
import sys
import time

# ------------------------------------------------------------------------------------------------
# RESP
# ------------------------------------------------------------------------------------------------


class RespError(Exception):
    pass


def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, int):
            a = b"%d" % a
        elif isinstance(a, str):
            a = a.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


class Conn:
    def __init__(self, host, port, timeout=60.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = bytearray()
        self.pos = 0

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, data):
        self.sock.sendall(data)

    def _fill(self):
        if self.pos > 65536:
            del self.buf[:self.pos]
            self.pos = 0
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise EOFError("server closed the connection")
        self.buf += chunk

    def _line(self):
        while True:
            idx = self.buf.find(b"\r\n", self.pos)
            if idx >= 0:
                line = bytes(self.buf[self.pos:idx])
                self.pos = idx + 2
                return line
            self._fill()

    def _exact(self, n):
        while len(self.buf) - self.pos < n:
            self._fill()
        data = bytes(self.buf[self.pos:self.pos + n])
        self.pos += n
        return data

    def reply(self):
        line = self._line()
        kind = line[:1]
        if kind == b"$":
            n = int(line[1:])
            if n < 0:
                return None
            return self._exact(n + 2)[:-2]
        if kind == b"+":
            return line[1:]
        if kind == b":":
            return int(line[1:])
        if kind == b"-":
            return RespError(line[1:].decode(errors="replace"))
        if kind == b"*":
            n = int(line[1:])
            if n < 0:
                return None
            return [self.reply() for _ in range(n)]
        if kind == b"_":
            return None
        raise AssertionError("unexpected RESP marker %r" % (line[:16],))

    def call(self, *args):
        self.send(enc(*args))
        return self.reply()


# ------------------------------------------------------------------------------------------------
# Oracle
# ------------------------------------------------------------------------------------------------


class Tracker:
    """Per (connection, group) serial-order check over the values read, in reply order."""

    __slots__ = ("maxseq", "superseded", "last", "changes")

    def __init__(self):
        self.maxseq = {}
        self.superseded = set()
        self.last = None
        self.changes = 0

    def observe(self, raw):
        """None if consistent, else a short reason."""
        if raw is None:
            return "missing-value"
        if raw == self.last:
            return None
        try:
            writer, seq = raw.rsplit(b":", 1)
            seq = int(seq)
        except ValueError:
            return "unparsable-value"
        known = self.maxseq.get(writer)
        bad = None
        if known is not None:
            if seq < known:
                bad = "older-than-seen"
            elif seq == known and writer in self.superseded:
                bad = "resurrected"
        if known is None or seq > known:
            self.maxseq[writer] = seq
            self.superseded.discard(writer)
        for other in self.maxseq:
            if other != writer:
                self.superseded.add(other)
        if self.last is not None:
            self.changes += 1
        self.last = raw
        return bad

    def snapshot(self):
        return {k.decode(): v for k, v in self.maxseq.items()}


# ------------------------------------------------------------------------------------------------
# Worker processes
# ------------------------------------------------------------------------------------------------

# Per-process counter slots in one shared RawArray.
F_OPS, F_VIOL, F_TORN, F_BURSTS, F_CHANGES, F_ERR, NF = range(7)


def _bump(counters, slot, field, value=1):
    counters[slot * NF + field] += value


def writer_proc(slot, wid, cfg, group, stop, counters, events):
    conn = None
    try:
        conn = Conn(cfg["host"], cfg["port"])
        a, b = group
        wtag = b"w%d" % wid
        seq = 0
        depth = cfg["writer_pipeline"]
        exec_kind = cfg["writer_kind"] == "exec"
        while not stop.is_set():
            parts = []
            for _ in range(depth):
                seq += 1
                v = b"%s:%d" % (wtag, seq)
                if exec_kind:
                    parts.append(enc(b"MULTI") + enc(b"SET", a, v) + enc(b"SET", b, v) +
                                 enc(b"EXEC"))
                else:
                    parts.append(enc(b"MSET", a, v, b, v))
            conn.send(b"".join(parts))
            for _ in range(depth):
                if exec_kind:
                    r = [conn.reply() for _ in range(4)]
                    ok = (r[0] == b"OK" and r[1] == b"QUEUED" and r[2] == b"QUEUED" and
                          isinstance(r[3], list) and len(r[3]) == 2)
                else:
                    r = conn.reply()
                    ok = r == b"OK"
                if not ok:
                    _bump(counters, slot, F_ERR)
                    events.put(("error", "writer %d unexpected reply %r" % (wid, r)))
                    stop.set()
                    return
            _bump(counters, slot, F_OPS, depth)
            _bump(counters, slot, F_BURSTS)
    except Exception as exc:  # noqa: BLE001 - report every worker failure to the parent
        _bump(counters, slot, F_ERR)
        events.put(("error", "writer %d: %r" % (wid, exc)))
        stop.set()
    finally:
        if conn:
            conn.close()


def reader_proc(slot, rid, cfg, groups, stop, counters, events):
    conn = None
    try:
        conn = Conn(cfg["host"], cfg["port"])
        mode = cfg["read_mode"]
        depth = cfg["depth"]
        order_cfg = cfg["order"]
        trackers = [Tracker() for _ in groups]
        reported = 0
        burst = 0
        t0 = cfg["t0"]
        while not stop.is_set():
            gi = burst % len(groups)
            a, b = groups[gi]
            # Alternate the order per full sweep over the groups, so every group is read both
            # a-first and b-first (the a and b keys sit on two different owners).
            if order_cfg == "ab" or (order_cfg == "alt" and (burst // len(groups)) % 2 == 0):
                first, second = a, b
            else:
                first, second = b, a
            pair = enc(b"GET", first) + enc(b"GET", second)
            if mode == "pipe":
                conn.send(pair * depth)
                values = [conn.reply() for _ in range(2 * depth)]
            elif mode == "split":
                g1, g2 = enc(b"GET", first), enc(b"GET", second)
                values = []
                for _ in range(depth):
                    conn.send(g1)
                    conn.send(g2)
                    values.append(conn.reply())
                    values.append(conn.reply())
            else:  # seq
                g1, g2 = enc(b"GET", first), enc(b"GET", second)
                values = []
                for _ in range(depth):
                    conn.send(g1)
                    values.append(conn.reply())
                    conn.send(g2)
                    values.append(conn.reply())
            tracker = trackers[gi]
            before = tracker.snapshot() if reported < 20 else None
            changes_before = tracker.changes
            for idx, raw in enumerate(values):
                if isinstance(raw, RespError):
                    _bump(counters, slot, F_ERR)
                    events.put(("error", "reader %d error reply %s" % (rid, raw)))
                    stop.set()
                    return
                why = tracker.observe(raw)
                if why is None:
                    continue
                if why in ("missing-value", "unparsable-value"):
                    _bump(counters, slot, F_ERR)
                    events.put(("error", "reader %d %s %r" % (rid, why, raw)))
                    continue
                torn = (idx % 2) == 1
                _bump(counters, slot, F_VIOL)
                if torn:
                    _bump(counters, slot, F_TORN)
                if reported < 20:
                    reported += 1
                    events.put(("violation", {
                        "t": round(time.time() - t0, 3),
                        "reader": rid,
                        "mode": mode,
                        "group": gi,
                        "burst": burst,
                        "kind": "TORN-PAIR" if torn else "SESSION-BACKWARDS",
                        "reason": why,
                        "index": idx,
                        "order": [first.decode(), second.decode()],
                        "replies": [v.decode() if isinstance(v, bytes) else v for v in values],
                        "tracker_before_burst": before,
                    }))
            _bump(counters, slot, F_CHANGES, tracker.changes - changes_before)
            _bump(counters, slot, F_OPS, depth)
            _bump(counters, slot, F_BURSTS)
            burst += 1
    except Exception as exc:  # noqa: BLE001
        _bump(counters, slot, F_ERR)
        events.put(("error", "reader %d: %r" % (rid, exc)))
        stop.set()
    finally:
        if conn:
            conn.close()


def mget_noise_proc(slot, nid, cfg, groups, stop, counters, events):
    conn = None
    try:
        conn = Conn(cfg["host"], cfg["port"])
        keys = [k for g in groups for k in g]
        cmd = enc(b"MGET", *keys) * cfg["mget_pipeline"]
        trackers = [Tracker() for _ in groups]
        reported = 0
        t0 = cfg["t0"]
        while not stop.is_set():
            conn.send(cmd)
            for _ in range(cfg["mget_pipeline"]):
                values = conn.reply()
                if not isinstance(values, list) or len(values) != len(keys):
                    _bump(counters, slot, F_ERR)
                    events.put(("error", "mget noise %d bad reply %r" % (nid, values)))
                    stop.set()
                    return
                for gi in range(len(groups)):
                    va, vb = values[2 * gi], values[2 * gi + 1]
                    torn = va != vb
                    w1 = trackers[gi].observe(va)
                    w2 = trackers[gi].observe(vb)
                    bad_value = [w for w in (w1, w2)
                                 if w in ("missing-value", "unparsable-value")]
                    if bad_value:
                        _bump(counters, slot, F_ERR)
                        events.put(("error", "mget noise %d %s %r %r" % (nid, bad_value[0],
                                                                         va, vb)))
                        continue
                    if torn or w1 is not None or w2 is not None:
                        _bump(counters, slot, F_VIOL)
                        if torn:
                            _bump(counters, slot, F_TORN)
                        if reported < 10:
                            reported += 1
                            events.put(("violation", {
                                "t": round(time.time() - t0, 3),
                                "reader": "mget%d" % nid,
                                "mode": "mget",
                                "group": gi,
                                "kind": "TORN-MGET" if torn else "MGET-SESSION-BACKWARDS",
                                "reason": w1 or w2 or "values differ inside one MGET",
                                "replies": [va.decode() if va else va, vb.decode() if vb else vb],
                            }))
                _bump(counters, slot, F_OPS)
            _bump(counters, slot, F_BURSTS)
    except Exception as exc:  # noqa: BLE001
        _bump(counters, slot, F_ERR)
        events.put(("error", "mget noise %d: %r" % (nid, exc)))
        stop.set()
    finally:
        if conn:
            conn.close()


def lag_noise_proc(slot, nid, cfg, noise, stop, counters, events):
    conn = None
    try:
        conn = Conn(cfg["host"], cfg["port"])
        if noise["kind"] == "lpos":
            cmd = enc(b"LPOS", noise["list"], b"absent-element") * cfg["lag_pipeline"]
        else:
            payload = b"x" * 256
            cmd = b"".join(enc(b"SET", k, payload) for k in noise["keys"])
        n_replies = cfg["lag_pipeline"] if noise["kind"] == "lpos" else len(noise["keys"])
        while not stop.is_set():
            conn.send(cmd)
            for _ in range(n_replies):
                r = conn.reply()
                if isinstance(r, RespError):
                    _bump(counters, slot, F_ERR)
                    events.put(("error", "lag noise %d error %s" % (nid, r)))
                    stop.set()
                    return
            _bump(counters, slot, F_OPS, n_replies)
            _bump(counters, slot, F_BURSTS)
    except Exception as exc:  # noqa: BLE001
        _bump(counters, slot, F_ERR)
        events.put(("error", "lag noise %d: %r" % (nid, exc)))
        stop.set()
    finally:
        if conn:
            conn.close()


# ------------------------------------------------------------------------------------------------
# Setup helpers
# ------------------------------------------------------------------------------------------------


def info_fields(conn):
    raw = None
    for args in ((b"INFO", b"everything"), (b"INFO", b"all"), (b"INFO",)):
        raw = conn.call(*args)
        if isinstance(raw, bytes):
            break
    out = {}
    if isinstance(raw, bytes):
        for line in raw.decode(errors="replace").splitlines():
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def debug_shards(conn, keys):
    rows = []
    for i in range(0, len(keys), 256):
        chunk = keys[i:i + 256]
        r = conn.call(b"DEBUG", b"SHARDS", *chunk)
        if not isinstance(r, list) or len(r) != len(chunk):
            return None
        for row in r:
            if not (isinstance(row, list) and len(row) == 2 and
                    all(isinstance(x, int) for x in row)):
                return None
            rows.append((row[0], row[1]))
    return rows


def choose_geometry(admin, args, prefix):
    """Groups of (a, b) with every a on owner X and every b on owner Y (X != Y), proven by
    DEBUG SHARDS when available. Also noise keys on owner X."""
    need_noise = 64
    cand = [("tt:%s:%05d" % (prefix, i)).encode() for i in range(4096)]
    rows = None
    if args.geometry in ("auto", "debug"):
        rows = debug_shards(admin, cand)
        if rows is None and args.geometry == "debug":
            raise SystemExit("DEBUG SHARDS unavailable but --geometry debug was requested")
    if rows is None:
        groups = [(("tt:%s:g%d:a" % (prefix, g)).encode(), ("tt:%s:g%d:b" % (prefix, g)).encode())
                  for g in range(args.groups)]
        noise = {"list": ("tt:%s:noise:list" % prefix).encode(),
                 "keys": [("tt:%s:noise:%d" % (prefix, i)).encode() for i in range(need_noise)]}
        return groups, noise, {"proven": False, "note": "DEBUG SHARDS unavailable; owners unproven"}
    by_owner = {}
    placement = {}
    for key, (sid, owner) in zip(cand, rows):
        by_owner.setdefault(owner, []).append(key)
        placement[key] = (sid, owner)
    owners = sorted(by_owner, key=lambda o: -len(by_owner[o]))
    if len(owners) < 2:
        raise SystemExit("geometry: only one owner thread holds shards (%r); need two" % owners)
    x, y = owners[0], owners[1]
    if len(by_owner[x]) < args.groups + need_noise + 1 or len(by_owner[y]) < args.groups:
        raise SystemExit("geometry: not enough candidate keys on owners %d/%d" % (x, y))
    a_keys = by_owner[x][:args.groups]
    b_keys = by_owner[y][:args.groups]
    noise_list = by_owner[x][args.groups]
    noise_keys = by_owner[x][args.groups + 1:args.groups + 1 + need_noise]
    groups = list(zip(a_keys, b_keys))
    geo = {
        "proven": True,
        "owner_a": x,
        "owner_b": y,
        "owners_seen": sorted(by_owner),
        "groups": [{"a": a.decode(), "a_shard": placement[a][0], "a_owner": placement[a][1],
                    "b": b.decode(), "b_shard": placement[b][0], "b_owner": placement[b][1]}
                   for a, b in groups],
        "noise_list": noise_list.decode(),
    }
    return groups, {"list": noise_list, "keys": noise_keys}, geo


def recheck_geometry(admin, geo, groups):
    if not geo.get("proven"):
        return True
    keys = [k for g in groups for k in g]
    rows = debug_shards(admin, keys)
    if rows is None:
        return False
    for i, (a, b) in enumerate(groups):
        if rows[2 * i][1] != geo["owner_a"] or rows[2 * i + 1][1] != geo["owner_b"]:
            return False
    return True


# ------------------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--label", default="arm")
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--max-violations", type=int, default=3)
    p.add_argument("--writers", type=int, default=2)
    p.add_argument("--groups", type=int, default=2)
    p.add_argument("--readers", type=int, default=6)
    p.add_argument("--read-mode", choices=("pipe", "split", "seq"), default="pipe")
    p.add_argument("--depth", type=int, default=8, help="GET pairs per burst")
    p.add_argument("--order", choices=("ab", "ba", "alt"), default="alt")
    p.add_argument("--writer-kind", choices=("mset", "exec"), default="mset")
    p.add_argument("--writer-pipeline", type=int, default=16)
    p.add_argument("--lag-noise", type=int, default=0)
    p.add_argument("--lag-kind", choices=("lpos", "set"), default="lpos")
    p.add_argument("--lag-list-len", type=int, default=5000)
    p.add_argument("--lag-pipeline", type=int, default=4)
    p.add_argument("--mget-noise", type=int, default=0)
    p.add_argument("--mget-pipeline", type=int, default=4)
    p.add_argument("--read-delay-us", type=int, default=0,
                   help="TomoKV: DEBUG ATOMIC-READ-DELAY for the run, reset to 0 afterwards")
    p.add_argument("--geometry", choices=("auto", "debug", "none"), default="auto")
    p.add_argument("--require-atomic", type=int, choices=(0, 1), default=None,
                   help="fail setup unless CONFIG GET atomic returns this (TomoKV)")
    p.add_argument("--require-mode", choices=("1s", "2s"))
    p.add_argument("--require-read-local", type=int, choices=(0, 1))
    p.add_argument("--require-reorder", type=int, choices=(0, 1))
    p.add_argument("--json", default=None, help="write the summary JSON here")
    p.add_argument("--progress", type=float, default=10.0)
    args = p.parse_args()

    ctx = mp.get_context("fork")
    admin = Conn(args.host, args.port)
    server = info_fields(admin)
    product = "tomokv" if any(k.startswith("atomic_") for k in server) else "redis"
    version = server.get("redis_version", "?")
    atomic_reply = admin.call(b"CONFIG", b"GET", b"atomic")
    atomic = None
    if isinstance(atomic_reply, list) and len(atomic_reply) == 2:
        atomic = atomic_reply[1].decode()
    if args.require_atomic is not None and atomic != str(args.require_atomic):
        print("SETUP FAIL: CONFIG GET atomic = %r, required %d" % (atomic, args.require_atomic))
        return 2
    effective = {}
    if product == "tomokv":
        for key, required in (("thread-mode", args.require_mode),
                              ("read-local", args.require_read_local),
                              ("reorder", args.require_reorder)):
            reply = admin.call("CONFIG", "GET", key)
            value = reply[1].decode() if isinstance(reply, list) and len(reply) == 2 else None
            effective[key] = value
            if required is not None and value != str(required):
                print("SETUP FAIL: CONFIG GET %s = %r, required %s" % (key, value, required))
                return 2
    prefix = "%s:%d" % (args.label, time.time_ns())
    groups, noise, geo = choose_geometry(admin, args, prefix)

    # Seed every group atomically so readers never see a missing key.
    for a, b in groups:
        r = admin.call(b"MSET", a, b"init:0", b, b"init:0")
        if r != b"OK":
            print("SETUP FAIL: seed MSET replied %r" % (r,))
            return 2
    noise["kind"] = args.lag_kind
    if args.lag_noise:
        if args.lag_kind == "lpos":
            admin.call(b"DEL", noise["list"])
            pushed = 0
            while pushed < args.lag_list_len:
                n = min(1000, args.lag_list_len - pushed)
                r = admin.call(b"RPUSH", noise["list"],
                               *[b"e%07d" % (pushed + i) for i in range(n)])
                if isinstance(r, RespError):
                    print("SETUP FAIL: RPUSH noise list: %s" % r)
                    return 2
                pushed += n
            probe = admin.call(b"LPOS", noise["list"], b"absent-element")
            if isinstance(probe, RespError):
                print("note: LPOS unavailable (%s); falling back to SET lag noise" % probe)
                noise["kind"] = "set"

    delay_armed = False
    if args.read_delay_us:
        r = admin.call(b"DEBUG", b"ATOMIC-READ-DELAY", args.read_delay_us)
        if r != b"OK":
            print("SETUP FAIL: DEBUG ATOMIC-READ-DELAY %d replied %r" %
                  (args.read_delay_us, r))
            return 2
        delay_armed = True

        def _disarm():  # also runs if this process dies on an unhandled exception
            try:
                c = Conn(args.host, args.port, timeout=5)
                c.call(b"DEBUG", b"ATOMIC-READ-DELAY", 0)
                c.close()
            except Exception:  # noqa: BLE001
                pass

        atexit.register(_disarm)

    before = info_fields(admin) if product == "tomokv" else {}
    print("=" * 100)
    print("ARM %s  server=%s %s atomic=%s  port=%d" % (args.label, product, version, atomic,
                                                      args.port))
    if effective:
        print("    effective configuration: %s" % json.dumps(effective, sort_keys=True))
    print("    read-mode=%s depth=%d order=%s readers=%d writers=%d (%s, pipeline %d) groups=%d "
          "lag-noise=%d(%s) mget-noise=%d read-delay-us=%d seconds=%.0f max-violations=%d" %
          (args.read_mode, args.depth, args.order, args.readers, args.writers, args.writer_kind,
           args.writer_pipeline, len(groups), args.lag_noise, noise["kind"], args.mget_noise,
           args.read_delay_us, args.seconds, args.max_violations))
    if geo.get("proven"):
        print("    geometry PROVEN by DEBUG SHARDS: a-keys on owner %d, b-keys on owner %d "
              "(owners seen %s)" % (geo["owner_a"], geo["owner_b"], geo["owners_seen"]))
        for g in geo["groups"]:
            print("      %s (shard %d, owner %d)   %s (shard %d, owner %d)" %
                  (g["a"], g["a_shard"], g["a_owner"], g["b"], g["b_shard"], g["b_owner"]))
    else:
        print("    geometry: %s" % geo.get("note"))

    t0 = time.time()
    cfg = {
        "host": args.host, "port": args.port, "read_mode": args.read_mode, "depth": args.depth,
        "order": args.order, "writer_kind": args.writer_kind,
        "writer_pipeline": args.writer_pipeline, "mget_pipeline": args.mget_pipeline,
        "lag_pipeline": args.lag_pipeline, "t0": t0,
    }
    roles = []
    for w in range(args.writers):
        roles.append(("writer", w))
    for r in range(args.readers):
        roles.append(("reader", r))
    for n in range(args.mget_noise):
        roles.append(("mget", n))
    for n in range(args.lag_noise):
        roles.append(("lag", n))
    counters = ctx.RawArray("q", len(roles) * NF)
    stop = ctx.Event()
    events = ctx.Queue()
    procs = []
    for slot, (role, idx) in enumerate(roles):
        if role == "writer":
            target, extra = writer_proc, (idx, cfg, groups[idx % len(groups)])
        elif role == "reader":
            target, extra = reader_proc, (idx, cfg, groups)
        elif role == "mget":
            target, extra = mget_noise_proc, (idx, cfg, groups)
        else:
            target, extra = lag_noise_proc, (idx, cfg, noise)
        proc = ctx.Process(target=target, args=(slot,) + extra + (stop, counters, events),
                           daemon=True)
        procs.append(proc)
    for proc in procs:
        proc.start()

    def total(role_name, field):
        return sum(counters[s * NF + field] for s, (role, _) in enumerate(roles)
                   if role == role_name)

    violations, errors = [], []

    def drain_events():
        while True:
            try:
                kind, payload = events.get_nowait()
            except Exception:  # noqa: BLE001 - queue.Empty
                return
            if kind == "violation":
                violations.append(payload)
                if len(violations) <= 10:
                    print("    VIOLATION %s" % json.dumps(payload))
            else:
                errors.append(payload)
                print("    ERROR %s" % payload)

    next_progress = t0 + args.progress
    stop_reason = "duration"
    try:
        while True:
            time.sleep(0.25)
            drain_events()
            now = time.time()
            nviol = total("reader", F_VIOL) + total("mget", F_VIOL)
            if nviol >= args.max_violations:
                stop_reason = "max-violations"
                break
            if stop.is_set():
                stop_reason = "worker-stop (error)"
                break
            if now - t0 >= args.seconds:
                break
            if now >= next_progress:
                next_progress += args.progress
                el = now - t0
                print("    t=%6.1fs pairs=%d (%.0f/s) writes=%d (%.0f/s) value-changes=%d "
                      "violations=%d torn-pair=%d mget=%d" %
                      (el, total("reader", F_OPS), total("reader", F_OPS) / el,
                       total("writer", F_OPS), total("writer", F_OPS) / el,
                       total("reader", F_CHANGES), total("reader", F_VIOL),
                       total("reader", F_TORN), total("mget", F_OPS)))
                sys.stdout.flush()
    except KeyboardInterrupt:
        stop_reason = "interrupted"
    stop.set()
    for proc in procs:
        proc.join(timeout=15)
    for proc in procs:
        if proc.is_alive():
            proc.terminate()
    drain_events()
    elapsed = time.time() - t0

    if delay_armed:
        admin.call(b"DEBUG", b"ATOMIC-READ-DELAY", 0)
    after = info_fields(admin) if product == "tomokv" else {}
    geometry_stable = recheck_geometry(admin, geo, groups)
    admin.close()

    deltas = {}
    for k, v in after.items():
        if not k.startswith("atomic_") or k not in before:
            continue
        try:
            d = int(after[k]) - int(before[k])
        except ValueError:
            continue
        if d:
            deltas[k] = d

    pairs = total("reader", F_OPS)
    writes = total("writer", F_OPS)
    changes = total("reader", F_CHANGES)
    nviol = total("reader", F_VIOL)
    ntorn = total("reader", F_TORN)
    mget_viol = total("mget", F_VIOL)
    mget_torn = total("mget", F_TORN)
    nerr = sum(counters[s * NF + F_ERR] for s in range(len(roles)))
    vacuous = []
    if not pairs:
        vacuous.append("no read pairs completed")
    if not writes:
        vacuous.append("no writes completed")
    if pairs and writes and not changes:
        vacuous.append("readers never saw a value change (reads not concurrent with writes)")
    if product == "tomokv" and atomic == "1" and args.writer_kind == "mset" and \
            not deltas.get("atomic_groups"):
        vacuous.append("atomic_groups did not advance: MSET never ran as a cross-shard group")
    if not geometry_stable:
        vacuous.append("key placement changed during the run")

    summary = {
        "label": args.label, "server": product, "version": version, "atomic": atomic,
        "effective_configuration": effective,
        "port": args.port, "elapsed_s": round(elapsed, 1), "stop_reason": stop_reason,
        "read_mode": args.read_mode, "depth": args.depth, "order": args.order,
        "readers": args.readers, "writers": args.writers, "writer_kind": args.writer_kind,
        "groups": len(groups), "lag_noise": args.lag_noise, "lag_kind": noise["kind"],
        "mget_noise": args.mget_noise, "read_delay_us": args.read_delay_us,
        "geometry": geo, "geometry_stable": geometry_stable,
        "read_pairs": pairs, "writes": writes, "value_changes_seen": changes,
        "violations": nviol, "torn_pairs": ntorn,
        "session_backwards": nviol - ntorn,
        "mget_violations": mget_viol, "mget_torn": mget_torn, "errors": nerr,
        "error_samples": errors[:5], "violation_samples": violations[:10],
        "info_atomic_deltas": deltas, "vacuous": vacuous,
    }
    print("    RESULT %s: %.1fs, %d read pairs (%.0f/s), %d writes (%.0f/s), %d value changes "
          "seen; violations=%d (torn-pair %d, session-backwards %d), mget violations=%d "
          "(torn %d), errors=%d, stop=%s" %
          (args.label, elapsed, pairs, pairs / max(elapsed, 1e-9), writes,
           writes / max(elapsed, 1e-9), changes, nviol, ntorn, nviol - ntorn, mget_viol,
           mget_torn, nerr, stop_reason))
    if deltas:
        print("    INFO atomic_* deltas: %s" % json.dumps(deltas, sort_keys=True))
    if vacuous:
        print("    VACUOUS/INVALID: %s" % "; ".join(vacuous))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(summary, fh, indent=1, sort_keys=True)
    sys.stdout.flush()
    if nviol or mget_viol:
        return 1
    if vacuous or nerr:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
