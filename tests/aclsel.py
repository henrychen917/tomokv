#!/usr/bin/env python3
"""Directed Redis 7.4 ACL selector parsing, reporting, and enforcement battery.

Usage: tests/aclsel.py HOST PORT
"""

import select
import socket
import sys
import threading
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
CHECKS = 0


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
    global CHECKS
    CHECKS += 1
    if isinstance(wanted, str) and isinstance(actual, RespError):
        actual = str(actual)
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


def fields(reply):
    if not isinstance(reply, list) or len(reply) != 12:
        raise AssertionError("GETUSER shape: %r" % (reply,))
    return {reply[index]: reply[index + 1] for index in range(0, len(reply), 2)}


def selector_fields(reply):
    result = []
    for selector in reply:
        if not isinstance(selector, list) or len(selector) != 6:
            raise AssertionError("selector shape: %r" % (selector,))
        result.append({selector[index]: selector[index + 1]
                       for index in range(0, len(selector), 2)})
    return result


def stats(conn):
    body = conn.command("INFO", "STATS")
    result = {}
    for line in body.split(b"\r\n"):
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        if value.isdigit():
            result[key] = int(value)
    return result


def wait_closed(conn, timeout=6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        readable, _, _ = select.select([conn.sock], [], [], 0.2)
        if not readable:
            continue
        try:
            if conn.sock.recv(1, socket.MSG_PEEK) == b"":
                return
        except (ConnectionError, OSError):
            return
    raise AssertionError("selector channel revocation did not close subscriber")


admin = Conn()
is_tomokv = b"tomokv_version:" in admin.command("INFO", "SERVER")
for username in ("aclsel", "aclsel-bad", "aclsel-default"):
    admin.command("ACL", "DELUSER", username)
before = stats(admin)

expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "allchannels"), b"OK",
       "arm selector channel default")
expect(admin.command("ACL", "SETUSER", "aclsel-default", "reset", "on", "nopass", "()"),
       b"OK", "empty selector with allchannels default")
default_selector = selector_fields(
    fields(admin.command("ACL", "GETUSER", "aclsel-default"))[b"selectors"])
expect(default_selector[0][b"channels"], b"&*", "selector inherits allchannels default")
expect(admin.command("ACL", "DELUSER", "aclsel-default"), 1,
       "remove selector-default probe")
expect(admin.command("CONFIG", "SET", "acl-pubsub-default", "resetchannels"), b"OK",
       "restore selector channel default")

for key, value in (("sel:a:1", "A"), ("sel:b:1", "B"), ("sel:root:1", "R"),
                   ("sel:cat:1", "CAT")):
    expect(admin.command("SET", key, value), b"OK", "seed " + key)

# One packed selector and one fragmented across RESP arguments prove both parser paths fired.
rules = (
    "reset", "on", "nopass", "-@all", "resetkeys", "resetchannels",
    "(~sel:a:* +get +strlen +mget)",
    "(", "~sel:b:*", "+set", ")",
    "(&sel:news:* +publish)",
    "(&sel:sub:* +subscribe +unsubscribe)",
)
expect(admin.command("ACL", "SETUSER", "aclsel", *rules), b"OK", "selector grammar")

info = fields(admin.command("ACL", "GETUSER", "aclsel"))
selectors = selector_fields(info[b"selectors"])
expect(selectors, [
    {b"commands": b"-@all +get +strlen +mget", b"keys": b"~sel:a:*", b"channels": b""},
    {b"commands": b"-@all +set", b"keys": b"~sel:b:*", b"channels": b""},
    {b"commands": b"-@all +publish", b"keys": b"", b"channels": b"&sel:news:*"},
    {b"commands": b"-@all +subscribe +unsubscribe", b"keys": b"",
     b"channels": b"&sel:sub:*"},
], "GETUSER selector rows")
expected_list = (
    b"user aclsel on nopass sanitize-payload resetchannels -@all "
    b"(~sel:a:* resetchannels -@all +get +strlen +mget) "
    b"(~sel:b:* resetchannels -@all +set) "
    b"(resetchannels &sel:news:* -@all +publish) "
    b"(resetchannels &sel:sub:* -@all +subscribe +unsubscribe)"
)
listed = next(row for row in admin.command("ACL", "LIST") if row.startswith(b"user aclsel "))
expect(listed, expected_list, "ACL LIST selector serialization")

expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(on +get)"),
       "ERR Error in ACL SETUSER modifier '(on +get)': Syntax error",
       "selector rejects user flags")
expect(admin.command("ACL", "GETUSER", "aclsel-bad"), None,
       "invalid selector is all-or-nothing")
expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(~x:*", "+get"),
       "ERR Unmatched parenthesis in acl selector starting at '(~x:*'.",
       "unmatched selector error")
expect(admin.command("ACL", "SETUSER", "aclsel-bad", "reset", "(~x:* +eval)"),
       ("ERR Error in ACL SETUSER modifier '(~x:* +eval)': Script commands in ACL selectors "
        "require allcommands") if is_tomokv else b"OK",
       "unsafe script selector fail-closed policy")

user = Conn()
expect(user.command("AUTH", "aclsel", "unused"), b"OK", "selector user AUTH")

# Selector grants, negative controls, and denial-reason precedence.
expect(user.command("GET", "sel:a:1"), b"A", "selector GET grant")
expect(user.command("SET", "sel:b:2", "B2"), b"OK", "selector SET grant")
expect(user.command("GET", "sel:b:1"), "NOPERM No permissions to access a key",
       "GET command exists but no complete set matches key")
expect(user.command("SET", "sel:a:2", "A2"), "NOPERM No permissions to access a key",
       "SET command exists but no complete set matches key")
expect(user.command("DEL", "sel:a:1"),
       "NOPERM User aclsel has no permissions to run the 'del' command",
       "selector command denial")
expect(user.command("MGET", "sel:a:1"), [b"A"], "selector MGET grant")
expect(user.command("MGET", "sel:a:1", "sel:b:1"),
       "NOPERM No permissions to access a key", "selector MGET key denial")
expect(user.command("PUBLISH", "sel:news:x", "payload"), 0, "selector channel grant")
expect(user.command("PUBLISH", "sel:other", "payload"),
       "NOPERM No permissions to access a channel", "selector channel denial")

# Root and selectors are alternatives, never bags of independently composable permissions.
expect(admin.command("ACL", "SETUSER", "aclsel", "~sel:root:*", "+get", "allchannels"),
       b"OK", "add root permission set")
expect(user.command("GET", "sel:root:1"), b"R", "root permission grant")
expect(user.command("GET", "sel:a:1"), b"A", "selector remains an alternative")
expect(user.command("PUBLISH", "sel:other", "payload"),
       "NOPERM No permissions to access a channel", "root channel cannot mix with selector command")
expect(admin.command("ACL", "SETUSER", "aclsel", "(~sel:b:* +mget)"), b"OK",
       "add second MGET selector")
expect(user.command("MGET", "sel:b:1"), [b"B"], "second selector MGET grant")
expect(user.command("MGET", "sel:a:1", "sel:b:1"),
       "NOPERM No permissions to access a key", "multi-key request cannot mix selectors")

# Command categories and exclusions apply inside a selector exactly as in the root set.
expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors",
                     "(~sel:cat:* +@string -set)"), b"OK", "selector command category")
expect(user.command("GET", "sel:cat:1"), b"CAT", "selector category GET")
expect(user.command("STRLEN", "sel:cat:1"), 3, "selector category STRLEN")
expect(user.command("SET", "sel:cat:2", "x"),
       "NOPERM User aclsel has no permissions to run the 'set' command",
       "selector category exclusion")
expect(user.command("GET", "sel:a:1"), "NOPERM No permissions to access a key",
       "root command and selector key cannot mix")

# EXEC rechecks the current immutable selector image, rather than the queued image.
expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass", "~*",
                     "resetchannels", "-@all", "+multi", "+exec",
                     "(~sel:a:* +get)"), b"OK", "transaction selector setup")
expect(user.command("MULTI"), b"OK", "selector transaction MULTI")
expect(user.command("GET", "sel:a:1"), b"QUEUED", "selector transaction queue")
expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors"), b"OK",
       "revoke queued selector")
exec_reply = user.command("EXEC")
if not isinstance(exec_reply, list) or len(exec_reply) != 1:
    raise AssertionError("selector EXEC reply shape: %r" % (exec_reply,))
expect(exec_reply[0],
       "NOPERM ACLs rules changed between the moment the transaction was accumulated and the EXEC "
       "call. This command is no longer allowed for the following reason: no permission to execute "
       "the command or subcommand",
       "selector EXEC recheck")

# Blocking completion also rechecks selectors after wakeup.
expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass", "~*",
                     "resetchannels", "-@all", "(~sel:block:* +blpop)"), b"OK",
       "blocking selector setup")
admin.command("DEL", "sel:block:k")
expect(admin.command("EXISTS", "sel:block:k"), 0, "blocking key clean slate")
blocked = Conn()
expect(blocked.command("AUTH", "aclsel", "unused"), b"OK", "blocking selector AUTH")
blocking_reply = []
thread = threading.Thread(target=lambda: blocking_reply.append(
    blocked.command("BLPOP", "sel:block:k", 0)))
thread.start()
time.sleep(0.25)
expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors",
                     "(~sel:other:* +blpop)"), b"OK", "revoke blocking selector key")
expect(admin.command("LPUSH", "sel:block:k", "value"), 1, "wake selector BLPOP")
thread.join(5)
if not blocking_reply:
    raise AssertionError("selector BLPOP did not finish")
expect(blocking_reply[0], "NOPERM No permissions to access a key", "selector blocking recheck")

# A selector-backed subscription survives unrelated root edits, then closes on selector removal.
expect(admin.command("ACL", "SETUSER", "aclsel", "reset", "on", "nopass",
                     "resetkeys", "-@all", "resetchannels",
                     "(&sel:sub:* +subscribe +unsubscribe)"), b"OK",
       "subscription selector setup")
subscriber = Conn()
expect(subscriber.command("AUTH", "aclsel", "unused"), b"OK", "subscriber selector AUTH")
expect(subscriber.command("SUBSCRIBE", "sel:sub:x"),
       [b"subscribe", b"sel:sub:x", 1], "selector SUBSCRIBE grant")
ordinary = Conn()
expect(ordinary.command("AUTH", "aclsel", "unused"), b"OK", "ordinary control AUTH")
killed_before = stats(admin).get(b"acl_pubsub_clients_killed")
expect(admin.command("ACL", "SETUSER", "aclsel", "~sel:root:*", "+get"), b"OK",
       "unrelated root update preserves selector")
expect(admin.command("PUBLISH", "sel:sub:x", "still-open"), 1,
       "preserved subscriber receiver count")
expect(subscriber.read(), [b"message", b"sel:sub:x", b"still-open"],
       "preserved selector subscriber delivery")
if is_tomokv:
    expect(stats(admin)[b"acl_pubsub_clients_killed"], killed_before,
           "preservation control kills zero subscribers")
expect(admin.command("ACL", "SETUSER", "aclsel", "clearselectors"), b"OK",
       "clear subscription selector")
wait_closed(subscriber)
if is_tomokv:
    expect(stats(admin)[b"acl_pubsub_clients_killed"], killed_before + 1,
           "selector revocation kills exactly one subscriber")
expect(ordinary.command("GET", "sel:root:1"), b"R",
       "selector revocation leaves ordinary connection open")

# RESET and CLEARSELECTORS affect selectors without leaking into the root permission set.
expect(admin.command("ACL", "SETUSER", "aclsel", "(~sel:a:* +get)"), b"OK",
       "re-add selector before reset")
expect(admin.command("ACL", "SETUSER", "aclsel", "reset"), b"OK", "reset user")
expect(fields(admin.command("ACL", "GETUSER", "aclsel"))[b"selectors"], [],
       "reset clears selectors")

after = stats(admin)
minimum_deltas = {
    b"acl_access_denied_cmd": 3,
    b"acl_access_denied_key": 5,
    b"acl_access_denied_channel": 2,
}
if is_tomokv:
    minimum_deltas[b"acl_pubsub_clients_killed"] = 1
for counter, minimum in minimum_deltas.items():
    delta = after.get(counter, 0) - before.get(counter, 0)
    if delta < minimum:
        raise AssertionError("selector mechanism did not fire: %s delta=%d wanted>=%d" %
                             (counter.decode(), delta, minimum))

admin.command("ACL", "DELUSER", "aclsel", "aclsel-bad", "aclsel-default")
for connection in (blocked, ordinary, user, admin):
    connection.close()
print("aclsel: PASS (%d checks; parsing/reporting/root+selector/key/channel/command/EXEC/BLPOP/revocation fired)" % CHECKS)
