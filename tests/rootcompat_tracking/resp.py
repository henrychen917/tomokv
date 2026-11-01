"""Minimal RESP2/RESP3 client for black-box reproduction (no third-party deps).

Push frames ('>') are queued separately from replies so a test can count invalidations and
pub/sub messages without disturbing request/reply pairing.
"""
import socket
import time


class RespError(Exception):
    pass


class ErrorReply(str):
    """An error reply (-ERR ...) kept as a value, not raised."""


class Push(list):
    """A RESP3 push frame."""


class _Need(Exception):
    pass


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, bytes):
            b = a
        elif isinstance(a, str):
            b = a.encode()
        else:
            b = str(a).encode()
        out.append(b"$%d\r\n" % len(b))
        out.append(b)
        out.append(b"\r\n")
    return b"".join(out)


class Conn:
    def __init__(self, port, host="127.0.0.1", timeout=5.0, name=None):
        self.port = port
        self.host = host
        self.name = name
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.pos = 0
        self.pushes = []          # (monotonic time, Push)
        self.default_timeout = timeout

    # ---------------------------------------------------------------- parsing
    def _line(self):
        i = self.buf.find(b"\r\n", self.pos)
        if i < 0:
            raise _Need()
        line = self.buf[self.pos:i]
        self.pos = i + 2
        return line

    def _parse(self):
        t = self.buf[self.pos:self.pos + 1]
        if not t:
            raise _Need()
        self.pos += 1
        if t == b"+":
            return self._line().decode(errors="replace")
        if t == b"-":
            return ErrorReply(self._line().decode(errors="replace"))
        if t == b":":
            return int(self._line())
        if t in (b"$", b"=", b"!"):
            n = int(self._line())
            if n < 0:
                return None
            if len(self.buf) < self.pos + n + 2:
                raise _Need()
            data = self.buf[self.pos:self.pos + n]
            self.pos += n + 2
            if t == b"=":
                data = data[4:]
            if t == b"!":
                return ErrorReply(data.decode(errors="replace"))
            return data
        if t in (b"*", b">", b"~"):
            n = int(self._line())
            if n < 0:
                return None
            items = [self._parse() for _ in range(n)]
            if t == b">":
                return Push(items)
            return items
        if t == b"%":
            n = int(self._line())
            items = []
            for _ in range(n):
                k = self._parse()
                v = self._parse()
                items.append((k, v))
            return dict((k if not isinstance(k, list) else tuple(k), v) for k, v in items)
        if t == b"|":   # attribute: parse and drop, then return the following value
            n = int(self._line())
            for _ in range(n):
                self._parse()
                self._parse()
            return self._parse()
        if t == b"_":
            self._line()
            return None
        if t == b"#":
            return self._line() == b"t"
        if t == b",":
            return float(self._line())
        if t == b"(":
            return int(self._line())
        raise RespError("bad type byte %r at %d" % (t, self.pos - 1))

    def _try_one(self):
        start = self.pos
        try:
            v = self._parse()
        except _Need:
            self.pos = start
            return False, None
        if self.pos > 1 << 20:
            self.buf = self.buf[self.pos:]
            self.pos = 0
        return True, v

    def _fill(self, deadline, nonblock_ok=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if not nonblock_ok:
                return False
            remaining = 0.0
        self.sock.settimeout(remaining if remaining > 0 else 0.0)
        try:
            data = self.sock.recv(1 << 20)
        except (socket.timeout, BlockingIOError):
            return False
        if not data:
            raise RespError("connection closed by server")
        if self.pos:
            self.buf = self.buf[self.pos:] + data
            self.pos = 0
        else:
            self.buf += data
        return True

    # ----------------------------------------------------------------- public
    def send(self, *args):
        self.sock.sendall(encode(*args))

    def send_raw(self, data):
        self.sock.sendall(data)

    def read(self, timeout=None):
        """Next non-push reply. Pushes met on the way are queued."""
        deadline = time.monotonic() + (self.default_timeout if timeout is None else timeout)
        while True:
            ok, v = self._try_one()
            if ok:
                if isinstance(v, Push):
                    self.pushes.append((time.monotonic(), v))
                    continue
                return v
            if not self._fill(deadline):
                raise RespError("timeout waiting for reply on port %d (%s)" % (self.port, self.name))

    def call(self, *args, timeout=None):
        self.send(*args)
        return self.read(timeout)

    def pipeline(self, cmds, timeout=None):
        self.sock.sendall(b"".join(encode(*c) for c in cmds))
        return [self.read(timeout) for _ in cmds]

    def poll_pushes(self, timeout=0.0):
        """Collect pushes (and, in RESP2 subscriber mode, plain arrays) for up to timeout s.
        Returns the list of newly collected frames."""
        deadline = time.monotonic() + timeout
        got = []
        first = True
        while True:
            ok, v = self._try_one()
            if ok:
                if isinstance(v, Push):
                    self.pushes.append((time.monotonic(), v))
                got.append(v)
                continue
            if not self._fill(deadline, nonblock_ok=first):
                return got
            first = False

    def read_frames_until_quiet(self, quiet=0.5, max_total=10.0):
        """Collect frames until no frame arrives for `quiet` seconds (or max_total)."""
        start = time.monotonic()
        frames = []
        last = time.monotonic()
        while True:
            now = time.monotonic()
            if now - start > max_total:
                return frames
            wait = min(quiet - (now - last), max_total - (now - start))
            if wait <= 0:
                return frames
            got = self.poll_pushes(wait)
            if got:
                frames.extend(got)
                last = time.monotonic()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def b2s(v):
    if isinstance(v, bytes):
        return v.decode(errors="replace")
    if isinstance(v, list):
        return [b2s(x) for x in v]
    return v


def info_dict(conn, section=None):
    raw = conn.call("INFO", section) if section else conn.call("INFO")
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    out = {}
    for line in raw.split("\r\n"):
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k] = v
    return out
