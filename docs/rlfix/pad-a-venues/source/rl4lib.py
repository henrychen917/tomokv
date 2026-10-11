#!/usr/bin/env python3
"""Round-4 read-local audit: black-box helpers (RESP client + server lifecycle).

Rules encoded here (from round4-read/PROMPT-read-local.md):
  * every server and client is pinned with `taskset -c 96-111`;
  * ports 22300-22399 only;
  * servers boot with --bind 127.0.0.1 --port P --save "" --appendonly no;
  * the PID recorded is the server process itself (taskset execs the binary);
  * stop = kill <pid>, wait, then `ss -ltn` must show the port closed;
  * never pkill.
"""
import os
import socket
import subprocess
import sys
import time

TOMO = '/home/user/Projects/cx-rlfix/build/rlfix/pad-a/tomokv'
REDIS = "/home/user/Projects/redis74/src/redis-server"
CORES = "48-55"
PORT_LO, PORT_HI = 25600, 25699
LOGDIR = '/home/user/Projects/cx-rlfix/docs/rlfix/pad-a-venues'

# Pin the client process itself.
try:
    os.sched_setaffinity(0, set(range(57, 64)))
except OSError:
    pass


class RespError(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg if isinstance(msg, bytes) else msg.encode()

    def __eq__(self, other):
        return isinstance(other, RespError) and self.msg == other.msg

    def __hash__(self):
        return hash(self.msg)

    def __repr__(self):
        return "ERR<%s>" % self.msg.decode("utf-8", "replace")


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        elif not isinstance(a, (bytes, bytearray)):
            a = str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


class Conn:
    def __init__(self, port, host="127.0.0.1", timeout=20.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _fill(self):
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("server closed the connection")
        self.buf += chunk

    def _line(self):
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                return line
            self._fill()

    def _exact(self, n):
        while len(self.buf) < n + 2:
            self._fill()
        data, self.buf = self.buf[:n], self.buf[n + 2:]
        return data

    def read(self):
        line = self._line()
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest
        if t == b"-":
            return RespError(rest)
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            return None if n < 0 else self._exact(n)
        if t == b"*":
            n = int(rest)
            return None if n < 0 else [self.read() for _ in range(n)]
        if t == b"_":
            return None
        if t == b"%":
            n = int(rest)
            return {self.read(): self.read() for _ in range(n)}
        if t == b"#":
            return rest == b"t"
        if t == b",":
            return float(rest)
        if t in (b"=", b"!"):
            n = int(rest)
            return self._exact(n)
        if t == b"~" or t == b">":
            n = int(rest)
            return [self.read() for _ in range(n)]
        raise ValueError("bad RESP type %r in %r" % (t, line))

    def send(self, payload):
        self.sock.sendall(payload)

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def pipeline(self, cmds):
        self.sock.sendall(b"".join(encode(*c) for c in cmds))
        return [self.read() for _ in cmds]


def parse_info(raw):
    if isinstance(raw, RespError):
        raise AssertionError("INFO failed: %r" % raw)
    out = {}
    for line in raw.decode("utf-8", "replace").split("\r\n"):
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k] = v
    return out


def info(conn, section="all"):
    return parse_info(conn.cmd("INFO", section))


def port_listening(port):
    out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].endswith(":%d" % port):
            return True
    return False


class Server:
    """One server process. `kind` is 'tomo' or 'redis'."""

    def __init__(self, port, args=(), kind="tomo", binary=None, name=None):
        if not (PORT_LO <= port <= PORT_HI):
            raise ValueError("port %d outside 22300-22399" % port)
        self.port = port
        self.kind = kind
        self.binary = binary or (TOMO if kind == "tomo" else REDIS)
        self.args = list(args)
        self.proc = None
        self.pid = None
        os.makedirs(LOGDIR, exist_ok=True)
        self.name = name or ("%s-%d" % (kind, port))
        self.logpath = os.path.join(LOGDIR, "%s-%d.log" % (self.name, int(time.time() * 1000)))

    def argv(self):
        base = ["taskset", "-c", "56" if self.kind == "redis" else CORES, self.binary,
                "--bind", "127.0.0.1", "--port", str(self.port),
                "--save", "", "--appendonly", "no"]
        if self.kind == "redis":
            base += ["--daemonize", "no", "--dir", LOGDIR,
                     "--dbfilename", "rl4-oracle-%d.rdb" % self.port]
        if self.kind == "tomo":
            base += ["--shards", "16"]
            if "1s" not in self.args:
                base += ["--ratio", "6:2"]
        return base + self.args

    def start(self, timeout=30.0, expect_fail=False):
        if port_listening(self.port):
            raise AssertionError("port %d already in use" % self.port)
        self.log = open(self.logpath, "wb")
        self.proc = subprocess.Popen(self.argv(), stdout=self.log, stderr=subprocess.STDOUT)
        self.pid = self.proc.pid       # taskset execs the binary: this IS the server pid
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rc = self.proc.poll()
            if rc is not None:
                self.log.close()
                if expect_fail:
                    return rc
                raise AssertionError("server exited rc=%s: %s" % (rc, self.output()[-2000:]))
            try:
                c = Conn(self.port, timeout=2.0)
                r = c.cmd("PING")
                c.close()
                if r == b"PONG":
                    if expect_fail:
                        raise AssertionError("expected boot refusal but server is up")
                    return self
            except (OSError, ConnectionError, ValueError):
                pass
            time.sleep(0.05)
        raise AssertionError("server on %d not ready in %.0fs" % (self.port, timeout))

    def output(self):
        try:
            with open(self.logpath, "rb") as f:
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def comm_check(self):
        """Confirm the recorded PID is the server binary itself (not a wrapper)."""
        try:
            exe = os.readlink("/proc/%d/exe" % self.pid)
        except OSError as e:
            return "pid %d: %s" % (self.pid, e)
        return exe

    def stop(self, timeout=30.0):
        if self.proc is None or self.proc.poll() is not None:
            closed = not port_listening(self.port)
            return closed
        subprocess.run(["kill", str(self.pid)])
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["kill", "-9", str(self.pid)])
            self.proc.wait(timeout=10)
        try:
            self.log.close()
        except Exception:
            pass
        for _ in range(100):
            if not port_listening(self.port):
                return True
            time.sleep(0.05)
        return False

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        closed = self.stop()
        if not closed:
            print("WARNING: port %d still listening after stop" % self.port, file=sys.stderr)
        return False


class Report:
    def __init__(self, name):
        self.name = name
        self.rows = []

    def check(self, label, ok, detail=""):
        self.rows.append((label, bool(ok), detail))
        print("%s %s: %s %s" % (self.name, "PASS" if ok else "FAIL", label,
                                 ("-- " + str(detail)) if detail else ""))
        sys.stdout.flush()

    def note(self, label, detail=""):
        self.rows.append((label, None, detail))
        print("%s NOTE: %s %s" % (self.name, label, ("-- " + str(detail)) if detail else ""))
        sys.stdout.flush()

    def finish(self):
        fails = [r for r in self.rows if r[1] is False]
        print("%s SUMMARY: %d checks, %d FAIL" % (
            self.name, sum(1 for r in self.rows if r[1] is not None), len(fails)))
        return 0 if not fails else 1


def rl_stats(conn):
    t = info(conn, "stats")
    return {k: int(v) for k, v in t.items() if k.startswith("read_local_")
            and v.lstrip("-").isdigit()}


def delta(after, before, keys=None):
    keys = keys or sorted(set(after) | set(before))
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) - before.get(k, 0)}
