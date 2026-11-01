"""Minimal RESP2 client for black-box reproductions (no third-party deps).

Replies:
  simple string -> Status(str)   error -> Err(str)   integer -> int
  bulk -> bytes                  nil bulk ($-1) -> NIL_BULK
  array -> list                  null array (*-1) -> NIL_ARRAY
"""
import select
import socket
import time


class Status(str):
    pass


class Err(str):
    pass


class _Nil:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name

    def __bool__(self):
        return False


NIL_BULK = _Nil('NIL_BULK($-1)')
NIL_ARRAY = _Nil('NIL_ARRAY(*-1)')


class Timeout(Exception):
    pass


def encode(args):
    out = [b'*%d\r\n' % len(args)]
    for a in args:
        if isinstance(a, bytes):
            b = a
        elif isinstance(a, int):
            b = str(a).encode()
        else:
            b = str(a).encode()
        out.append(b'$%d\r\n%s\r\n' % (len(b), b))
    return b''.join(out)


class Conn:
    def __init__(self, port, host='127.0.0.1', timeout=10.0):
        self.port = port
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b''
        self.default_timeout = timeout

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

    # ---- sending -------------------------------------------------------
    def send(self, *args):
        self.s.sendall(encode(args))

    def send_many(self, cmds):
        """Pipeline several commands in ONE sendall (one TCP write)."""
        self.s.sendall(b''.join(encode(c) for c in cmds))

    # ---- parsing -------------------------------------------------------
    def _fill(self, deadline):
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise Timeout()
            r, _, _ = select.select([self.s], [], [], remaining)
            if not r:
                raise Timeout()
            chunk = self.s.recv(1 << 16)
            if not chunk:
                raise ConnectionError('server closed connection')
            self.buf += chunk
            return

    def _line(self, pos, deadline):
        while True:
            i = self.buf.find(b'\r\n', pos)
            if i >= 0:
                return i
            self._fill(deadline)

    def _parse(self, pos, deadline):
        """Return (value, newpos); may call _fill."""
        while len(self.buf) <= pos:
            self._fill(deadline)
        t = self.buf[pos:pos + 1]
        e = self._line(pos, deadline)
        line = self.buf[pos + 1:e]
        nxt = e + 2
        if t == b'+':
            return Status(line.decode()), nxt
        if t == b'-':
            return Err(line.decode(errors='replace')), nxt
        if t == b':':
            return int(line), nxt
        if t == b'$':
            n = int(line)
            if n < 0:
                return NIL_BULK, nxt
            while len(self.buf) < nxt + n + 2:
                self._fill(deadline)
            return self.buf[nxt:nxt + n], nxt + n + 2
        if t == b'*':
            n = int(line)
            if n < 0:
                return NIL_ARRAY, nxt
            items = []
            p = nxt
            for _ in range(n):
                v, p = self._parse(p, deadline)
                items.append(v)
            return items, p
        if t == b'_':
            return NIL_BULK, nxt
        raise ValueError('unexpected RESP type %r in %r' % (t, self.buf[pos:pos + 64]))

    def read(self, timeout=None):
        """Read one reply. timeout=None -> default; raises Timeout (buffer kept)."""
        if timeout is None:
            timeout = self.default_timeout
        deadline = time.monotonic() + timeout
        v, p = self._parse(0, deadline)
        self.buf = self.buf[p:]
        return v

    def try_read(self, timeout):
        """Return (True, reply) or (False, None) on timeout; never loses bytes."""
        try:
            return True, self.read(timeout)
        except Timeout:
            return False, None

    def cmd(self, *args, timeout=None):
        self.send(*args)
        return self.read(timeout)

    def pipeline(self, cmds, timeout=None):
        self.send_many(cmds)
        return [self.read(timeout) for _ in cmds]


def info_field(conn, section, field):
    raw = conn.cmd('INFO', section)
    if isinstance(raw, Err):
        raise RuntimeError('INFO failed: %s' % raw)
    for line in raw.decode().split('\r\n'):
        if line.startswith(field + ':'):
            return line.split(':', 1)[1]
    return None


def blocked_clients(conn):
    v = info_field(conn, 'clients', 'blocked_clients')
    return int(v) if v is not None else -1


def wait_blocked(conn, want, timeout=3.0, step=0.0005):
    """Poll INFO clients until blocked_clients == want. Returns True on success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if blocked_clients(conn) == want:
            return True
        time.sleep(step)
    return False


def show(v):
    """Compact printable form of a reply."""
    if isinstance(v, bytes):
        return v.decode(errors='replace')
    if isinstance(v, Err):
        return '(error) ' + v
    if isinstance(v, Status):
        return '+' + v
    if isinstance(v, list):
        return '[' + ', '.join(show(x) for x in v) + ']'
    return repr(v)
