#!/usr/bin/env python3
"""FIX 2 sanity check: does INFO total_commands_processed report the number of
commands the client actually sent?

Method (exact, no hand-waved slop): read INFO, send exactly N commands, read INFO
again. An INFO reply is built BEFORE call() bumps the counter, so INFO#a reports Va
and leaves the counter at Va+1; therefore

    measured = Vb - Va - 1

is exactly the number of commands executed between the two reads, i.e. exactly N if
the counter is correct. Everything runs on ONE connection so no other client can
contribute, and the server is otherwise idle (no cron command traffic on this fork).
"""
import socket, sys, threading, time

port = int(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else "run"


def conn():
    s = socket.create_connection(("127.0.0.1", port))
    s.settimeout(180)
    return s


def cmd(*a):
    o = f"*{len(a)}\r\n".encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o


SENT = b"ZZ_SENTINEL_ZZ"


def info_field(s, field):
    """Send INFO stats and parse one field out of the RESP bulk reply."""
    s.sendall(cmd("INFO", "stats"))
    buf = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            raise RuntimeError("closed during INFO")
        buf += c
        if buf[0:1] != b"$":
            raise RuntimeError("unexpected INFO reply %r" % buf[:64])
        hdr = buf.find(b"\r\n")
        if hdr < 0:
            continue
        n = int(buf[1:hdr])
        if len(buf) >= hdr + 2 + n + 2:
            body = buf[hdr + 2:hdr + 2 + n]
            break
    for line in body.split(b"\r\n"):
        if line.startswith(field.encode() + b":"):
            return int(line.split(b":")[1])
    raise RuntimeError("field %s not in INFO stats" % field)


def run(name, batch):
    s = conn()
    # warm: make sure the connection is established and settled before the first read
    s.sendall(cmd("PING"))
    while b"+PONG" not in s.recv(1 << 16):
        pass
    va = info_field(s, "total_commands_processed")
    payload = b"".join(batch) + cmd("ECHO", SENT)
    n_sent = len(batch) + 1                      # + the ECHO sentinel
    # Drain on a second thread WHILE sending: a multi-MB single sendall with nobody reading can
    # wedge on socket back-pressure. The sentinel is the last command, and the ring splices
    # replies in issue order, so seeing it proves every earlier command completed.
    err = []

    def reader():
        buf = b""
        try:
            while SENT not in buf:
                c = s.recv(1 << 20)
                if not c:
                    err.append("closed before sentinel")
                    return
                buf = buf[-64:] + c
        except Exception as e:                   # noqa: BLE001 - reported via err
            err.append(repr(e))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    s.sendall(payload)
    t.join(300)
    if t.is_alive():
        raise RuntimeError("timed out waiting for sentinel (%s)" % name)
    if err:
        raise RuntimeError("reader failed: %s" % err[0])
    time.sleep(0.5)                              # let any in-flight bumps land
    vb = info_field(s, "total_commands_processed")
    measured = vb - va - 1                       # -1: INFO#a counts itself after reporting
    verdict = "OK" if measured == n_sent else "WRONG"
    print("%-8s %-20s sent=%-8d INFO_counted=%-8d ratio=%.4f  %s"
          % (label, name, n_sent, measured, measured / n_sent, verdict))
    s.close()
    return n_sent, measured


N = 50000
rows = []
# A. worker-routed single-key traffic (SET/GET) -- exExecFake, the dominant regime
rows.append(run("A_setget_worker",
                [cmd("SET", "k:%d" % i, "v") for i in range(N)] +
                [cmd("GET", "k:%d" % i) for i in range(N)]))
# B. inline traffic on the io thread -- call(); PING is not worker-routed
rows.append(run("B_ping_inline", [cmd("PING") for _ in range(N)]))
# C. cross-shard scatter-gather -- ONE MGET of 8 keys is ONE client command
rows.append(run("C_mget8_xshard",
                [cmd("MGET", *["k:%d" % ((i * 8 + j) % N) for j in range(8)])
                 for i in range(N // 5)]))
# D. mixed pipeline over all three routes
mix = []
for i in range(N // 4):
    mix += [cmd("SET", "m:%d" % i, "v"), cmd("GET", "m:%d" % i),
            cmd("PING"), cmd("MGET", "m:%d" % i, "m:%d" % ((i + 1) % (N // 4)))]
rows.append(run("D_mixed", mix))

te = sum(r[0] for r in rows)
tm = sum(r[1] for r in rows)
print("%-8s %-20s sent=%-8d INFO_counted=%-8d ratio=%.4f" % (label, "TOTAL", te, tm, tm / te))
