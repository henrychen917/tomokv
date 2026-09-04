#!/usr/bin/env python3
"""CLIENT REPLY OFF/SKIP must suppress a cross-shard MGET reply COMPLETELY.

    tests/replyoff_xshard.py HOST PORT
    boot: --thread-mode 2s --shards 64 --zc-min 64 --atomic 1 --enable-debug-command yes

The cross-shard retire hook assembles an MGET whose values are borrowed (longer than
min(zc-min, 1024) bytes, cmd/scatter_engine.inc) straight into the connection's segment queue --
array header, borrowed bulks, CRLFs -- BEFORE the suppressing serve consults the op's skip mark.
Pre-fix only the op's TAIL was dropped: the header and the bulks reached the wire, the peer parsed
the next real reply as the array's missing element, and every later reply on the connection was
shifted by one.

Vacuity guards (a run that exercises nothing must FAIL):
  - zero-copy is enabled on this boot (CONFIG GET zc-min > 0): with it every 4KB value in a
    cross-shard MGET is gathered as a BORROW (cutover = min(zc-min, 1024));
  - the REPLY ON control MGET returns every value intact and moves zc_sends (the borrow path
    really fired: an MGET borrows only through the cross-shard gather, so this also proves the
    32 random keys spanned shards);
  - the suppressed MGET moves zc_releases (borrows were gathered and returned UNSENT) and does
    NOT move zc_sends (nothing borrowed was submitted);
  - a counter the battery rests on must EXIST in INFO STATS (_lib.info_int: absent is a failure,
    never a silent 0).
On a fused (1s) boot with read-local armed the cross-shard MGET is served on the parsing thread's
own exec without taking a borrow, so the three counter checks are visible skips with that reason;
the wire assertions run on every boot.

Client: tests/_lib.Conn, a BUFFERED reader whose bulk read loops until the declared length and
asserts the CRLF trailer. The battery's first client read bulks through an UNBUFFERED socket file
(`makefile("rb", buffering=0)`), whose read(n) is a single recv(): on a zero-copy boot a borrowed
4KB value and its CRLF ride different sendmsg iovecs and land in different recv() calls, so the
short read was sliced as if complete and the trailer stayed in the stream (`unexpected reply head
b'\\r\\n'`). A fused read-local boot writes the array contiguously, which is why it passed there.
expect_wire() is the only raw-socket consumer; it first takes what the buffered reader already
holds so no byte can be skipped, and it uses the raw socket for its timed probes because a timeout
inside the socket FILE poisons it for every later read.

Exit status: 1 if any check failed, else 0 (never the failure count: tests/gate.sh py() reads
exit 3 as "the battery skipped itself").
"""
import os
import socket
import sys

import _lib

NKEYS, VALUE_LEN = 32, 4096
FAIL = 0
FUSED_LOCAL = False


def check(ok, label, detail=""):
    global FAIL
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + detail) if (detail and not ok) else ''}")
    if not ok:
        FAIL += 1


def check_zc_evidence(cond, label, detail):
    # Fused read-local serves the cross-shard MGET on the parsing thread's own exec without taking
    # a borrow: nothing goes out by zero-copy and a suppressed reply has nothing to release. The
    # counter EVIDENCE therefore does not apply on that boot; it is reported as a skip with its
    # reason, never turned into a silent pass. The wire assertions run regardless.
    if FUSED_LOCAL:
        print(f"  skip {label} -- fused read-local path takes no borrow ({detail})")
        return
    check(cond, label, detail)


class Conn(_lib.Conn):
    """tests/_lib.Conn (buffered reader, exact bulk framing) plus the raw-wire probe this battery
    needs."""

    def __init__(self, host, port):
        super().__init__(host, port, timeout=10)

    def _held(self):
        """Bytes the buffered reader already pulled off the socket but has not handed out. Empty
        after a whole reply was consumed with nothing pipelined behind it; folded into
        expect_wire() so a raw recv() can never skip them. Non-blocking: never waits for the
        server, and a non-blocking EAGAIN does not poison the socket file (only a timeout does)."""
        saved = self.sock.gettimeout()
        self.sock.settimeout(0.0)
        try:
            held = self.file.peek()   # buffered bytes, else ONE non-blocking raw read (b"" EAGAIN)
        except BlockingIOError:
            held = b""
        finally:
            self.sock.settimeout(saved)
        return self.file.read(len(held)) if held else b""

    def expect_wire(self, want, quiet=0.3, wait=5.0):
        """Exactly `want` bytes must arrive, then NOTHING else within `quiet` seconds.

        Returns (got, extra): `got` is what arrived while waiting for len(want) bytes (a leaked
        reply shows up here first), `extra` everything that followed inside the quiet window --
        drained (1 MiB cap) so a leaked array is measured whole and the stream is clean again for
        the next probe. Raw recv() on purpose: a timeout raised through the socket FILE latches
        SocketIO._timeout_occurred and every later read() would fail."""
        saved = self.sock.gettimeout()
        got, extra = self._held(), b""
        try:
            self.sock.settimeout(wait)
            try:
                while len(got) < len(want):
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        break
                    got += chunk
            except socket.timeout:
                pass
            self.sock.settimeout(quiet)
            try:
                while len(extra) < (1 << 20):
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        break
                    extra += chunk
            except socket.timeout:
                pass
        finally:
            self.sock.settimeout(saved)
        return got, extra


def stat(c, key):
    return _lib.info_int(c, "STATS", key)


def mismatch(got, want):
    """One line on how `got` differs from `want`, for the FAIL detail."""
    if isinstance(got, _lib.RespError):
        return f"error reply: {got}"
    if isinstance(want, list):
        if not isinstance(got, list):
            return f"reply is {type(got).__name__}, not an array"
        if len(got) != len(want):
            return f"{len(got)} elements, want {len(want)}"
        bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
        return f"elements {bad[:8]} differ" if bad else ""
    return f"got {got!r:.64}" if got != want else ""


def sync_check(label, fn, want):
    """A reply check that survives a desynced stream: a reader error is a FAIL row, not a
    traceback that hides the rows after it."""
    try:
        got = fn()
    except (AssertionError, EOFError, OSError) as e:
        check(False, label, f"{type(e).__name__}: {e}")
        return
    check(got == want, label, mismatch(got, want))


def wire_detail(got, extra):
    return f"got={got[:64]!r}{'...' if len(got) > 64 else ''} ({len(got)}B) extra={len(extra)}B"


def main():
    global FUSED_LOCAL
    host, port = sys.argv[1], int(sys.argv[2])
    admin = Conn(host, port)
    zc = admin.cmd("CONFIG", "GET", "zc-min")
    _tm = admin.cmd("CONFIG", "GET", "thread-mode")
    _rl = admin.cmd("CONFIG", "GET", "read-local")
    FUSED_LOCAL = (isinstance(_tm, list) and len(_tm) == 2 and _tm[1] == b"1s" and
                   isinstance(_rl, list) and len(_rl) == 2 and _rl[1] not in (b"0", b""))
    zc_min = int(zc[1]) if isinstance(zc, list) and len(zc) == 2 else 0
    check(zc_min > 0, "boot has zero-copy enabled (borrowed MGET values are reachable)",
          f"zc-min={zc_min}")

    tag = os.urandom(4).hex()
    keys = [f"replyoff:{tag}:{i}" for i in range(NKEYS)]
    values = [os.urandom(VALUE_LEN) for _ in range(NKEYS)]
    for k, v in zip(keys, values):
        assert admin.must("SET", k, v) == b"OK"

    # ---- control: REPLY ON, the same MGET must answer in full and move zc_sends ------------------
    c = Conn(host, port)
    zc_sends0 = stat(admin, "zc_sends")
    reply = c.cmd("MGET", *keys)
    check(reply == values, "control MGET (REPLY ON) returns every value intact",
          mismatch(reply, values))
    zc_sends1 = stat(admin, "zc_sends")
    check_zc_evidence(zc_sends1 > zc_sends0, "control MGET borrowed its values (zc_sends moved)",
                      f"{zc_sends0} -> {zc_sends1}: boot with zero-copy enabled")

    # ---- REPLY OFF: nothing until REPLY ON's +OK, then +PONG, then silence ---------------------
    zc_sends0, zc_rel0 = stat(admin, "zc_sends"), stat(admin, "zc_releases")
    c.send("CLIENT", "REPLY", "OFF")
    c.send("MGET", *keys)
    c.send("CLIENT", "REPLY", "ON")
    c.send("PING")
    got, extra = c.expect_wire(b"+OK\r\n+PONG\r\n")
    check(got == b"+OK\r\n+PONG\r\n" and not extra,
          "REPLY OFF: cross-shard MGET leaves NOTHING on the wire", wire_detail(got, extra))
    zc_sends1, zc_rel1 = stat(admin, "zc_sends"), stat(admin, "zc_releases")
    check_zc_evidence(zc_rel1 > zc_rel0, "suppressed MGET returned its borrows (zc_releases moved)",
                      f"{zc_rel0} -> {zc_rel1}")
    check_zc_evidence(zc_sends1 == zc_sends0,
                      "suppressed MGET submitted no borrowed send (zc_sends unchanged)",
                      f"{zc_sends0} -> {zc_sends1}")

    # ---- REPLY SKIP: the MGET is skipped, PING answers, then silence ----------------------------
    c.send("CLIENT", "REPLY", "SKIP")
    c.send("MGET", *keys)
    c.send("PING")
    got, extra = c.expect_wire(b"+PONG\r\n")
    check(got == b"+PONG\r\n" and not extra,
          "REPLY SKIP: cross-shard MGET leaves NOTHING on the wire", wire_detail(got, extra))

    # ---- the connection is still in sync afterwards ----------------------------------------------
    sync_check("connection still in sync after suppression",
               lambda: c.cmd("GET", keys[0]), values[0])
    sync_check("a later REPLY ON MGET on the same connection is intact",
               lambda: c.cmd("MGET", *keys), values)

    for k in keys:
        admin.cmd("DEL", k)
    print(f"replyoff_xshard: {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
