#!/usr/bin/env python3
"""Exactly one Redis-compatible reply per blocking command after ACL changes.

Timeout is a null reply on Redis even after revocation. TomoKV's retire-time
NOPERM is a named known difference (ACL-REVOKED-TIMEOUT), never proof of parity.
Read through an ECHO fence so doubled coded/null/error replies always fail.
Woken commands still require the exact denial and permitted commands their data.
"""
import socket
import sys
import time

from _lib import Conn
from known_difference import expect as known_expect
from _client_wait import wait_client_state

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7899

FAILURES = []


def encode(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        out += b"$%d\r\n%s\r\n" % (len(b), b)
    return out


def raw_reply(file):
    """Preserve one complete RESP frame; buffered reads may span any TCP split."""
    line = file.readline()
    assert line and line.endswith(b"\r\n"), ("truncated RESP line", line)
    kind = line[:1]
    if kind == b"$":
        size = int(line[1:-2])
        if size >= 0:
            body = file.read(size + 2)
            assert len(body) == size + 2 and body[-2:] == b"\r\n", "truncated bulk"
            line += body
    elif kind in (b"*", b"%", b">"):
        count = max(0, int(line[1:-2])) * (2 if kind == b"%" else 1)
        line += b"".join(raw_reply(file) for _ in range(count))
    else:
        assert kind in (b"+", b"-", b":", b"_", b"#"), line
    return line


def check(name, got, want):
    if got == want:
        print("  ok   %s" % name)
    else:
        FAILURES.append(name)
        print("  FAIL %s\n         got  %r\n         want %r" % (name, got, want))


def main():
    admin = Conn(HOST, PORT, timeout=10)
    assert admin.cmd("ACL", "SETUSER", "u", "on", ">p", "~*", "&*", "+@all") == b"OK"

    def trial(name, blocking_argv, revoke_argv, wake_argv, expect, resp3=False, known=None):
        budget = time.monotonic() + 10
        timeout_s = float(blocking_argv[1] if blocking_argv[0] == "BLMPOP" else blocking_argv[-1])
        while True:
            assert time.monotonic() < budget, "blocking/revocation window never opened: " + name
            # A scheduling miss gets an entirely new connection and no stale ACL/key state.
            assert admin.cmd("ACL", "SETUSER", "u", "on", ">p", "resetkeys", "~*",
                             "resetchannels", "&*", "+@all") == b"OK"
            admin.cmd("DEL", "aclr:list", "aclr:zset")
            victim = Conn(HOST, PORT, timeout=10)
            try:
                if resp3:
                    victim.cmd("HELLO", "3")
                assert victim.cmd("AUTH", "u", "p") == b"OK"
                client_id = victim.cmd("CLIENT", "ID")
                armed_at = time.monotonic()
                victim.send(*blocking_argv)
                try:
                    wait_client_state(admin, client_id, "blocked", timeout=min(5, budget - armed_at))
                except AssertionError as error:
                    if (timeout_s and time.monotonic() - armed_at >= timeout_s and
                            "never became blocked" in str(error)):
                        print("  INVALID fresh timeout arm: " + name, flush=True)
                        continue
                    raise
                assert admin.cmd(*revoke_argv) == b"OK"
                if timeout_s and time.monotonic() - armed_at >= timeout_s:
                    print("  INVALID timeout elapsed before revocation acknowledgement: " + name,
                          flush=True)
                    continue
                # From here, a wrong reply is a failure, never an excuse to retry.
                if wake_argv:
                    reply = admin.cmd(*wake_argv)
                    assert isinstance(reply, int) and reply > 0, reply
                marker = ("aclreply-fence:%d" % client_id).encode()
                victim.send("ECHO", marker)
                marker_frame = b"$%d\r\n%s\r\n" % (len(marker), marker)
                got = b""
                while True:
                    frame = raw_reply(victim.file)
                    if frame == marker_frame:
                        break
                    got += frame
                if known is None:
                    check(name, got, expect)
                else:
                    known_expect(got, expect, root="ACL-REVOKED-TIMEOUT: " + name, known=known)
                break
            finally:
                victim.close()

    noperm_cmd = (b"-NOPERM User u has no permissions to run the '%s' command\r\n")

    print("== 1. TIMEOUT: Redis returns one null even after revocation")
    for verb, argv, resp3 in (
            ('blpop', ('BLPOP', 'aclr:list', '1'), False),
            ('blpop', ('BLPOP', 'aclr:list', '1'), True),
            ('bzpopmin', ('BZPOPMIN', 'aclr:zset', '1'), False),
            ('blmpop', ('BLMPOP', '1', '1', 'aclr:list', 'LEFT'), True)):
        trial(f'{verb} timeout revoked RESP{3 if resp3 else 2}', argv,
              ('ACL', 'SETUSER', 'u', '-' + verb), None,
              b'_\r\n' if resp3 else b'*-1\r\n', resp3=resp3,
              known=noperm_cmd % verb.encode())

    print("== 2. WOKEN: the reply is real data, and the discard must drop the bytes")
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
    assert admin.cmd("ACL", "DELUSER", "u") == 1
    admin.close()
    if FAILURES:
        print("aclreply: %d FAILURES: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("aclreply: all rows ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
