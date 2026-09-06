#!/usr/bin/env python3
"""DIRECTED REPRODUCTION of the expwide S1 MGET failure.

expwide S1 arms eight keys on eight distinct owners with one shared deadline, turns on
DEBUG ATOMIC-FANOUT-DEFER, and requires the cross-shard read to take at least half the defer. On
t-rlbatch (and so on t-ringsize) the MGET comes back in 0.000s, so the section cannot prove the
window ever opened and fails rather than pass vacuously.

The elapsed time alone cannot say WHY. Two very different faults produce the same 0.000s:

  (a) the hook is broken, and the fan-out ran without being deferred; or
  (b) the MGET never entered the fan-out at all -- it was served by the read-local path, which the
      hook does not cover.

So this samples the read-local MGET counters either side of the command. If
read_local_mget_local_hits moves, the command was served locally and (b) is the answer, which makes
the expwide failure a REAL loss of coverage: the deadline-cut invariant that S1 exists to police is
no longer being exercised by S1 on this branch, whatever the local path happens to do.

EXISTS is run as the in-test control: same eight owners, same hook, same connection.

    s1_mget_repro.py HOST PORT [defer_us]
"""
import socket, sys, time

HOST = sys.argv[1]
PORT = int(sys.argv[2])
DEFER_US = int(sys.argv[3]) if len(sys.argv) > 3 else 400000


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=120)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed the connection")
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body
        if kind == b"-":
            return ("ERR", body.decode())
        if kind == b":":
            return int(body)
        if kind == b"$":
            n = int(body)
            if n == -1:
                return None
            data = self.file.read(n + 2)
            return data[:-2]
        if kind == b"*":
            n = int(body)
            if n == -1:
                return None
            return [self.read() for _ in range(n)]
        raise AssertionError("bad reply %r" % line)

    def cmd(self, *args):
        out = bytearray(b"*%d\r\n" % len(args))
        for a in args:
            if not isinstance(a, bytes):
                a = str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        self.sock.sendall(out)
        return self.read()


def info_counters(c):
    body = c.cmd("INFO", "all")
    if isinstance(body, tuple):
        return {}
    out = {}
    for line in body.decode(errors="replace").replace("\r", "").split("\n"):
        if ":" in line and line.startswith("read_local"):
            k, _, v = line.partition(":")
            try:
                out[k] = int(v)
            except ValueError:
                pass
    return out


def owner_keys(c, prefix="expwide:hop", count=8):
    by_shard = {}
    for i in range(6000):
        key = "%s:%04d" % (prefix, i)
        s = c.cmd("DEBUG", "SHARD", key)
        if isinstance(s, int) and s not in by_shard:
            by_shard[s] = key
        if len(by_shard) == count:
            break
    if len(by_shard) != count:
        raise SystemExit("DEBUG SHARD found only %d owners" % len(by_shard))
    return [by_shard[s] for s in sorted(by_shard)]


def main():
    c = Resp()
    if not isinstance(c.cmd("DEBUG", "SHARD", "expwide:probe"), int):
        raise SystemExit("server is not sharded; S1 does not apply")
    c.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "0")
    c.cmd("FLUSHALL")
    keys = owner_keys(c)
    deadline_ms = DEFER_US // 2000

    print(f"{'command':<8}{'elapsed s':>11}{'>=defer/2':>11}"
          f"{'mget_local_hits':>18}{'mget_fallbacks':>16}{'hits':>10}{'verdict':>28}")
    for name, args in (("MGET", ("MGET",) + tuple(keys)),
                       ("EXISTS", ("EXISTS",) + tuple(keys))):
        # one shared absolute deadline, placed inside the window the hook is about to open
        now_ms = c.cmd("TIME")
        base = int(now_ms[0]) * 1000 + int(now_ms[1]) // 1000
        for k in keys:
            c.cmd("SET", k, "v")
        for k in keys:
            c.cmd("PEXPIREAT", k, base + deadline_ms)
        if c.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", str(DEFER_US)) != b"OK":
            raise SystemExit("fan-out defer hook rejected")
        before = info_counters(c)
        t0 = time.monotonic()
        c.cmd(*args)
        elapsed = time.monotonic() - t0
        after = info_counters(c)
        c.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", "0")

        d = lambda k: after.get(k, 0) - before.get(k, 0)
        widened = elapsed >= DEFER_US / 2.0e6
        local = d("read_local_mget_local_hits")
        if widened:
            verdict = "entered the deferred fan-out"
        elif local > 0:
            verdict = "SERVED LOCALLY, hook bypassed"
        else:
            verdict = "no fan-out AND not local (?)"
        print(f"{name:<8}{elapsed:>11.3f}{str(widened):>11}"
              f"{local:>18}{d('read_local_mget_fallbacks'):>16}{d('read_local_hits'):>10}"
              f"{verdict:>28}")


main()
