#!/usr/bin/env python3
"""Script-effect durability regression battery. Usage: tests/scriptatomic.py HOST PORT

WHAT THIS PINS DOWN
-------------------
`--atomic 1` used to arm a deep undo log over a script's declared keys and restore it whenever the
activation failed (src/cmd/scripting.cc, the ScriptUndo class). Redis has never undone a script's
partial effects, so every activation that wrote and then raised diverged the moment atomics were
enabled -- and the divergence was a LOST WRITE: the restore published a superseded value over a
committed one, or erased the key outright when the script had created it. Two symptom shapes, one
cause:

    (a) a counter frozen one step behind         INCR applied, then reversed
    (b) a key absent that must exist             the script created it, the restore erased it

Both are reproduced below WITHOUT concurrency, and again WITH the cross-shard MVCC engine engaged.

WHAT MAKES THIS NON-VACUOUS
---------------------------
Every arm that must exercise the guarded path asserts that `script_failed_after_effects` advanced:
that counter only moves when an activation FAILS with at least one applied keyspace effect
standing, which is exactly the interleave the undo log used to reverse. An arm that leaves the
counter still is reported as vacuous and fails the battery even when the data happens to look
right. A read-only failure arm is the negative control: it must NOT move the counter.

The whole core is run twice, once with `atomic 0` and once with `atomic 1`, and the two runs are
required to agree observation for observation -- the mode may not change what a script leaves
behind.

The cross-shard section needs `--enable-debug-command yes` (DEBUG SHARDS to prove the group really
spans owners, ATOMIC-COMMIT-DELAY / ATOMIC-READ-DELAY to widen the window). Without it that
section is skipped outside the gate; strict gate invocations fail. The core arms still run.
"""

import socket
import sys

from _lib import strict_mode

HOST, PORT = sys.argv[1], int(sys.argv[2])
TAG = "sa"

FAIL = 0
VACUOUS = 0


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, int):
            arg = str(arg)
        if isinstance(arg, str):
            arg = arg.encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, timeout=30):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((HOST, PORT))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def pipeline(self, commands):
        self.sock.sendall(b"".join(encode(*c) for c in commands))
        return [self.read() for _ in commands]

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        prefix = self.file.read(1)
        if not prefix:
            raise EOFError("server closed the connection")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError(f"bad RESP line: {prefix + line!r}")
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
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return payload
        if prefix == b"*":
            size = int(value)
            if size == -1:
                return None
            return [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")

    def close(self):
        if self.sock is not None:
            self.file.close()
            self.sock.close()
            self.sock = None


def note(label, condition, detail=""):
    global FAIL
    if condition:
        print(f"  ok   {label}", flush=True)
    else:
        FAIL += 1
        print(f"  FAIL {label} {detail}", flush=True)


def vacuous(label, detail):
    global VACUOUS, FAIL
    VACUOUS += 1
    FAIL += 1
    print(f"  VACUOUS {label} {detail}", flush=True)


def stats(conn):
    raw = conn.cmd("INFO", "STATS")
    if not isinstance(raw, bytes):
        raise AssertionError(f"INFO STATS returned {raw!r}")
    table = {}
    for line in raw.decode().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            table[key] = value
    return table


def counter(conn, name):
    # A build without the counter cannot prove the guarded path ran. Report that as vacuity where
    # the assertion is made rather than aborting here, so the data arms still produce a verdict --
    # that is what makes a HEAD-vs-fix comparison readable.
    table = stats(conn)
    return int(table[name]) if name in table else None


def delta(after, before):
    return None if after is None or before is None else after - before


def error_text(reply):
    return reply.args[0] if isinstance(reply, RespError) else None


# ---------------------------------------------------------------------------------------------
# Core: an activation that fails keeps every effect it already applied, in BOTH atomic modes.
# ---------------------------------------------------------------------------------------------

WRITE_THEN_RAISE = "redis.call('INCR', KEYS[1]) error('boom')"
CREATE_THEN_RAISE = "redis.call('SET', KEYS[1], 'made') error('boom')"
APPEND_THEN_GLOBAL = "redis.call('APPEND', KEYS[1], 'XY') return nosuchglobal"
DEL_THEN_RAISE = "redis.call('DEL', KEYS[1]) error('boom')"
WRITE_THEN_WRONGTYPE = "redis.call('INCR', KEYS[1]) return redis.call('LPUSH', KEYS[1], 'x')"
WRITE_THEN_RUNAWAY = "redis.call('INCR', KEYS[1]) while true do end"
WRITE_THEN_BAD_REPLY = "redis.call('INCR', KEYS[1]) return 1/0"
PCALL_INDEX_NUMBER = ("local r = redis.pcall('INCR', KEYS[1]) "
                      "if r.err then return r.err end return r")
RO_WRITE = "return redis.call('SET', KEYS[1], 'ro')"
READ_THEN_RAISE = "redis.call('GET', KEYS[1]) error('boom')"


def core_pass(conn, mode, keys):
    """Every observation this returns must be identical for mode 0 and mode 1."""
    observed = {}
    before_failed = counter(conn, "script_failed_after_effects")
    before_writes = counter(conn, "script_effect_writes")

    k = keys["single"]

    # (a) a counter one step behind: the classic shape from the differ.
    conn.cmd("SET", k, "5")
    observed["a_error"] = "boom" in (error_text(conn.cmd("EVAL", WRITE_THEN_RAISE, 1, k)) or "")
    observed["a_value"] = conn.cmd("GET", k)

    # (b) the key must exist: the script created it, so a restore that erases it is data loss.
    conn.cmd("DEL", k)
    observed["b_error"] = "boom" in (error_text(conn.cmd("EVAL", CREATE_THEN_RAISE, 1, k)) or "")
    observed["b_exists"] = conn.cmd("EXISTS", k)
    observed["b_value"] = conn.cmd("GET", k)

    # A raised *runtime* error rather than error(): the globals guard.
    conn.cmd("SET", k, "abc")
    observed["c_error"] = "nosuchglobal" in (error_text(conn.cmd("EVAL", APPEND_THEN_GLOBAL, 1, k)) or "")
    observed["c_value"] = conn.cmd("GET", k)

    # A delete is an effect too: the key must stay gone.
    conn.cmd("SET", k, "doomed")
    observed["d_error"] = "boom" in (error_text(conn.cmd("EVAL", DEL_THEN_RAISE, 1, k)) or "")
    observed["d_exists"] = conn.cmd("EXISTS", k)

    # A nested command error (WRONGTYPE) unwinds the activation; the INCR before it still stands.
    conn.cmd("SET", k, "7")
    observed["e_error"] = "WRONGTYPE" in (error_text(conn.cmd("EVAL", WRITE_THEN_WRONGTYPE, 1, k)) or "")
    observed["e_value"] = conn.cmd("GET", k)

    # The reply converter rejecting the result is a failure arm of its own.
    conn.cmd("SET", k, "10")
    observed["f_error"] = error_text(conn.cmd("EVAL", WRITE_THEN_BAD_REPLY, 1, k)) is not None
    observed["f_value"] = conn.cmd("GET", k)

    # The instruction-limit abort: BUSY, and the write before the runaway loop stands.
    conn.cmd("SET", k, "20")
    busy = error_text(conn.cmd("EVAL", WRITE_THEN_RUNAWAY, 1, k)) or ""
    observed["g_busy"] = busy.startswith("BUSY ")
    observed["g_value"] = conn.cmd("GET", k)
    observed["g_alive"] = conn.cmd("PING")

    # The exact differ shape: a script whose own reply-handling raises after a successful pcall.
    conn.cmd("SET", k, "-3")
    observed["h_error"] = error_text(conn.cmd("EVAL", PCALL_INDEX_NUMBER, 1, k)) is not None
    observed["h_value"] = conn.cmd("GET", k)

    # Two declared keys on ONE owner: both effects stand.
    k1, k2 = keys["same_owner"]
    conn.cmd("MSET", k1, "1", k2, "1")
    two = "redis.call('INCR', KEYS[1]) redis.call('INCR', KEYS[2]) error('boom')"
    observed["i_error"] = "boom" in (error_text(conn.cmd("EVAL", two, 2, k1, k2)) or "")
    observed["i_values"] = conn.cmd("MGET", k1, k2)

    # A read-only activation whose write is REFUSED must leave the committed value alone, and the
    # refusal is not an "effect" -- this is the negative control for the counter.
    conn.cmd("SET", k, "41")
    failed_before_ro = counter(conn, "script_failed_after_effects")
    ro = conn.pipeline([["EVAL", "return redis.call('INCR', KEYS[1])", "1", k],
                        ["EVAL_RO", RO_WRITE, "1", k],
                        ["GET", k]])
    observed["j_incr"] = ro[0]
    observed["j_refused"] = "read-only" in (error_text(ro[1]) or "")
    observed["j_value"] = ro[2]
    observed["j_value_fresh"] = conn.cmd("GET", k)
    after_ro = counter(conn, "script_failed_after_effects")
    observed["j_no_effect_counted"] = (
        after_ro is not None and failed_before_ro is not None and after_ro == failed_before_ro)

    # A failing activation that only READ is the second negative control.
    conn.cmd("SET", k, "reader")
    failed_before_read = counter(conn, "script_failed_after_effects")
    observed["k_error"] = "boom" in (error_text(conn.cmd("EVAL", READ_THEN_RAISE, 1, k)) or "")
    after_read = counter(conn, "script_failed_after_effects")
    observed["k_no_effect_counted"] = (
        after_read is not None and failed_before_read is not None and
        after_read == failed_before_read)

    # Control: a successful activation still commits normally.
    conn.cmd("SET", k, "1")
    observed["l_reply"] = conn.cmd("EVAL", "return redis.call('INCR', KEYS[1])", 1, k)
    observed["l_value"] = conn.cmd("GET", k)

    observed["_failed_delta"] = delta(
        counter(conn, "script_failed_after_effects"), before_failed)
    observed["_writes_delta"] = delta(counter(conn, "script_effect_writes"), before_writes)
    print(f"  -- atomic {mode}: failed_after_effects +{observed['_failed_delta']}, "
          f"effect_writes +{observed['_writes_delta']}", flush=True)
    return observed


def check_core(observed, mode):
    m = f"(atomic {mode})"
    note(f"write-then-raise keeps the increment {m}",
         observed["a_error"] and observed["a_value"] == b"6", repr(observed["a_value"]))
    note(f"create-then-raise keeps the key {m}",
         observed["b_error"] and observed["b_exists"] == 1 and observed["b_value"] == b"made",
         f"{observed['b_exists']!r} {observed['b_value']!r}")
    note(f"append-then-runtime-error keeps the append {m}",
         observed["c_error"] and observed["c_value"] == b"abcXY", repr(observed["c_value"]))
    note(f"delete-then-raise keeps the key deleted {m}",
         observed["d_error"] and observed["d_exists"] == 0, repr(observed["d_exists"]))
    note(f"nested WRONGTYPE keeps the earlier increment {m}",
         observed["e_error"] and observed["e_value"] == b"8", repr(observed["e_value"]))
    note(f"reply-conversion failure keeps the increment {m}",
         observed["f_error"] and observed["f_value"] == b"11", repr(observed["f_value"]))
    note(f"instruction-limit abort keeps the increment {m}",
         observed["g_busy"] and observed["g_value"] == b"21" and observed["g_alive"] == b"PONG",
         repr(observed["g_value"]))
    note(f"pcall-then-raise keeps the increment {m}",
         observed["h_error"] and observed["h_value"] == b"-2", repr(observed["h_value"]))
    note(f"two same-owner keys both keep their effect {m}",
         observed["i_error"] and observed["i_values"] == [b"2", b"2"], repr(observed["i_values"]))
    note(f"refused read-only write leaves the committed value {m}",
         observed["j_incr"] == 42 and observed["j_refused"] and
         observed["j_value"] == b"42" and observed["j_value_fresh"] == b"42",
         f"{observed['j_incr']!r} {observed['j_value']!r} {observed['j_value_fresh']!r}")
    note(f"refused write is not counted as an effect {m}", observed["j_no_effect_counted"])
    note(f"read-only failure is not counted as an effect {m}",
         observed["k_error"] and observed["k_no_effect_counted"])
    note(f"successful activation still commits {m}",
         observed["l_reply"] == 2 and observed["l_value"] == b"2", repr(observed["l_value"]))
    # The eight arms above that fail WITH an effect standing are exactly the guarded path.
    if observed["_failed_delta"] is None or observed["_failed_delta"] < 8:
        vacuous(f"guarded path did not run {m}",
                f"script_failed_after_effects advanced by {observed['_failed_delta']}, wanted >= 8")
    else:
        note(f"guarded path fired: failed_after_effects +{observed['_failed_delta']} {m}", True)
    if observed["_writes_delta"] is None or observed["_writes_delta"] < 12:
        vacuous(f"no script effects were applied at all {m}",
                f"script_effect_writes advanced by {observed['_writes_delta']}")


# ---------------------------------------------------------------------------------------------
# Cross-shard section: the same durability claim with the epoch-MVCC engine actually engaged.
# ---------------------------------------------------------------------------------------------

def shard_of(conn, key):
    reply = conn.cmd("DEBUG", "SHARD", key)
    if isinstance(reply, RespError):
        raise RespError(reply.args[0])
    return reply


def owners_of(conn, keys):
    reply = conn.cmd("DEBUG", "SHARDS", *keys)
    if isinstance(reply, RespError):
        raise reply
    if (not isinstance(reply, list) or len(reply) != len(keys) or
            any(not isinstance(row, list) or len(row) != 2 or
                any(type(value) is not int for value in row) for row in reply)):
        raise AssertionError(f"malformed DEBUG SHARDS placement: {reply!r}")
    return [row[1] for row in reply]


def find_pair(conn, want_same):
    """Use actual owner IDs, including distinct shards on the same executor."""
    anchor = f"{TAG}:pair:anchor"
    for first in range(0, 4096, 128):
        candidates = [f"{TAG}:pair:{index}" for index in range(first, first + 128)]
        owners = owners_of(conn, [anchor, *candidates])
        for candidate, owner in zip(candidates, owners[1:]):
            if (owner == owners[0]) == want_same:
                pair = (anchor, candidate)
                current = owners_of(conn, pair)
                if (current[0] == current[1]) == want_same:
                    return pair
    raise AssertionError("no stable key pair with the wanted owner relation in 4096 tries")


def unavailable(reason):
    if strict_mode():
        vacuous("cross-owner geometry unavailable under TOMO_GATE_STRICT", str(reason))
    else:
        print(f"  SKIP cross-owner section: DEBUG unavailable ({reason})", flush=True)


def arm(conn, name, value):
    reply = conn.cmd("DEBUG", name, str(value))
    if isinstance(reply, RespError):
        raise RespError(reply.args[0])
    if reply != b"OK":
        raise AssertionError(f"DEBUG {name} {value} answered {reply!r}")
    return True


def crossshard_pass(conn, mode, g1, g2, rounds=48):
    before_groups = int(stats(conn).get("atomic_groups", "0"))
    before_failed = counter(conn, "script_failed_after_effects")
    losses = []
    for round_ in range(rounds):
        base = round_ * 10
        # One pipeline: a genuine cross-shard group, a write-then-fail script on one of its keys,
        # and a cross-shard read that must see the script's effect (same-connection RYOW).
        replies = conn.pipeline([
            ["MSET", g1, str(base), g2, str(base)],
            ["EVAL", WRITE_THEN_RAISE, "1", g1],
            ["MGET", g1, g2],
            ["EVAL", CREATE_THEN_RAISE, "1", g2],
            ["MGET", g1, g2],
            ["DEL", g1, g2],
        ])
        if replies[0] != b"OK":
            losses.append((round_, "MSET", replies[0]))
        if not isinstance(replies[1], RespError):
            losses.append((round_, "script did not fail", replies[1]))
        if replies[2] != [str(base + 1).encode(), str(base).encode()]:
            losses.append((round_, "lost script INCR", replies[2]))
        if not isinstance(replies[3], RespError):
            losses.append((round_, "script did not fail", replies[3]))
        if replies[4] != [str(base + 1).encode(), b"made"]:
            losses.append((round_, "lost script SET", replies[4]))
    groups = int(stats(conn).get("atomic_groups", "0")) - before_groups
    failed = delta(counter(conn, "script_failed_after_effects"), before_failed)
    return losses, groups, failed


def run_crossshard(conn, mode):
    m = f"(atomic {mode})"
    try:
        g1, g2 = find_pair(conn, want_same=False)
    except RespError as err:
        unavailable(err)
        return None
    owners = owners_of(conn, (g1, g2))
    same_owner = owners[0] == owners[1]
    note(f"cross-shard pair really spans owners {m}", not same_owner,
         f"owner IDs {owners}")
    if same_owner:
        return None
    arm(conn, "ATOMIC-COMMIT-DELAY", 60)
    arm(conn, "ATOMIC-READ-DELAY", 60)
    try:
        losses, groups, failed = crossshard_pass(conn, mode, g1, g2)
    finally:
        arm(conn, "ATOMIC-COMMIT-DELAY", 0)
        arm(conn, "ATOMIC-READ-DELAY", 0)
    note(f"no script effect lost under a live cross-shard group {m}",
         not losses, repr(losses[:4]))
    if failed is None or failed < 48:
        vacuous(f"cross-shard section did not reach the guarded path {m}",
                f"failed_after_effects advanced by {failed}")
    else:
        note(f"cross-shard guarded path fired: failed_after_effects +{failed} {m}", True)
    return groups


# ---------------------------------------------------------------------------------------------

conn = Conn()
try:
    boot_mode = conn.cmd("CONFIG", "GET", "atomic")[1]
    keys = {"single": f"{TAG}:one"}
    try:
        keys["same_owner"] = find_pair(conn, want_same=True)
        debug_ok = True
    except RespError as exc:
        unavailable(exc)
        # Cross-owner scripts are accepted now, so acceptance no longer reveals placement. The
        # debug-armed gate below owns the same-owner and proven-cross geometry checks; an ordinary
        # boot can still cover the two-declared-key effect semantics with a fixed distinct pair.
        debug_ok = False
        anchor = f"{TAG}:pair:anchor"
        keys["same_owner"] = (anchor, f"{TAG}:pair:argument")

    results = {}
    groups_seen = {}
    for mode in (0, 1):
        if isinstance(conn.cmd("CONFIG", "SET", "atomic", str(mode)), RespError):
            raise AssertionError(f"CONFIG SET atomic {mode} rejected")
        print(f"-- atomic {mode}", flush=True)
        results[mode] = core_pass(conn, mode, keys)
        check_core(results[mode], mode)
        if debug_ok:
            groups_seen[mode] = run_crossshard(conn, mode)

    shared = [k for k in results[0] if not k.startswith("_")]
    mismatched = [k for k in shared if results[0][k] != results[1][k]]
    note("atomic 0 and atomic 1 observe the same script effects",
         not mismatched,
         "; ".join(f"{k}: {results[0][k]!r} vs {results[1][k]!r}" for k in mismatched[:4]))

    if debug_ok:
        # The engine itself must have run in mode 1 and stayed out of the way in mode 0: without
        # this the cross-shard section could pass while testing nothing about atomics.
        note("cross-shard groups fired with atomic 1",
             (groups_seen.get(1) or 0) > 0, repr(groups_seen.get(1)))
        note("cross-shard groups stayed dormant with atomic 0 (negative control)",
             (groups_seen.get(0) or 0) == 0, repr(groups_seen.get(0)))

finally:
    try:
        conn.cmd("CONFIG", "SET", "atomic", boot_mode)
        conn.cmd("DEL", keys["single"], *keys["same_owner"])
        conn.cmd("DEL", f"{TAG}:pair:anchor")
    except Exception:
        pass
    conn.close()

print(f"SCRIPTATOMIC: {FAIL} FAIL ({VACUOUS} vacuous)")
sys.exit(1 if FAIL else 0)
