#!/usr/bin/env python3
# L2 partial-frame spin probe. A connection that has sent an INCOMPLETE RESP frame and then goes
# quiet must not make its io thread spin: the parser returns Incomplete without advancing, and if
# the loop counts that as progress it never parks.   usage: spinprobe.py PORT [server_pid]
#
# Scored as a DELTA over the same server's zero-conn idle burn: background timers (cron, climon,
# lb census, the age sampler) legitimately tick the loop and drift across binaries, so an
# absolute threshold rots. The defect this guards against costs ~1000 ticks/6s; wakeup-only
# parking costs ~0 over baseline.
#
# Two things make the row non-vacuous (AUDIT-TESTS F1):
#   * the PID is the server that OWNS PORT: given by the caller (the gate passes $SRV) or resolved
#     from the listening socket with `ss`, refusing ambiguity. The old probe took the first
#     /proc/*/comm containing "tomokv", which on a shared box is another lane's server.
#   * after the idle window the frame is COMPLETED and must answer +OK: the parser held the partial
#     frame for the whole window. A server that dropped the half-frame connection idles just as
#     quietly and used to pass.
import os
import re
import socket
import subprocess
import sys
import time

PORT = int(sys.argv[1])
IDLE_SECONDS = 6
MAX_EXTRA_TICKS = 40


def listener_pids(port):
    try:
        out = subprocess.run(["ss", "-H", "-ltnp", "sport = :%d" % port],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({int(m.group(1)) for m in re.finditer(r"pid=(\d+)", out)})


def find_srv():
    if len(sys.argv) > 2:
        pid = int(sys.argv[2])
        if not os.path.exists("/proc/%d" % pid):
            raise SystemExit("spinprobe: server pid %d is not alive" % pid)
        return pid
    pids = listener_pids(PORT)
    if len(pids) == 1:
        return pids[0]
    if not pids:
        raise SystemExit("spinprobe: no process listens on port %d (ss); pass the server pid" % PORT)
    raise SystemExit("spinprobe: %d distinct pids listen on port %d (%s): ambiguous, pass the pid"
                     % (len(pids), PORT, pids))


srv = find_srv()


def ticks():
    # utime + stime; split after the ')' so a comm with spaces cannot shift the fields.
    fields = open("/proc/%d/stat" % srv).read().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])


t0 = ticks()
time.sleep(IDLE_SECONDS)
base = ticks() - t0

s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.sendall(b"*3\r\n$3\r\nSE")
time.sleep(0.5)                       # let the frame land and the conn reach its parked state
t0 = ticks()
time.sleep(IDLE_SECONDS)
d = ticks() - t0

# Mechanism proof: the rest of the very same frame must complete into one SET and answer +OK.
s.sendall(b"T\r\n$8\r\nsp:probe\r\n$1\r\nv\r\n")
f = s.makefile("rb")
try:
    reply = f.readline()
except OSError as exc:
    reply = b"<%s>" % type(exc).__name__.encode()
held = reply == b"+OK\r\n"
if held:
    s.sendall(b"*2\r\n$3\r\nDEL\r\n$8\r\nsp:probe\r\n")
    f.readline()
s.close()

print("pid %d idle %ds: baseline %d ticks, with partial-frame conn %d ticks (delta %+d); "
      "frame completion -> %r (%s)"
      % (srv, IDLE_SECONDS, base, d, d - base, reply,
         "parser held the partial frame" if held else "FAIL: partial frame was NOT held"))
sys.exit(0 if (d - base <= MAX_EXTRA_TICKS and held) else 1)
