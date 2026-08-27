"""Minimal RESP client used by the edgeenc probes."""
import socket


class RespError(Exception):
    """Value equality on purpose.

    Exception's default __eq__ is identity, so two structurally identical error replies from the
    two servers compared UNEQUAL and every error-bearing op counted as a diff. That defect in this
    harness manufactured hundreds of phantom diffs before it was caught.
    """

    def __eq__(self, other):
        return isinstance(other, RespError) and self.args == other.args

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("RespError",) + self.args)


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        elif isinstance(a, int):
            a = str(a).encode()
        out.extend((f"${len(a)}\r\n".encode(), a, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.f = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def read(self):
        p = self.f.read(1)
        if not p:
            raise EOFError("server closed the connection")
        line = self.f.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError(f"bad RESP line {p+line!r}")
        v = line[:-2]
        if p == b"+":
            return v
        if p == b"-":
            return RespError(v.decode("utf-8", "replace"))
        if p == b":":
            return int(v)
        if p == b"$":
            n = int(v)
            if n == -1:
                return None
            body = self.f.read(n + 2)
            return body[:-2]
        if p == b"*":
            n = int(v)
            if n == -1:
                return None
            return [self.read() for _ in range(n)]
        if p == b"%":
            n = int(v)
            return {  # RESP3 map
                self._key(self.read()): self.read() for _ in range(n)
            }
        if p in (b"~", b">"):
            return [self.read() for _ in range(int(v))]
        if p == b"#":
            return v == b"t"
        if p == b",":
            return float(v)
        if p == b"_":
            return None
        raise AssertionError(f"unknown RESP prefix {p!r}")

    @staticmethod
    def _key(k):
        return k if not isinstance(k, (bytes, bytearray)) else bytes(k)

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
