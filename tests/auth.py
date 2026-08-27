#!/usr/bin/env python3
"""Directed requirepass/AUTH compatibility test. Usage: tests/auth.py HOST PORT"""

import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
BOOT_PASSWORD = sys.argv[3].encode() if len(sys.argv) > 3 else b""


class RespError(Exception):
    pass


def frame(*args):
    values = [arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.file = self.sock.makefile("rb")

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        kind = self.file.read(1)
        if not kind:
            raise EOFError("server closed")
        line = self.file.readline()
        assert line.endswith(b"\r\n"), line
        value = line[:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if kind == b":":
            return int(value)
        if kind == b"_":
            return None
        if kind == b"#":
            return value == b"t"
        if kind in (b",", b"("):
            return value
        if kind in (b"$", b"=", b"!"):
            size = int(value)
            if size == -1:
                return None
            data = self.file.read(size)
            assert self.file.read(2) == b"\r\n"
            if kind == b"!":
                return RespError(data.decode("utf-8", "replace"))
            return data
        if kind in (b"*", b"~", b">"):
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        if kind in (b"%", b"|"):
            count = int(value)
            return {self.read(): self.read() for _ in range(count)}
        raise AssertionError("unknown RESP prefix %r" % kind)

    def close(self):
        self.file.close()
        self.sock.close()


def expect(actual, wanted, label):
    if isinstance(wanted, str) and isinstance(actual, RespError):
        actual = str(actual)
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


admin = Conn()
if BOOT_PASSWORD:
    expect(admin.command("PING"), "NOAUTH Authentication required.", "boot password gate")
    expect(admin.command("AUTH", BOOT_PASSWORD), b"OK", "boot password AUTH")
expect(admin.command("CONFIG", "SET", "requirepass", b""), b"OK", "start disabled")
registry = admin.command("COMMAND")
if not isinstance(registry, list) or not registry:
    raise AssertionError("COMMAND registry unavailable: %r" % (registry,))

expect(admin.command("CONFIG", "GET", "protected-mode"),
       [b"protected-mode", b"yes"], "protected-mode default")
expect(admin.command("CONFIG", "SET", "protected-mode", "0"), b"OK", "protected-mode live 0")
expect(admin.command("CONFIG", "GET", "protected-mode"),
       [b"protected-mode", b"no"], "protected-mode normalized no")
expect(admin.command("CONFIG", "SET", "protected-mode", "1"), b"OK", "protected-mode live 1")
expect(admin.command("PING"), b"PONG", "disabled PING")
expect(admin.command("AUTH", "anything"),
       "ERR AUTH <password> called without any password configured for the default user. Are you sure your configuration is correct?",
       "disabled one-argument AUTH")
expect(admin.command("AUTH", "default", "anything"), b"OK", "nopass ACL-form AUTH")
expect(admin.command("RESET"), b"RESET", "RESET under nopass")

# Authentication is initialized at connection creation. Redis deliberately keeps an already-open,
# nopass connection authenticated when requirepass is enabled later.
nopass_latched = Conn()
expect(nopass_latched.command("PING"), b"PONG", "nopass connection works")

password = b"s3cr\x00et"
expect(admin.command("CONFIG", "SET", "requirepass", password), b"OK", "live enable")
expect(admin.command("PING"), b"PONG", "setter connection remains authenticated")
expect(nopass_latched.command("PING"), b"PONG", "pre-existing nopass auth is latched")

unauth = Conn()
expect(unauth.command("PING"), "NOAUTH Authentication required.", "new connection gate")
# The unknown-command reply carries the command name and the first arguments (t-edgeproto made it
# byte-exact against redis 7.4); what this row is about is that it comes out AHEAD of NOAUTH.
expect(unauth.command("NOSUCHCOMMAND"),
       "ERR unknown command 'NOSUCHCOMMAND', with args beginning with: ",
       "unknown precedes NOAUTH")
expect(unauth.command("GET"),
       "ERR wrong number of arguments for 'get' command", "arity precedes NOAUTH")
expect(unauth.command("AUTH", "a", "b", "c"),
       "ERR wrong number of arguments for 'auth' command", "AUTH arity")
expect(unauth.command("AUTH", b"s3cr\x00eX"),
       "WRONGPASS invalid username-password pair or user is disabled.", "wrong password")
expect(unauth.command("AUTH", "nobody", password),
       "WRONGPASS invalid username-password pair or user is disabled.", "wrong username")
expect(unauth.command("HELLO", "2"),
       "NOAUTH HELLO must be called with the client already authenticated, otherwise the HELLO <proto> AUTH <user> <pass> option can be used to authenticate the client and select the RESP protocol version at the same time",
       "HELLO requires credentials")
expect(unauth.command("HELLO", "2", "AUTH", "default", b"wrong"),
       "WRONGPASS invalid username-password pair or user is disabled.", "HELLO wrong password")
expect(unauth.command("HELLO", "3", "AUTH", "default", b"wrong"),
       "WRONGPASS invalid username-password pair or user is disabled.",
       "HELLO 3 authenticates before protocol selection")
expect(unauth.command("PING"), "NOAUTH Authentication required.",
       "failed HELLO 3 leaves RESP2 and unauthenticated")
expect(unauth.command("HELLO", "abc"),
       "ERR Protocol version is not an integer or out of range", "HELLO noninteger")
expect(unauth.command("HELLO", "2", "AUTH", "default"),
       "ERR Syntax error in HELLO option 'AUTH'", "HELLO short AUTH")
expect(unauth.command("HELLO", "2", "BOGUS"),
       "ERR Syntax error in HELLO option 'BOGUS'", "HELLO unknown option")
hello = unauth.command("HELLO", "2", "AUTH", "default", password)
if not isinstance(hello, list) or hello[:6] != [b"server", b"redis", b"version", b"0.1-cpp", b"proto", 2]:
    raise AssertionError("HELLO AUTH reply: %r" % (hello,))
expect(unauth.command("PING"), b"PONG", "HELLO authenticated connection")
expect(unauth.command("AUTH", b"wrong"),
       "WRONGPASS invalid username-password pair or user is disabled.", "failed re-auth reply")
expect(unauth.command("PING"), b"PONG", "failed re-auth preserves prior authentication")
expect(unauth.command("CONFIG", "GET", "requirepass"),
       [b"requirepass", password], "CONFIG GET requirepass")
if password in unauth.command("CLIENT", "LIST"):
    raise AssertionError("requirepass leaked through CLIENT LIST")
if password in unauth.command("CLIENT", "INFO"):
    raise AssertionError("requirepass leaked through CLIENT INFO")

expect(unauth.command("RESET"), b"RESET", "RESET reply")
expect(unauth.command("PING"), "NOAUTH Authentication required.", "RESET deauthenticates")
expect(unauth.command("AUTH", "default", password), b"OK", "ACL-form AUTH")

# HELLO defers protocol/name changes until credentials succeed and repeated AUTH uses the last pair.
hello_edges = Conn()
expect(hello_edges.command("HELLO", "2", "AUTH", "default", b"wrong",
                           "AUTH", "default", password, "SETNAME", "hello-edge")[:2],
       [b"server", b"redis"], "HELLO repeated AUTH last wins")
expect(hello_edges.command("CLIENT", "GETNAME"), b"hello-edge", "HELLO SETNAME applied")

proto = Conn()
hello3 = proto.command("HELLO", "3", "AUTH", "default", password)
if not isinstance(hello3, dict) or hello3.get(b"server") != b"redis" or hello3.get(b"proto") != 3:
    raise AssertionError("HELLO 3 AUTH reply: %r" % (hello3,))
expect(proto.command("PING"), b"PONG", "HELLO 3 authenticated connection")

# Iterate every registered command at valid minimum arity. Only AUTH/HELLO/QUIT/RESET may escape
# the pre-dispatch NOAUTH gate; command syntax is intentionally irrelevant after arity validation.
allowed = {b"auth", b"hello", b"quit", b"reset"}
for info in registry:
    name, arity = info[0], abs(info[1])
    probe = Conn()
    reply = probe.command(name, *([b"x"] * (arity - 1)))
    if name not in allowed:
        expect(reply, "NOAUTH Authentication required.", "pre-auth registry %s" % name.decode())
    probe.close()

# Unauthenticated parser allocation limits reject >10 multibulk elements and >16KiB bulks.
too_many = Conn()
too_many.sock.sendall(frame("MGET", *(["k"] * 10)))
if not isinstance(too_many.read(), RespError):
    raise AssertionError("unauthenticated multibulk limit did not reject")
too_many.close()
too_large = Conn()
too_large.sock.sendall(frame("AUTH", b"x" * 16385))
if not isinstance(too_large.read(), RespError):
    raise AssertionError("unauthenticated bulk limit did not reject")
too_large.close()

hardening = Conn()
expect(hardening.command("AUTH", password), b"OK", "hardening AUTH")
expect(hardening.command("MGET", *(["k"] * 10)), [None] * 10,
       "authenticated multibulk >10")
expect(hardening.command("SET", "large-auth", b"v" * 16385), b"OK",
       "authenticated bulk >16KiB")

# A non-reading peer generating multi-megabyte HELLO errors must trip the unauthenticated 1KiB
# userspace output-buffer ceiling once the kernel send queue fills.
slow = Conn()
slow.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
slow.sock.sendall(frame("HELLO", "2") * 20000)
time.sleep(0.1)
slow.sock.settimeout(2)
closed = False
try:
    for _ in range(20001):
        slow.read()
except socket.timeout:
    pass
except (EOFError, ConnectionError, OSError):
    closed = True
if not closed:
    raise AssertionError("unauthenticated output-buffer ceiling did not close the client")
slow.close()

stats = unauth.command("INFO", "STATS")
if b"auth_failures:" not in stats or b"auth_failures:0\r\n" in stats:
    raise AssertionError("auth_failures counter did not fire: %r" % stats)

# Rotating a password gates new/unauthenticated clients but preserves already-authenticated ones,
# matching Redis ACL credential changes.
expect(unauth.command("CONFIG", "SET", "requirepass", b"rotated"), b"OK", "live rotate")
expect(unauth.command("PING"), b"PONG", "existing authentication survives rotation")
fresh = Conn()
expect(fresh.command("AUTH", password),
       "WRONGPASS invalid username-password pair or user is disabled.", "old credential rejected")
expect(fresh.command("AUTH", b"rotated"), b"OK", "new credential accepted")
expect(fresh.command("CONFIG", "SET", "requirepass", b""), b"OK", "restore disabled")

# RESET under nopass re-latches authentication, so a later live enable does not retroactively gate.
reset_nopass = Conn()
expect(reset_nopass.command("RESET"), b"RESET", "nopass RESET relatches auth")
expect(fresh.command("CONFIG", "SET", "requirepass", b"last-pass"), b"OK", "final live enable")
expect(reset_nopass.command("PING"), b"PONG", "nopass RESET latch survives enable")
expect(fresh.command("CONFIG", "SET", "requirepass", b""), b"OK", "final restore disabled")

for connection in (reset_nopass, fresh, hardening, proto, hello_edges, unauth,
                   nopass_latched, admin):
    connection.close()
print("auth: PASS (registry gate, SHA auth, HELLO ordering, latching, limits, counters)")
