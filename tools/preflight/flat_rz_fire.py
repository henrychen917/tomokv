#!/usr/bin/env python3
"""Fire DEBUG RELOAD into a live FLAT_RZ_COPYING window, with NOTHING else touching the server.

Everything below is a correction of a way this failed to open the window. Keeping the list because
each one produced a green run that proved nothing:

  1. `redis-cli debug reload` — a fresh redis-cli handshakes before sending, and the handshake is
     worker-dispatched, so it does not complete while the coordinator has the workers parked. The
     reload arrived 1ms AFTER each copy finished, every cycle. => one pre-opened socket.
  2. Polling INFO to wait for the window — every command opens a flat region (call() takes
     FLAT_EXTERN_REGION), and QUIESCING refuses to complete while any io epoch is odd. INFO on a 2M
     key db is slow enough that a 20ms poll loop kept an epoch odd almost continuously, so the
     coordinator aborted at its 200ms deadline over and over and NO copy ever started until the
     poller stopped. The observer prevented the event. => no commands at all inside the window.
  3. One big DEL burst to arm the resize — it trips the shrink flag part way through, the
     coordinator parks the workers, and the REST of the burst stalls until the copy completes, so
     the burst only returns once the window has shut. => the trigger delete must be small enough to
     finish inside one beforeSleep pass.

So the sequence here is: open one socket and handshake it; send a SMALL delete that crosses the
shrink trigger; sleep just long enough for the coordinator to arm and enter COPYING; then send
DEBUG RELOAD on that same socket. No polling, no second connection, no big burst.

Evidence that the window really was open is read AFTER the fact, from
tomokv_flat_resize_quiesce_waits, never from inside it.

usage: flat_rz_fire.py <port> <keep> <armhi> <arm_delay_s> [reload-args...]
prints: the reload's reply
"""
import socket, sys, time

port = int(sys.argv[1]); keep = int(sys.argv[2]); armhi = int(sys.argv[3])
delay = float(sys.argv[4]); extra = sys.argv[5:]


def enc(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        b_ = x.encode() if isinstance(x, str) else x
        out += b"$%d\r\n%s\r\n" % (len(b_), b_)
    return out


s = socket.create_connection(("127.0.0.1", port))
s.settimeout(600)
buf = b""


def read_one():
    """read exactly one RESP reply (simple/int/bulk) off the socket"""
    global buf
    while True:
        if buf[:1] in (b"+", b"-", b":"):
            i = buf.find(b"\r\n")
            if i > 0:
                r, buf = buf[:i], buf[i + 2:]
                return r
        elif buf[:1] == b"$":
            i = buf.find(b"\r\n")
            if i > 0:
                n = int(buf[1:i])
                if n < 0:
                    buf = buf[i + 2:]
                    return b""
                if len(buf) >= i + 2 + n + 2:
                    r = buf[i + 2:i + 2 + n]
                    buf = buf[i + 2 + n + 2:]
                    return r
        c = s.recv(1 << 20)
        if not c:
            raise EOFError("server closed the connection")
        buf += c


# handshake this socket NOW, while nothing is parked, so the window costs no connect
s.sendall(enc("PING"))
read_one()

# the trigger: small enough to complete inside one beforeSleep pass, so the coordinator arms only
# AFTER it has drained and nothing of ours is left queued behind the park
try:
    s.sendall(b"".join(enc("DEL", "k:%d" % i) for i in range(keep, armhi)))
    for _ in range(armhi - keep):
        read_one()
except (EOFError, OSError) as e:
    print("CONNECTION-CLOSED(%s)" % e)
    raise SystemExit(0)

# let the coordinator arm (one pass) and get into COPYING (next pass). Nothing is sent meanwhile.
time.sleep(delay)

try:
    s.sendall(enc("DEBUG", "RELOAD", *extra))
    print(read_one().decode(errors="replace"))
except (EOFError, OSError) as e:
    # the pre-fix arm kills the server here, and a bare traceback reads like a harness bug
    print("CONNECTION-CLOSED(%s)" % e)
