#!/usr/bin/env python3
"""TTL state and expiry EVENTS must survive a FLIP.

usage: flip_ttl.py HOST PORT

Two shipped incidents lived exactly here and neither had a directed test:
  * the LB mover moved a shard and its expired-key events stranded at the OLD owner (the
    keyless-notify pending pointer was never rebound), and
  * an accounting walk expired keys outside any operation's cut.
FLIP moves shards between executors through its own stage machinery, so it gets the directed
version: keys carrying live TTLs are spread across every shard, the split is flipped while those
TTLs are pending, and then EVERY key must still (a) expire, and (b) deliver its expired event.
A missing event is precisely the stranded-binding failure; a surviving key is a lost expire-index.

Shape-agnostic: the test reads the live split from the FLIP report and flips to a materially
different one, so it runs under any boot ratio with at least 4 threads.
"""

import select
import socket
import sys
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
NKEYS = 96
TTL_MS = 700
ROUNDS = 2


def conn():
    s = socket.create_connection((HOST, PORT), timeout=15)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def send(sock, *args):
    enc = [a.encode() if isinstance(a, str) else a for a in args]
    sock.sendall(b"*%d\r\n" % len(enc) +
                 b"".join(b"$%d\r\n" % len(a) + a + b"\r\n" for a in enc))


def rd(f):
    p = f.read(1)
    if not p:
        raise IOError("connection closed")
    line = f.readline()[:-2]
    if p == b"-":
        raise IOError("error reply: %s" % line.decode(errors="replace"))
    if p in b"+:":
        return line
    if p == b"$":
        n = int(line)
        if n == -1:
            return None
        d = f.read(n)
        f.read(2)
        return d
    if p == b"*":
        n = int(line)
        return None if n == -1 else [rd(f) for _ in range(n)]
    if p == b"%":
        n = int(line)
        out = {}
        for _ in range(n):
            k = rd(f)
            out[k] = rd(f)
        return out
    raise IOError("bad prefix %r" % p)


def flip_report(s, f):
    send(s, "FLIP")
    rep = rd(f)
    if isinstance(rep, dict):
        return {k.decode(): v for k, v in rep.items()}
    it = iter(rep)
    return {k.decode(): v for k, v in zip(it, it)}


def as_int(v):
    return int(v if not isinstance(v, bytes) else v.decode())


w, wf = conn()
sub, subf = conn()

send(w, "CONFIG", "SET", "notify-keyspace-events", "Ex")
rd(wf)
send(sub, "SUBSCRIBE", "__keyevent@0__:expired")
rd(subf)
# From here on the subscriber is read with an incremental buffer, never the buffered file
# object: a BufferedReader that hits a socket timeout mid-frame is permanently wedged
# ("cannot read from timed out object"), which fails the test for a harness reason.
subbuf = b""


def sub_messages(deadline):
    """Yield complete pubsub frames until the deadline, surviving idle gaps."""
    global subbuf

    def parse_one(buf):
        # Returns (frame, consumed) or (None, 0) if incomplete. Only the shapes SUBSCRIBE
        # traffic produces: arrays of bulk strings / integers.
        def line(pos):
            end = buf.find(b"\r\n", pos)
            return (None, 0) if end < 0 else (buf[pos:end], end + 2)

        def item(pos):
            if pos >= len(buf):
                return None, 0
            t = buf[pos:pos + 1]
            head, nxt = line(pos + 1)
            if head is None:
                return None, 0
            if t == b":":
                return int(head), nxt
            if t == b"$":
                n = int(head)
                if n < 0:
                    return None, nxt
                if len(buf) < nxt + n + 2:
                    return None, 0
                return buf[nxt:nxt + n], nxt + n + 2
            if t == b"*":
                out = []
                p2 = nxt
                for _ in range(int(head)):
                    v, p2 = item(p2)
                    if p2 == 0:
                        return None, 0
                    out.append(v)
                return out, p2
            raise IOError("unexpected pubsub prefix %r" % t)

        return item(0)

    while time.time() < deadline:
        frame, consumed = parse_one(subbuf)
        if consumed:
            subbuf = subbuf[consumed:]
            yield frame
            continue
        r, _, _ = select.select([sub], [], [], 0.2)
        if not r:
            continue
        chunk = sub.recv(65536)
        if not chunk:
            raise IOError("subscriber connection closed")
        subbuf += chunk

checks = 0
for rnd in range(ROUNDS):
    rep = flip_report(w, wf)
    io, ex = as_int(rep["live_io"]), as_int(rep["live_ex"])
    total = io + ex
    # A materially different split: swap-heavy, clamped to a legal shape.
    tio = max(2, min(total - 2, ex + (2 if rnd == 0 else -2)))
    tex = total - tio
    if tio == io:
        tio = max(2, min(total - 2, io + 2))
        tex = total - tio

    keys = ["ft:%d:%d" % (rnd, i) for i in range(NKEYS)]
    for k in keys:
        send(w, "SET", k, "v", "PX", str(TTL_MS))
        rd(wf)

    send(w, "FLIP", str(tio), str(tex))
    if rd(wf) != b"OK":
        print("FAIL: FLIP %d %d refused on a lightly loaded server" % (tio, tex))
        sys.exit(1)
    deadline = time.time() + 10
    while time.time() < deadline:
        rep = flip_report(w, wf)
        if (as_int(rep["live_io"]) == tio and as_int(rep["live_ex"]) == tex and
                str(rep.get("moving", b"0")) in ("b'0'", "0", "b'false'")):
            break
        time.sleep(0.1)
    else:
        print("FAIL: flip to %d:%d never landed" % (tio, tex))
        sys.exit(1)
    checks += 1

    # Every key set BEFORE the flip must now expire on whatever executor owns its shard AFTER it,
    # and every expiry must deliver its event to this subscriber.
    got = set()
    deadline = time.time() + 8
    try:
        for frame in sub_messages(deadline):
            if isinstance(frame, list) and len(frame) == 3 and frame[0] == b"message":
                key = frame[2].decode()
                if key.startswith("ft:%d:" % rnd):
                    got.add(key)
                    if len(got) == NKEYS:
                        break
    except IOError as e:
        print("FAIL: subscriber died: %s" % e)
        sys.exit(1)
    if len(got) != NKEYS:
        missing = sorted(set(keys) - got)[:5]
        print("FAIL: round %d delivered %d/%d expired events across the flip; missing e.g. %s"
              % (rnd, len(got), NKEYS, missing))
        sys.exit(1)
    checks += 1

    # And the data itself must be gone -- a delivered event for a surviving key would be worse.
    args = ["EXISTS"] + keys
    send(w, *args)
    alive = int(rd(wf))
    if alive != 0:
        print("FAIL: round %d left %d keys alive after their TTLs crossed the flip" % (rnd, alive))
        sys.exit(1)
    checks += 1

print("flip_ttl: %d checks ok -- %d flips, %d expired events delivered across them"
      % (checks, ROUNDS, ROUNDS * NKEYS))
sys.exit(0)
