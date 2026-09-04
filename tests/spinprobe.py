#!/usr/bin/env python3
# L2 partial-frame spin probe. A connection that has sent an INCOMPLETE RESP frame and then goes
# quiet must not make its io thread spin: the parser returns Incomplete without advancing, and if
# the loop counts that as progress it never parks.
#
# Usage: spinprobe.py PORT [server_pid] [--idle-only]
#
# Scored from DEBUG LBSIGNALS' owner-written loop counters, never process CPU jiffies.  The partial
# arm is a delta over the same server's quiet baseline; this removes scheduler/CPU-frequency noise
# and, on failure, identifies the exact connection-owning thread.  --idle-only is the gate's
# one-second process-wide quiet-loop ceiling and checks every reported thread in either role model.
#
# Two things make the row non-vacuous (AUDIT-TESTS F1):
#   * the PID is the server that OWNS PORT: given by the caller (the gate passes $SRV) or resolved
#     from the listening socket with `ss`, refusing ambiguity. The old probe took the first
#     process named "tomokv", which on a shared box can be another lane's server. LBSIGNALS itself
#     is fetched from PORT, so the measured counters cannot come from that foreign process.
#   * after the idle window the frame is COMPLETED and must answer +OK: the parser held the partial
#     frame for the whole window. A server that dropped the half-frame connection idles just as
#     quietly and used to pass.
import math
import os
import re
import socket
import subprocess
import sys
import time

PORT = int(sys.argv[1])
IDLE_SECONDS = 1.0
LAND_SECONDS = 0.2
MAX_IDLE_ITERATIONS = 64
MAX_IDLE_SPINS = 64
MAX_IDLE_WAKES = 64
# Split executors deliberately run kExSpinBudget pause iterations before each Ring park. Price
# that fixed policy plus the same bounded wake allowance instead of applying the IO/fused ceiling
# to a different loop shape. A true unbounded spin still exceeds this by orders of magnitude.
EX_SPIN_BUDGET = 2048
RING_PARK_MS = 50
MAX_IDLE_EX_SPIN_CYCLES = (math.ceil(IDLE_SECONDS * 1000 / RING_PARK_MS) +
                           MAX_IDLE_WAKES + 4)
MAX_IDLE_EX_SPINS = EX_SPIN_BUDGET * MAX_IDLE_EX_SPIN_CYCLES
MAX_IDLE_EX_ITERATIONS = MAX_IDLE_EX_SPINS + MAX_IDLE_ITERATIONS
# THE PARKED-FRAME CEILINGS ARE NOT ALL THE SAME KIND OF NUMBER.
# What this row exists to catch is a partial frame that makes its owner thread SPIN or trade wakes
# instead of parking, and those two counters were +0 in all 36 measured runs below. Loop iterations
# are different: they price the observation window itself, and the window costs a whole number of
# passes that the sampler's own two DEBUG round trips can shift by one. Measured on this box, six
# runs each of three binaries -- including the SHIPPED one, which is the point -- gave extra
# iterations of 0, 7 or 9 with no other value in between and no separation between binaries:
#   train4  9 9 0 9 9 7   train3  9 9 9 7 7 9   shipped  7 9 0 9 0 9
# A ceiling of 8 therefore failed a correct server about half the time, which is what it did on two
# gate runs. 24 is three times the largest observed value and still two orders of magnitude below a
# real spin, which shows up as thousands of iterations.
MAX_EXTRA_ITERATIONS = 24
MAX_EXTRA_SPINS = 8
MAX_EXTRA_WAKES = 8
# ATTEMPTS. Wake accounting is a race against whatever else the box is doing: a gate sharing the
# machine with two compiling agents saw +15/+16 wakes on a server that measured +0/+0 alone. A
# thread that really spins or really trades wakes on a parked frame does it on every attempt, so
# retrying costs a defect nothing and costs a busy box a red row it did not earn.
PARKED_ATTEMPTS = 3


def arguments():
    pid = None
    idle_only = False
    for arg in sys.argv[2:]:
        if arg == "--idle-only":
            idle_only = True
        elif pid is None:
            try:
                pid = int(arg)
            except ValueError:
                raise SystemExit("spinprobe: unexpected argument %r" % arg)
        else:
            raise SystemExit("spinprobe: unexpected argument %r" % arg)
    return pid, idle_only


def listener_pids(port):
    try:
        out = subprocess.run(["ss", "-H", "-ltnp", "sport = :%d" % port],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({int(m.group(1)) for m in re.finditer(r"pid=(\d+)", out)})


def find_srv(given_pid):
    if given_pid is not None:
        pid = given_pid
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


def read_resp(stream):
    line = stream.readline()
    if not line.endswith(b"\r\n"):
        raise RuntimeError("truncated RESP reply: %r" % line)
    kind, value = line[:1], line[1:-2]
    if kind == b"+":
        return value
    if kind == b":":
        return int(value)
    if kind == b"-":
        raise RuntimeError("server error: %s" % value.decode("utf-8", "replace"))
    if kind == b"$":
        length = int(value)
        if length < 0:
            return None
        payload = stream.read(length)
        trailer = stream.read(2)
        if len(payload) != length or trailer != b"\r\n":
            raise RuntimeError("truncated bulk RESP reply")
        return payload
    raise RuntimeError("unsupported RESP reply: %r" % line)


def command(sock, stream, *args):
    encoded = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    request = [b"*%d\r\n" % len(encoded)]
    for arg in encoded:
        request.extend((b"$%d\r\n" % len(arg), arg, b"\r\n"))
    sock.sendall(b"".join(request))
    return read_resp(stream)


def connect():
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock, sock.makefile("rb")


def lbsignals(sock, stream):
    raw = command(sock, stream, "DEBUG", "LBSIGNALS")
    if not isinstance(raw, bytes) or not raw.startswith(b"lbver 1 "):
        raise RuntimeError("DEBUG LBSIGNALS returned %r" % (raw,))
    stamp = None
    threads = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        fields = line.split()
        if fields[:2] == ["lbver", "1"]:
            if len(fields) < 4 or fields[2] != "stamp_ns":
                raise RuntimeError("malformed LBSIGNALS header: %r" % line)
            stamp = int(fields[3])
        elif fields and fields[0] == "thread":
            if len(fields) < 16:
                raise RuntimeError("short LBSIGNALS thread row: %r" % line)
            tid = int(fields[1])
            if tid in threads:
                raise RuntimeError("duplicate LBSIGNALS thread %d" % tid)
            threads[tid] = {
                "role": fields[2],
                "clients": int(fields[4]),
                "iterations": int(fields[5]),
                "wakes_sent": int(fields[13]),
                "wakes_recv": int(fields[14]),
                "spins": int(fields[15]),
            }
    if stamp is None or not threads:
        raise RuntimeError("DEBUG LBSIGNALS omitted its stamp or thread rows")
    return stamp, threads


COUNTERS = ("iterations", "spins", "wakes_sent", "wakes_recv")


def deltas(before, after):
    if set(before) != set(after):
        raise RuntimeError("LBSIGNALS thread set changed during quiet window: %s -> %s"
                           % (sorted(before), sorted(after)))
    out = {}
    for tid in sorted(before):
        if before[tid]["role"] != after[tid]["role"]:
            raise RuntimeError("thread %d changed role during quiet window: %s -> %s"
                               % (tid, before[tid]["role"], after[tid]["role"]))
        row = {"role": after[tid]["role"]}
        for name in COUNTERS:
            if after[tid][name] < before[tid][name]:
                raise RuntimeError("thread %d counter %s regressed: %d -> %d"
                                   % (tid, name, before[tid][name], after[tid][name]))
            row[name] = after[tid][name] - before[tid][name]
        out[tid] = row
    return out


def measure(sock, stream):
    stamp0, before = lbsignals(sock, stream)
    time.sleep(IDLE_SECONDS)
    stamp1, after = lbsignals(sock, stream)
    if stamp1 - stamp0 < int(IDLE_SECONDS * 900_000_000):
        raise RuntimeError("LBSIGNALS capture was not fresh over the idle window: %d ns"
                           % (stamp1 - stamp0))
    return before, after, deltas(before, after)


def describe(rows):
    return "; ".join(
        "tid=%d role=%s iterations=%d spins=%d wakes=%d/%d"
        % (tid, row["role"], row["iterations"], row["spins"],
           row["wakes_sent"], row["wakes_recv"])
        for tid, row in sorted(rows.items()))


given_pid, idle_only = arguments()
srv = find_srv(given_pid)
admin, admin_file = connect()
admin_tid = command(admin, admin_file, "DEBUG", "IO-THREAD")
if not isinstance(admin_tid, int):
    raise SystemExit("spinprobe: DEBUG IO-THREAD returned %r" % (admin_tid,))

if idle_only:
    _before, _after, quiet = measure(admin, admin_file)
    sampling_fired = admin_tid in quiet and quiet[admin_tid]["iterations"] > 0
    offenders = {}
    for tid, row in quiet.items():
        ex = row["role"] == "ex"
        iteration_ceiling = MAX_IDLE_EX_ITERATIONS if ex else MAX_IDLE_ITERATIONS
        spin_ceiling = MAX_IDLE_EX_SPINS if ex else MAX_IDLE_SPINS
        if (row["iterations"] > iteration_ceiling or row["spins"] > spin_ceiling or
                row["wakes_sent"] + row["wakes_recv"] > MAX_IDLE_WAKES):
            offenders[tid] = row
    print("pid %d idle %.0fs LBSIGNALS delta: %s; sampler tid=%d mechanism=%s"
          % (srv, IDLE_SECONDS, describe(quiet), admin_tid,
             "fired" if sampling_fired else "FAIL: no sampling iteration"))
    admin_file.close()
    admin.close()
    sys.exit(0 if sampling_fired and not offenders else 1)

# Baseline has the same retained admin connection and the same two DEBUG samples as the partial
# window, so its target-thread delta prices the observation itself without process-wide noise.
for attempt in range(1, PARKED_ATTEMPTS + 1):
  _base_before, _base_after, baseline = measure(admin, admin_file)

  partial, partial_file = connect()
  target_tid = command(partial, partial_file, "DEBUG", "IO-THREAD")
  if not isinstance(target_tid, int) or target_tid not in baseline:
      raise SystemExit("spinprobe: invalid connection owner %r" % (target_tid,))
  partial.sendall(b"*3\r\n$3\r\nSE")
  time.sleep(LAND_SECONDS)               # let the incomplete frame reach its parked parser state
  partial_before, _partial_after, parked = measure(admin, admin_file)
  target = parked[target_tid]
  base_target = baseline[target_tid]
  extra = {name: target[name] - base_target[name] for name in COUNTERS}

  # Mechanism proof: the rest of the very same frame must complete into one SET and answer +OK.
  partial.sendall(b"T\r\n$8\r\nsp:probe\r\n$1\r\nv\r\n")
  try:
      reply = read_resp(partial_file)
  except (OSError, RuntimeError) as exc:
      reply = b"<%s>" % type(exc).__name__.encode()
  held = reply == b"OK"
  owner_after = None
  if held:
      owner_after = command(partial, partial_file, "DEBUG", "IO-THREAD")
      command(partial, partial_file, "DEL", "sp:probe")
  stable_owner = owner_after == target_tid

  sampling_fired = admin_tid in baseline and baseline[admin_tid]["iterations"] > 0
  sampling_fired = (sampling_fired and admin_tid in parked and
                    parked[admin_tid]["iterations"] > 0)
  within_ceiling = (extra["iterations"] <= MAX_EXTRA_ITERATIONS and
                    extra["spins"] <= MAX_EXTRA_SPINS and
                    extra["wakes_sent"] <= MAX_EXTRA_WAKES and
                    extra["wakes_recv"] <= MAX_EXTRA_WAKES)

  print("pid %d idle %.0fs%s target tid=%d role=%s: baseline {%s}; partial {%s}; "
        "extra iterations=%+d spins=%+d wakes=%+d/%+d; frame completion -> %r; "
        "owner after=%r (%s)"
        % (srv, IDLE_SECONDS, "" if attempt == 1 else " (retry %d)" % (attempt - 1),
           target_tid, partial_before[target_tid]["role"],
           describe({target_tid: base_target}), describe({target_tid: target}),
           extra["iterations"], extra["spins"], extra["wakes_sent"], extra["wakes_recv"],
           reply, owner_after, "stable" if stable_owner else "CHANGED"))

  # One connection per attempt: the parked frame is the state under test, so a retry has to start
  # from a fresh unparked connection rather than reuse the one already completed above.
  partial_file.close()
  partial.close()
  if within_ceiling and held and stable_owner and sampling_fired:
      break

admin_file.close()
admin.close()
sys.exit(0 if within_ceiling and held and stable_owner and sampling_fired else 1)
