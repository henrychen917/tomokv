#!/usr/bin/env python3
"""Directed Redis 7.4 ACL grammar, enforcement, closure, and persistence gate.

Usage: tests/acl.py HOST PORT ACLFILE
"""

import glob
import os
import socket
import sys
import threading
import time


HOST, PORT, ACLFILE = sys.argv[1], int(sys.argv[2]), sys.argv[3]


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
        if not line.endswith(b"\r\n"):
            raise EOFError("truncated reply")
        value = line[:-2]
        if kind == b"+":
            return value
        if kind == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            data = self.file.read(size)
            assert self.file.read(2) == b"\r\n"
            return data
        if kind == b"*":
            count = int(value)
            return None if count == -1 else [self.read() for _ in range(count)]
        raise AssertionError("unknown RESP prefix %r" % kind)

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()


def expect(actual, wanted, label):
    if isinstance(wanted, str) and isinstance(actual, RespError):
        actual = str(actual)
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


def fields(reply):
    assert isinstance(reply, list) and len(reply) == 12, reply
    return {reply[i]: reply[i + 1] for i in range(0, len(reply), 2)}


def stats(conn):
    body = conn.command("INFO", "STATS")
    result = {}
    for line in body.split(b"\r\n"):
        if b":" in line:
            key, value = line.split(b":", 1)
            if value.isdigit():
                result[key] = int(value)
    return result


def wait_closed(conn, timeout=6):
    conn.sock.settimeout(0.2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn.read()
        except socket.timeout:
            continue
        except (EOFError, ConnectionError, OSError):
            return
    raise AssertionError("connection was not closed by ACL revocation")


admin = Conn()
if ACLFILE == "-":
    nofile = ("ERR This Redis instance is not configured to use an ACL file. You may want to "
              "specify users via the ACL SETUSER command and then issue a CONFIG REWRITE "
              "(assuming you have a Redis configuration file set) in order to store users in "
              "the Redis configuration.")
    expect(admin.command("ACL", "LOAD"), nofile, "ACL LOAD without aclfile")
    expect(admin.command("ACL", "SAVE"), nofile, "ACL SAVE without aclfile")
    admin.close()
    print("acl: PASS (no-aclfile errors)")
    raise SystemExit(0)

expect(admin.command("ACL", "WHOAMI"), b"default", "default WHOAMI")
for username in admin.command("ACL", "USERS"):
    if username != b"default":
        admin.command("ACL", "DELUSER", username)

expect(admin.command("CONFIG", "GET", "acl-pubsub-default"),
       [b"acl-pubsub-default", b"resetchannels"], "pubsub ACL default")
expect(admin.command("ACL", "SETUSER", "channel-default"), b"OK", "new default-channel user")
expect(fields(admin.command("ACL", "GETUSER", "channel-default"))[b"channels"], b"",
       "new user resetchannels")
expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "allchannels"), b"OK",
       "live pubsub ACL default")
expect(admin.command("ACL", "SETUSER", "channel-all"), b"OK", "new allchannels user")
expect(fields(admin.command("ACL", "GETUSER", "channel-all"))[b"channels"], b"&*",
       "new user allchannels")
expect(admin.command("ACL", "DELUSER", "channel-default", "channel-all"), 2,
       "delete channel-default probes")
expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "resetchannels"), b"OK",
       "restore pubsub ACL default")

password = b"s3cr\x00et"
rules = [
    "on", b">" + password, "resetkeys", "~*", "resetchannels", "&news.*",
    "-@all", "+get", "+set", "+mget", "+mset", "+multi", "+exec",
    "+blpop", "+lpush", "+subscribe", "+unsubscribe", "+psubscribe",
    "+punsubscribe", "+ssubscribe", "+sunsubscribe", "+publish", "+spublish",
    "+eval", "+evalsha",
]
expect(admin.command("ACL", "SETUSER", "alice", *rules), b"OK", "SETUSER grammar")

alice_info = fields(admin.command("ACL", "GETUSER", "alice"))
if alice_info[b"flags"] != [b"on", b"sanitize-payload"]:
    raise AssertionError("flags/order: %r" % alice_info[b"flags"])
if len(alice_info[b"passwords"]) != 1 or len(alice_info[b"passwords"][0]) != 64:
    raise AssertionError("password hash shape: %r" % alice_info[b"passwords"])
expect(alice_info[b"keys"], b"~*", "GETUSER keys")
expect(alice_info[b"channels"], b"&news.*", "GETUSER channels")
expect(alice_info[b"selectors"], [], "GETUSER selectors")

listed = admin.command("ACL", "LIST")
if listed != sorted(listed) or not listed[0].startswith(b"user alice "):
    raise AssertionError("ACL LIST ordering/shape: %r" % listed)
expect(admin.command("ACL", "USERS"), [b"alice", b"default"], "USERS ordering")

expect(admin.command("ACL", "SETUSER", "bad-rw", "%R~cache:*"),
       "ERR Error in ACL SETUSER modifier '%R~cache:*': Read/write key patterns are not supported until command key specifications are available",
       "%R rule rejected")
expect(admin.command("ACL", "SETUSER", "bad-selector", "(~*", "+get", ")"),
       "ERR Error in ACL SETUSER modifier '(~*': ACL selectors are not supported",
       "selector rejected")
expect(admin.command("ACL", "SETUSER", "bad-firstarg", "+select|0"),
       "ERR Error in ACL SETUSER modifier '+select|0': Allowing first-arg of a subcommand is not supported",
       "first-arg rule rejected")

alice = Conn()
expect(alice.command("AUTH", "alice", password), b"OK", "multi-user AUTH")
expect(alice.command("ACL", "WHOAMI"),
       "NOPERM User alice has no permissions to run the 'acl' command", "ACL command bit")
expect(alice.command("AUTH", "default", "anything"), b"OK", "AUTH identity switch")
expect(alice.command("ACL", "WHOAMI"), b"default", "WHOAMI after default switch")
expect(alice.command("HELLO", "2", "AUTH", "alice", password)[:2],
       [b"server", b"redis"], "HELLO AUTH multi-user")

expect(admin.command("SET", "a:1", "A"), b"OK", "seed a")
expect(admin.command("SET", "b:1", "B"), b"OK", "seed b")
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~a:*"), b"OK",
       "restrict keys")
expect(alice.command("GET", "a:1"), b"A", "allowed GET")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key", "denied GET")
expect(alice.command("MGET", "a:1", "b:1"),
       "NOPERM No permissions to access a key", "denied key inside MGET")
expect(alice.command("MSET", "a:2", "x", "b:2", "y"),
       "NOPERM No permissions to access a key", "denied key inside MSET")
expect(admin.command("GET", "a:2"), None, "denied MSET is atomic at admission")
expect(alice.command("EVAL", "return redis.call('GET',KEYS[1])", 1, "a:1"),
       "NOPERM User alice has no permissions to run the 'eval' command", "Lua v1 deny")

# Queue-time denial dirties EXEC; a later permission change is instead a per-element EXEC error.
expect(alice.command("MULTI"), b"OK", "MULTI queue-time")
expect(alice.command("GET", "b:1"), "NOPERM No permissions to access a key",
       "queue-time ACL denial")
expect(alice.command("EXEC"),
       "EXECABORT Transaction discarded because of previous errors.", "queue-time EXECABORT")

expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~*"), b"OK",
       "open keys before EXEC")
expect(alice.command("MULTI"), b"OK", "MULTI recheck")
expect(alice.command("GET", "a:1"), b"QUEUED", "queue allowed a")
expect(alice.command("GET", "b:1"), b"QUEUED", "queue allowed b")
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~a:*"), b"OK",
       "revoke between MULTI and EXEC")
exec_reply = alice.command("EXEC")
expect(exec_reply[0], b"A", "EXEC partial allowed element")
expect(exec_reply[1],
       "NOPERM ACLs rules changed between the moment the transaction was accumulated and the EXEC call. This command is no longer allowed for the following reason: no permission to touch the specified keys",
       "EXEC per-element ACL recheck")

# Blocking completion must consult the current immutable permission blob, not its admission copy.
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~block:*"), b"OK",
       "allow blocking key")
blocked = Conn()
expect(blocked.command("AUTH", "alice", password), b"OK", "blocking AUTH")
blocking_reply = []
thread = threading.Thread(target=lambda: blocking_reply.append(
    blocked.command("BLPOP", "block:k", 0)))
thread.start()
time.sleep(0.25)
expect(admin.command("ACL", "SETUSER", "alice", "resetkeys", "~other:*"), b"OK",
       "revoke blocked key")
expect(admin.command("LPUSH", "block:k", "value"), 1, "wake blocked command")
thread.join(5)
expect(blocking_reply[0], "NOPERM No permissions to access a key", "blocking recheck")

# Three subscription namespaces and both publish forms share one channel-pattern namespace.
expect(admin.command("ACL", "SETUSER", "alice", "resetchannels", "&news.*"), b"OK",
       "restore channels")
expect(alice.command("PUBLISH", "other", "x"),
       "NOPERM No permissions to access a channel", "PUBLISH channel check")
expect(alice.command("SPUBLISH", "other", "x"),
       "NOPERM No permissions to access a channel", "SPUBLISH channel check")

sub = Conn(); expect(sub.command("AUTH", "alice", password), b"OK", "SUBSCRIBE AUTH")
expect(sub.command("SUBSCRIBE", "news.a"), [b"subscribe", b"news.a", 1], "SUBSCRIBE allow")
sub.send("UNSUBSCRIBE", "other")
unsub = sub.read()
if unsub[:2] != [b"unsubscribe", b"other"]:
    raise AssertionError("UNSUBSCRIBE channel exemption: %r" % (unsub,))
sub.close()

psub = Conn(); expect(psub.command("AUTH", "alice", password), b"OK", "PSUBSCRIBE AUTH")
expect(psub.command("PSUBSCRIBE", "news.*"), [b"psubscribe", b"news.*", 1],
       "PSUBSCRIBE literal allow")
psub.close()
psub_bad = Conn(); expect(psub_bad.command("AUTH", "alice", password), b"OK", "PSUB bad AUTH")
expect(psub_bad.command("PSUBSCRIBE", "news.a*"),
       "NOPERM No permissions to access a channel", "PSUBSCRIBE literal deny")
psub_bad.close()

ssub = Conn(); expect(ssub.command("AUTH", "alice", password), b"OK", "SSUBSCRIBE AUTH")
expect(ssub.command("SSUBSCRIBE", "news.a"), [b"ssubscribe", b"news.a", 1],
       "SSUBSCRIBE same namespace")
ssub.close()

# Revocation is an exact all-IO sweep: one violating subscribed client, one counted kill.
revoked = Conn(); expect(revoked.command("AUTH", "alice", password), b"OK", "revocation AUTH")
expect(revoked.command("SUBSCRIBE", "news.a"), [b"subscribe", b"news.a", 1],
       "revocation subscribe")
killed_before = stats(admin)[b"acl_pubsub_clients_killed"]
expect(admin.command("ACL", "SETUSER", "alice", "resetchannels", "&other"), b"OK",
       "channel revoke")
wait_closed(revoked)
killed_after = stats(admin)[b"acl_pubsub_clients_killed"]
expect(killed_after, killed_before + 1, "exact pubsub revocation count")

# SAVE is the LIST serializer plus one LF per sorted user, using temp+fsync+rename.
expect(admin.command("ACL", "SAVE"), b"OK", "ACL SAVE")
with open(ACLFILE, "rb") as handle:
    saved = handle.read()
expected_save = b"".join(line + b"\n" for line in admin.command("ACL", "LIST"))
expect(saved, expected_save, "SAVE byte-identical to LIST serializer")
if glob.glob(ACLFILE + ".tmp-*"):
    raise AssertionError("ACL SAVE left a temp file")

# LOAD accepts leading comments, aggregates errors, and leaves the old registry untouched.
before_bad_load = admin.command("ACL", "LIST")
with open(ACLFILE, "wb") as handle:
    handle.write(b"# accepted comment\nuser good on nopass ~* &* +@all\n"
                 b"user broken on ~* +nosuchcommand\n")
load_error = admin.command("ACL", "LOAD")
if not isinstance(load_error, RespError) or "nosuchcommand" not in str(load_error) or not str(load_error).endswith(
        "WARNING: ACL errors detected, no change to the previously active ACL rules was performed"):
    raise AssertionError("LOAD aggregate error: %r" % load_error)
expect(admin.command("ACL", "LIST"), before_bad_load, "LOAD all-or-nothing")

with open(ACLFILE, "wb") as handle:
    handle.write(b"# comments are deliberately not preserved\n" + saved)
expect(admin.command("ACL", "LOAD"), b"OK", "LOAD saved grammar")
expect(admin.command("ACL", "LIST"), before_bad_load, "SETUSER->LIST->SAVE->LOAD round trip")

# Removing a user through LOAD closes all of that user's connections, subscribed or otherwise.
deleted_user = Conn(); expect(deleted_user.command("AUTH", "alice", password), b"OK", "LOAD delete AUTH")
default_line = next(line for line in before_bad_load if line.startswith(b"user default "))
with open(ACLFILE, "wb") as handle:
    handle.write(default_line + b"\n")
expect(admin.command("ACL", "LOAD"), b"OK", "LOAD removes user")
wait_closed(deleted_user)

for bits, chars in ((1, 1), (256, 64), (4096, 1024)):
    generated = admin.command("ACL", "GENPASS", bits)
    if len(generated) != chars or any(c not in b"0123456789abcdef" for c in generated):
        raise AssertionError("GENPASS %d: %r" % (bits, generated))
expect(admin.command("ACL", "GENPASS", 0),
       "ERR ACL GENPASS argument must be the number of bits for the output password, a positive number up to 4096",
       "GENPASS zero")

final_stats = stats(admin)
for counter in (b"acl_access_denied_cmd", b"acl_access_denied_key",
                b"acl_access_denied_channel", b"acl_pubsub_clients_killed",
                b"acl_perm_retired"):
    if final_stats.get(counter, 0) == 0:
        raise AssertionError("ACL counter did not fire: %s=%r" % (counter, final_stats.get(counter)))

for connection in (blocked, alice, admin):
    connection.close()
print("acl: PASS (grammar, AUTH, key/command/channel matrix, EXEC/blocking closure, revocation, SAVE/LOAD)")
