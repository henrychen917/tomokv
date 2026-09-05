#!/usr/bin/env python3
"""ACL recheck over a CODED reply: exactly one reply per blocking command.

Usage: aclreply.py HOST PORT

WHAT THIS COVERS
----------------
A blocking command is rechecked against the live ACL when it retires
(blocking.inc blocking_retire -> acl.inc acl_recheck_blocking), because the
user's permissions can change while the client is parked.  When the recheck
denies, the reply the command already produced is DISCARDED and a NOPERM error
is put in its place.  "Discarded" has to mean every representation of that
reply, and reply codes added a second one.

    BLPOP k 1        ->  times out  ->  "*-1\\r\\n"   (RESP2)
                                        "_\\r\\n"     (RESP3)

Both are ReplyCode-carried (src/exec/op.h): the executor records a code and the
connection's owner formats the bytes at retire.  A discard written as

    op.reply.clear();

empties the byte buffer, which for a coded reply was already empty, and leaves
reply_code_ standing.  Retire then emits the coded reply AND the NOPERM behind
it -- two replies for one command, which shifts every later reply on that
connection by one.  The fix is Op::clear_reply(), which drops the bytes, the
direct length and the code together.

Verified against a negative-control build (this tree with that one line reverted
to op.reply.clear()): the two timeout rows below fail there with

    b"*-1\\r\\n-NOPERM User u has no permissions to run the 'blpop' command\\r\\n"
    b"_\\r\\n-NOPERM User u has no permissions to run the 'blpop' command\\r\\n"

and every other row passes, so this test discriminates exactly the defect.

Note this shape does NOT exist before reply codes: the blocking dispatch branch
in io_loop.h returns before the direct-reply arming, so a blocking op always has
direct_len == 0 and the byte-only discard was sufficient.  The coded reply is
the first representation op.reply.clear() could miss.

THE ORACLE IS THE BYTES.  Each row reads the victim's socket to quiescence and
compares the whole stream to the single expected error frame, so a second reply
fails as trailing garbage rather than being averaged away.
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7899

FAILURES = []


def encode(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        out += b"$%d\r\n%s\r\n" % (len(b), b)
    return out


def drain(sock, quiet=1.2):
    """Read until the socket has been silent for a beat; returns everything seen."""
    sock.setblocking(False)
    buf = b""
    deadline = time.time() + quiet
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            deadline = time.time() + 0.3
        except BlockingIOError:
            time.sleep(0.04)
    sock.setblocking(True)
    return buf


def connect(resp3=False):
    s = socket.create_connection((HOST, PORT), timeout=10)
    if resp3:
        s.sendall(encode("HELLO", "3"))
        drain(s, 0.6)
    return s


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        FAILURES.append(name)
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))


def main():
    admin = connect()
    admin.sendall(encode("ACL", "SETUSER", "u", "on", ">p", "~*", "&*", "+@all"))
    drain(admin, 0.6)

    def trial(name, blocking_argv, revoke_argv, wake_argv, expect, resp3=False):
        # Full reset, not just +@all: an earlier row revokes KEYS, and leaving that in
        # place made every later row read a key denial instead of the reply under test.
        admin.sendall(encode("ACL", "SETUSER", "u", "on", ">p",
                             "resetkeys", "~*", "resetchannels", "&*", "+@all"))
        drain(admin, 0.5)
        admin.sendall(encode("DEL", "aclr:list", "aclr:zset"))
        drain(admin, 0.5)

        victim = connect(resp3)
        victim.sendall(encode("AUTH", "u", "p"))
        drain(victim, 0.5)
        # Quiesce first: the command must be the head of its own parse pass with
        # nothing staged, which is the state the direct region and the ROB-head
        # barrier both want. Pipelining it would change the geometry.
        time.sleep(1.0)

        victim.sendall(encode(*blocking_argv))
        time.sleep(0.6)                      # let it park
        admin.sendall(encode(*revoke_argv))  # revoke while parked
        drain(admin, 0.5)
        time.sleep(0.25)
        if wake_argv:
            admin.sendall(encode(*wake_argv))
            drain(admin, 0.5)

        got = drain(victim, 3.0)
        victim.close()
        check(name, got, expect)

    noperm_cmd = (b"-NOPERM User u has no permissions to run the '%s' command\r\n")

    print("== 1. TIMEOUT: the reply is a CODED null, and the discard must drop the code")
    # These two are the discriminating rows: the timeout reply is *-1 / _, both coded.
    trial("BLPOP timeout, command revoked (RESP2)",
          ("BLPOP", "aclr:list", "1"), ("ACL", "SETUSER", "u", "-blpop"), None,
          noperm_cmd % b"blpop")
    trial("BLPOP timeout, command revoked (RESP3)",
          ("BLPOP", "aclr:list", "1"), ("ACL", "SETUSER", "u", "-blpop"), None,
          noperm_cmd % b"blpop", resp3=True)
    trial("BZPOPMIN timeout, command revoked (RESP2)",
          ("BZPOPMIN", "aclr:zset", "1"), ("ACL", "SETUSER", "u", "-bzpopmin"), None,
          noperm_cmd % b"bzpopmin")
    trial("BLMPOP timeout, command revoked (RESP3)",
          ("BLMPOP", "1", "1", "aclr:list", "LEFT"),
          ("ACL", "SETUSER", "u", "-blmpop"), None,
          noperm_cmd % b"blmpop", resp3=True)

    print("== 2. WOKEN: the reply is real data, and the discard must drop the bytes")
    # NEGATIVE CONTROLS for section 1: same denial, but the reply being discarded is
    # a byte reply rather than a coded one. These passed before reply codes too, so a
    # regression that broke only the coded path still shows up as a section-1-only fail.
    trial("BLPOP woken then command revoked (RESP2)",
          ("BLPOP", "aclr:list", "0"), ("ACL", "SETUSER", "u", "-blpop"),
          ("LPUSH", "aclr:list", "v"), noperm_cmd % b"blpop")
    trial("BLPOP woken then command revoked (RESP3)",
          ("BLPOP", "aclr:list", "0"), ("ACL", "SETUSER", "u", "-blpop"),
          ("LPUSH", "aclr:list", "v"), noperm_cmd % b"blpop", resp3=True)
    trial("BZPOPMIN woken then command revoked",
          ("BZPOPMIN", "aclr:zset", "0"), ("ACL", "SETUSER", "u", "-bzpopmin"),
          ("ZADD", "aclr:zset", "1", "m"), noperm_cmd % b"bzpopmin")
    trial("BLPOP woken then KEY revoked",
          ("BLPOP", "aclr:list", "0"),
          ("ACL", "SETUSER", "u", "resetkeys", "~nothing:*"),
          ("LPUSH", "aclr:list", "v"),
          b"-NOPERM No permissions to access a key\r\n")

    print("== 3. STILL PERMITTED: the recheck must not disturb an allowed reply")
    trial("BLPOP timeout, still permitted (RESP2)",
          ("BLPOP", "aclr:list", "1"), ("ACL", "SETUSER", "u", "+@all"), None,
          b"*-1\r\n")
    trial("BLPOP timeout, still permitted (RESP3)",
          ("BLPOP", "aclr:list", "1"), ("ACL", "SETUSER", "u", "+@all"), None,
          b"_\r\n", resp3=True)
    trial("BLPOP woken, still permitted",
          ("BLPOP", "aclr:list", "0"), ("ACL", "SETUSER", "u", "+@all"),
          ("LPUSH", "aclr:list", "v"),
          b"*2\r\n$9\r\naclr:list\r\n$1\r\nv\r\n")

    # Leave no ACL user behind: a live non-default user is what makes acl_active() true,
    # so a leaked one changes the regime for every later battery sharing this boot.
    admin.sendall(encode("ACL", "DELUSER", "u"))
    drain(admin, 0.5)
    admin.close()
    if FAILURES:
        print("aclreply: %d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("aclreply: all rows ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
