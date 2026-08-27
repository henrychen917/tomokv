#!/usr/bin/env python3
"""Cross-shard scan-ordering regression battery. Usage: tests/atomfix.py HOST PORT

WHAT THIS PINS DOWN
-------------------
A whole-owner walker (KEYS, exact DBSIZE, FLUSHDB) reads or clears an entire shard while naming
no keys at all. Program order against it is therefore per-OWNER, not per-key. The engine used to
express task ordering only through named keys, so a walker overlapped nothing and could run past
an older same-connection cross-shard group that was still parked on its owner -- most easily a
direct RENAME's destination task waiting for the source hop's image. The walker's bounded cursor
then swept the destination slot before the install landed, and the listing came back without a key
whose own RENAME had already answered +OK. The mirror case is a younger write installing behind a
cursor that is mid-walk, producing a listing that names a key the command before it deleted.

Both are deterministic here, not probabilistic: DEBUG ATOMIC-DIRECT-DEFER parks every direct
RENAME destination task for N extra owner passes after its source hop is ready, which is exactly
the window the walker used to exploit. Every case below also proves its mechanism FIRED -- the
`atomic_scan_order_holds` counter must advance, otherwise the case is reported as vacuous and the
battery fails even when the data happens to look right.

Boot requirement: --enable-debug-command yes (and --atomic 1 for the ordering cases; the battery
detects atomic 0 and still runs the shape, where it must also pass).
"""

import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])

# Enough distinct pairs that several land on different shards for any sane shard count, and enough
# keys that a bounded (256 slots/pass) walker needs several passes to cover an owner.
PAIRS = 96
TAG = "atomfix"


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, timeout=20):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((HOST, PORT))
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def send_raw(self, payload):
        self.sock.sendall(payload)

    def command(self, *args):
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
        if self.sock is None:
            return
        self.file.close()
        self.sock.close()
        self.sock = None


def ok(label):
    print(f"  ok   {label}", flush=True)


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")
    ok(label)


def stats(conn):
    raw = conn.command("INFO", "STATS")
    if not isinstance(raw, bytes):
        raise AssertionError(f"INFO STATS returned {raw!r}")
    out = {}
    for line in raw.decode().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key] = value
    return out


def scan_holds(conn):
    table = stats(conn)
    if "atomic_scan_order_holds" not in table:
        raise AssertionError(
            "INFO STATS has no atomic_scan_order_holds counter: this build cannot prove the "
            "ordering mechanism fired, so the battery would be vacuous")
    return int(table["atomic_scan_order_holds"])


def src(i):
    return f"{TAG}:src:{i:04d}:{'s' * 40}"


def dst(i):
    return f"{TAG}:dst:{i:04d}:{'d' * 40}"


def cleanup(conn):
    for i in range(PAIRS):
        conn.command("DEL", src(i), dst(i))


def arm_defer(conn, passes):
    reply = conn.command("DEBUG", "ATOMIC-DIRECT-DEFER", str(passes))
    if isinstance(reply, RespError):
        raise AssertionError(
            f"DEBUG ATOMIC-DIRECT-DEFER {passes} rejected ({reply}); boot the server with "
            "--enable-debug-command yes. Without the hook this battery cannot force the "
            "interleave and would be vacuous.")
    expect(reply, b"OK", f"DEBUG ATOMIC-DIRECT-DEFER {passes} accepted")


# ---------------------------------------------------------------------------------------------
# Case 1: a whole-owner walker must not overtake an older same-connection cross-shard write.
#
# One pipelined burst: N cross-shard RENAMEs, then KEYS over the destination pattern. Every RENAME
# answers +OK before the KEYS reply is read, so a destination absent from the listing is a listing
# that contradicts a reply the same connection already received.
# ---------------------------------------------------------------------------------------------
def case_walker_behind_writes(conn, armed):
    cleanup(conn)
    payload = b"".join(encode("SET", src(i), f"v{i}") for i in range(PAIRS))
    conn.send_raw(payload)
    for i in range(PAIRS):
        expect(conn.read(), b"OK", f"seed SET {i}") if i == 0 else conn.read()
    ok(f"seeded {PAIRS} source keys")

    burst = b"".join(encode("RENAME", src(i), dst(i)) for i in range(PAIRS))
    burst += encode("KEYS", f"{TAG}:dst:*")
    conn.send_raw(burst)
    for i in range(PAIRS):
        reply = conn.read()
        if reply != b"OK":
            raise AssertionError(f"RENAME {i} replied {reply!r}, wanted +OK")
    listing = conn.read()
    if not isinstance(listing, list):
        raise AssertionError(f"KEYS returned {listing!r}")
    listed = {item.decode() for item in listing}
    missing = sorted({dst(i) for i in range(PAIRS)} - listed)
    if missing:
        raise AssertionError(
            f"KEYS lost {len(missing)} RENAME destination(s) that had already replied +OK, "
            f"first {missing[0]!r} ({'armed' if armed else 'unarmed'} run)")
    ok(f"KEYS listed all {PAIRS} destinations that answered +OK")

    # Same shape through the other whole-owner reader: an exact DBSIZE must count them too.
    conn.send_raw(b"".join(encode("SET", src(i), f"w{i}") for i in range(PAIRS)) +
                  b"".join(encode("RENAME", src(i), dst(i)) for i in range(PAIRS)) +
                  encode("KEYS", f"{TAG}:*"))
    for _ in range(PAIRS * 2):
        conn.read()
    listing = conn.read()
    listed = {item.decode() for item in listing}
    missing = sorted({dst(i) for i in range(PAIRS)} - listed)
    if missing:
        raise AssertionError(f"second-round KEYS lost {len(missing)}, first {missing[0]!r}")
    ok("second round (overwrite then re-RENAME) listed every destination")


# ---------------------------------------------------------------------------------------------
# Case 2: a younger same-connection write must not land inside an older walker's listing.
#
# DEL every destination, then KEYS, then re-create them -- all in one pipelined burst. The KEYS
# sits between the two, so its listing must contain none of the destinations. A younger MSET that
# installs behind the walker's already-advanced cursor shows up as an extra key.
# ---------------------------------------------------------------------------------------------
def case_walker_ahead_of_writes(conn):
    burst = b"".join(encode("DEL", dst(i)) for i in range(PAIRS))
    burst += encode("KEYS", f"{TAG}:dst:*")
    pairs = []
    for i in range(PAIRS):
        pairs += [dst(i), f"late{i}"]
    burst += encode("MSET", *pairs)
    conn.send_raw(burst)
    for _ in range(PAIRS):
        conn.read()
    listing = conn.read()
    if not isinstance(listing, list):
        raise AssertionError(f"KEYS returned {listing!r}")
    leaked = sorted({item.decode() for item in listing} & {dst(i) for i in range(PAIRS)})
    mset = conn.read()
    expect(mset, b"OK", "trailing MSET replied")
    if leaked:
        raise AssertionError(
            f"KEYS listed {len(leaked)} key(s) that the command before it deleted and only a "
            f"LATER command re-created, first {leaked[0]!r}")
    ok("KEYS between DEL and MSET listed neither the deleted nor the not-yet-written values")


# ---------------------------------------------------------------------------------------------
# Case 3: negative control. With the hook disarmed the same shapes must still be correct, and the
# armed run must be the one that actually parks destination tasks -- otherwise case 1 proved
# nothing about the window it claims to force.
# ---------------------------------------------------------------------------------------------
def main():
    conn = Conn()
    admin = Conn()
    failures = 0
    try:
        atomic_on = True
        mode = admin.command("CONFIG", "GET", "atomic")
        if isinstance(mode, list) and len(mode) == 2:
            atomic_on = mode[1] != b"0"
        print(f"atomfix: atomic={'on' if atomic_on else 'off'}", flush=True)

        before_total = scan_holds(admin)
        ok(f"atomic_scan_order_holds baseline = {before_total}")

        arm_defer(admin, 0)
        cleanup(conn)
        unarmed_before = scan_holds(admin)
        case_walker_behind_writes(conn, armed=False)
        case_walker_ahead_of_writes(conn)
        unarmed_holds = scan_holds(admin) - unarmed_before
        ok(f"unarmed control passed, holds fired {unarmed_holds}x")

        arm_defer(admin, 64)
        cleanup(conn)
        armed_before = scan_holds(admin)
        case_walker_behind_writes(conn, armed=True)
        case_walker_ahead_of_writes(conn)
        armed_holds = scan_holds(admin) - armed_before

        # VACUOUS-VALIDATION GATE. Correct data with a gate that never opened proves nothing: if
        # the hook parked no destination task, the run never entered the window this test exists
        # to close, and it must be reported as a failure rather than a pass.
        if atomic_on and armed_holds == 0:
            raise AssertionError(
                "the armed run recorded 0 atomic_scan_order_holds: the ordering gate never "
                "opened, so the pass is vacuous (check --atomic 1 and that the RENAMEs are "
                "cross-shard)")
        ok(f"armed run forced the interleave, holds fired {armed_holds}x")
        if atomic_on and armed_holds <= unarmed_holds:
            print(f"  note armed holds {armed_holds} did not exceed unarmed {unarmed_holds}; the "
                  "window was already open naturally", flush=True)
    except AssertionError as failure:
        failures += 1
        print(f"  FAIL {failure}", flush=True)
    finally:
        try:
            admin.command("DEBUG", "ATOMIC-DIRECT-DEFER", "0")
            cleanup(conn)
        except (EOFError, OSError, AssertionError):
            pass
        conn.close()
        admin.close()

    print(f"atomfix: {'PASS' if not failures else 'FAIL'}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
