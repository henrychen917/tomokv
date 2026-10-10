#!/usr/bin/env python3
"""Round-4 ACL reproductions, with owned listeners and bounded state witnesses.

Adapted from round4-read cmd-complex/{acl_probes,capacity_unrun,extended_probes}.py and
server-atomics/t16_acl_wake.py. Each case is one gate row per thread mode; every expectation is
Redis 7.4.10's reply (run any case with --oracle against the vanilla binary). No rate measurement.

  sort          CC4.8   SORT_RO/SORT BY/GET option checks, their order and ACL LOG side effects
  streams-name  CC4.9   XREADGROUP with a group named STREAMS admits no outside stream
  save-load     CC4.10  whitespace/NUL patterns refused; ACL SAVE output always reloads
  capacity      CC4.24  65535 create/delete pairs, then creation, the live-slot ceiling and stop
  wake-pop      AT4.4   a woken pop denied by a revoked key/command leaves its element
  wake-scatter  AT4.6   a woken BLMOVE/BRPOPLPUSH/XREAD/XREADGROUP denial moves/delivers nothing
"""
import argparse
import contextlib
import json
from pathlib import Path
import resource
import socket
import subprocess
import time
import traceback

from _lib import Conn, RespError, encode
from _client_wait import wait_client_state


DENIED = RespError(b"NOPERM No permissions to access a key")
CASES = ("sort", "streams-name", "save-load", "capacity", "wake-pop", "wake-scatter")


def check(got, want, label):
    assert got == want, f"{label}: got {got!r}, expected {want!r}"


@contextlib.contextmanager
def connection(port):
    client = Conn("127.0.0.1", port, timeout=5)
    try:
        yield client
    finally:
        client.close()


def sort_option(name):
    return RespError(b"ERR %s option of SORT denied due to insufficient ACL permissions." % name)


def acl_log_total(admin):
    """Denials ACL LOG recorded: the sum of every entry's aggregated count."""
    return sum(dict(zip(entry[::2], entry[1::2]))[b"count"] for entry in admin.cmd("ACL", "LOG"))


def stat(admin, name):
    for line in admin.cmd("INFO", "stats").splitlines():
        if line.startswith(name + b":"):
            return int(line.split(b":", 1)[1])
    raise AssertionError(f"INFO stats has no {name!r}")


def sort_case(admin, port, _args):
    # Every expectation below is Redis 7.4.10's reply (docs/aclfix/oracle/sort). sort.c parses
    # options left to right and answers its first error; a user without unrestricted key access
    # may not reach GET or a '*' BY pattern. Declared keys (the source, SORT's last STORE target)
    # are checked first, by the ordinary ACL check, and answer NOPERM.
    check(admin.cmd("RPUSH", "allowed:list", "a"), 1, "source")
    check(admin.cmd("RPUSH", "denied:list", "x"), 1, "forbidden source")
    check(admin.cmd("SET", "other:a", "secret"), b"OK", "secret")
    check(admin.cmd("ACL", "SETUSER", "sorter", "on", "nopass", "~allowed:*",
                    "+sort_ro", "+sort", "+get"), b"OK", "sort user")
    integer = RespError(b"ERR value is not an integer or out of range")
    syntax = RespError(b"ERR syntax error")
    both = (
        (("BY", "nosort", "GET", "other:*"), sort_option(b"GET")),
        (("BY", "other:*"), sort_option(b"BY")),
        (("GET", "#"), sort_option(b"GET")),
        (("ALPHA", "DESC", "GET", "#"), sort_option(b"GET")),
        (("LIMIT", 0, 1, "BY", "nosort", "GET", "other:*"), sort_option(b"GET")),
        (("BY", "get"), [b"a"]),
        (("BY", "nosort"), [b"a"]),
        (("LIMIT", "x", 1, "GET", "#"), integer),
        (("LIMIT", "01", 1, "GET", "#"), integer),
        (("FOO", "GET", "#"), syntax),
        (("GET",), syntax),
    )
    options = ([("SORT_RO", case) for case in both] + [("SORT", case) for case in both] + [
        ("SORT_RO", (("STORE", "allowed:dst", "GET", "#"), syntax)),
        ("SORT", (("STORE", "allowed:dst", "GET", "#"), sort_option(b"GET"))),
        ("SORT", (("BY", "store", "LIMIT", 0, 1), [b"a"])),
    ])
    keys = (
        ("SORT_RO", "denied:list", "GET", "#"),
        ("SORT", "denied:list", "GET", "#"),
        ("SORT", "allowed:list", "STORE", "other:dst", "GET", "#"),
        ("SORT", "allowed:list", "GET", "#", "STORE", "other:dst"),
    )
    failures = []
    with connection(port) as user:
        check(user.cmd("AUTH", "sorter", "x"), b"OK", "AUTH")
        check(admin.cmd("ACL", "LOG", "RESET"), b"OK", "empty ACL LOG")
        denied_keys = stat(admin, b"acl_access_denied_key")
        for command, (arguments, want) in options:
            got = user.cmd(command, "allowed:list", *arguments)
            print(command, arguments, repr(got), flush=True)
            if got != want:
                failures.append((command, arguments, got, want))
        # An option error is sort.c's own reply: no ACL LOG entry, no ACL denial counter.
        logged = (acl_log_total(admin), stat(admin, b"acl_access_denied_key") - denied_keys)
        print("option denials logged", logged, flush=True)
        if logged != (0, 0):
            failures.append(("option denials reached ACL LOG/INFO", logged))
        check(user.cmd("GET", "other:a"), DENIED, "direct GET")
        for argv in keys:
            got = user.cmd(*argv)
            print(argv, repr(got), flush=True)
            if got != DENIED:
                failures.append((argv, got, DENIED))
        logged = (acl_log_total(admin), stat(admin, b"acl_access_denied_key") - denied_keys)
        print("key denials logged", logged, flush=True)
        if logged != (1 + len(keys), 1 + len(keys)):
            failures.append(("each key denial is logged once", logged))
    assert not failures, failures


def streams_case(admin, port, _args):
    check(admin.cmd("XADD", "secret:stream", "1-0", "f", "v"), b"1-0", "entry")
    check(admin.cmd("XGROUP", "CREATE", "secret:stream", "STREAMS", "0"), b"OK", "group")
    check(admin.cmd("ACL", "SETUSER", "reader", "on", "nopass", "~consumer", "~STREAMS",
                    "+xreadgroup", "+xrange"), b"OK", "reader")
    with connection(port) as user:
        check(user.cmd("AUTH", "reader", "x"), b"OK", "AUTH")
        check(user.cmd("XRANGE", "secret:stream", "-", "+"), DENIED, "direct XRANGE")
        got = user.cmd("XREADGROUP", "GROUP", "STREAMS", "consumer", "STREAMS", "secret:stream", ">")
        pending = admin.cmd("XPENDING", "secret:stream", "STREAMS")
        print("XREADGROUP", repr(got), "pending", repr(pending), flush=True)
        check(got, DENIED, "group named STREAMS")
        check(pending[0], 0, "denied admission must not add PEL entries")


def save_case(admin, _port, args):
    failures = []
    for prefix in (b"~", b"&"):
        for separator in (b" ", b"\t", b"\n", b"\r", b"\v", b"\f", b"\0"):
            rule = prefix + b"key" + separator + b"with-space"
            check(admin.cmd("ACL", "SETUSER", "spaced", "reset", "on", "nopass", "+get"),
                  b"OK", "fresh pattern state")
            before = admin.cmd("ACL", "GETUSER", "spaced")
            got = admin.cmd("ACL", "SETUSER", "spaced", rule)
            # Redis formats the invalid modifier with %s, truncating at NUL.
            shown = rule.split(b"\0")[0].replace(b"\r", b" ").replace(b"\n", b" ")
            want = RespError(b"ERR Error in ACL SETUSER modifier '" + shown +
                             b"': Syntax error")
            print("invalid pattern", repr(rule), repr(got), flush=True)
            if got != want or admin.cmd("ACL", "GETUSER", "spaced") != before:
                failures.append((rule, got, want))
    # Preserve the existing selector refusal. Both forms must reject atomically;
    # an unsupported selector must never get persisted as a partly applied rule.
    for selector in ('(~"key with space" +get)', '(&"channel with space" +subscribe)'):
        before = admin.cmd("ACL", "GETUSER", "spaced")
        got = admin.cmd("ACL", "SETUSER", "spaced", selector)
        assert isinstance(got, RespError), (selector, got)
        check(admin.cmd("ACL", "GETUSER", "spaced"), before, "invalid selector atomicity")
        print("invalid selector", repr(got), flush=True)
    check(admin.cmd("ACL", "DELUSER", "spaced"), 1, "remove invalid-pattern control")
    # Quotes and backslashes are legal literal pattern bytes in Redis ACL files.
    check(admin.cmd("ACL", "SETUSER", "roundtrip", "on", "nopass", "+get",
                    '~a"b', "~a'b", r"~a\b", '&a"b', "&a'b", r"&a\b"), b"OK", "legal patterns")
    before = admin.cmd("ACL", "GETUSER", "roundtrip")
    check(admin.cmd("ACL", "SAVE"), b"OK", "ACL SAVE")
    contents = args.aclfile.read_bytes()
    print("saved", repr(contents), flush=True)
    got = admin.cmd("ACL", "LOAD")
    print("reload", repr(got), flush=True)
    if got != b"OK" or admin.cmd("ACL", "GETUSER", "roundtrip") != before:
        failures.append(("roundtrip", got))
    # A rejected file retains the complete live image.
    args.aclfile.write_bytes(b"user default on nopass ~* &* +@all\nuser broken bogusrule\n")
    assert isinstance(admin.cmd("ACL", "LOAD"), RespError)
    check(admin.cmd("ACL", "GETUSER", "roundtrip"), before, "failed LOAD retains live image")
    assert not failures, failures


def capacity_case(admin, port, args):
    deadline = time.monotonic() + 45
    for base in range(0, 65535, 256):
        count = min(256, 65535 - base)
        admin.raw(b"".join(encode(*command) for _ in range(count) for command in
                           (("ACL", "SETUSER", "temporary", "on"),
                            ("ACL", "DELUSER", "temporary"))))
        for i in range(count):
            check(admin.read(), b"OK", f"create {base+i}")
            check(admin.read(), 1, f"delete {base+i}")
        assert time.monotonic() < deadline, "churn exceeded 45 seconds"
    first = admin.cmd("ACL", "SETUSER", "fresh", "on")
    second = admin.cmd("ACL", "SETUSER", "fresh2", "on")
    print("65535 create/delete pairs; extra creations:", repr(first), repr(second), flush=True)
    # Read both replies before asserting, so PRE also exercises the failing
    # creation's second advance and the shutdown array overrun under ASAN.
    check(first, b"OK", "first creation after churn")
    check(second, b"OK", "second creation after churn")
    # Exercise actual allocation failure too: reuse alone would otherwise hide
    # the original high-water/shutdown overrun. Redis has no 65536 live-slot cap.
    for base in range(0, 65533, 256):
        count = min(256, 65533 - base)
        admin.raw(b"".join(encode("ACL", "SETUSER", f"cap:{i}", "on")
                           for i in range(base, base + count)))
        for i in range(count):
            check(admin.read(), b"OK", f"fill slot {base+i}")
        assert time.monotonic() < deadline, "capacity setup exceeded 45 seconds"
    expected = b"OK" if args.oracle else RespError(b"ERR out of memory")
    check(admin.cmd("ACL", "SETUSER", "overflow1", "on"), expected, "first full-slot creation")
    check(admin.cmd("ACL", "SETUSER", "overflow2", "on"), expected, "second full-slot creation")
    print("live-slot boundary: two exact", repr(expected), "replies", flush=True)
    for base in range(0, 65533, 256):
        names = [f"cap:{i}" for i in range(base, min(65533, base + 256))]
        check(admin.cmd("ACL", "DELUSER", *names), len(names), "free full-slot users")
        assert time.monotonic() < deadline, "capacity cleanup exceeded 45 seconds"
    # A deleted authenticated user's handle must not name a new account.
    check(admin.cmd("ACL", "SETUSER", "held", "on", "nopass", "~*", "+@all"), b"OK", "held user")
    with connection(port) as old:
        check(old.cmd("AUTH", "held", "x"), b"OK", "held AUTH")
        ident = old.cmd("CLIENT", "ID")
        check(admin.cmd("ACL", "DELUSER", "held"), 1, "held delete")
        check(admin.cmd("ACL", "SETUSER", "replacement", "on", "nopass", "~*", "+@all"),
              b"OK", "replacement")
        wait_client_state(admin, ident, "gone", timeout=3)


def parked(admin, user, command, oracle):
    ident = user.cmd("CLIENT", "ID")
    user.send(*command)
    wait_client_state(admin, ident, "blocked", timeout=3)
    if not oracle:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            fields = dict(line.split(b":", 1) for line in admin.cmd("INFO").splitlines()
                          if b":" in line and not line.startswith(b"#"))
            if int(fields.get(b"blocking_waiters", 0)) >= 1:
                return
            time.sleep(.001)
        raise AssertionError("owner waiter registration never appeared")


def wake_case(admin, port, args):
    if args.case == "wake-pop":
        cases = [("BLPOP", ["BLPOP", "src", "0"], False),
                 ("BRPOP", ["BRPOP", "src", "0"], False),
                 ("BZPOPMIN", ["BZPOPMIN", "src", "0"], True),
                 ("BZPOPMAX", ["BZPOPMAX", "src", "0"], True),
                 ("BLMPOP", ["BLMPOP", "0", "1", "src", "LEFT"], False),
                 ("BZMPOP", ["BZMPOP", "0", "1", "src", "MIN"], True)]
    else:
        cases = [("BLMOVE", ["BLMOVE", "src", "dst", "LEFT", "LEFT", "0"], False),
                 ("BRPOPLPUSH", ["BRPOPLPUSH", "src", "dst", "0"], False),
                 ("XREAD", ["XREAD", "BLOCK", "0", "STREAMS", "src", "0"], False),
                 ("XREADGROUP", ["XREADGROUP", "GROUP", "g", "c", "BLOCK", "0",
                                 "STREAMS", "src", ">"], False)]
    failures = []
    check(admin.cmd("ACL", "LOG", "RESET"), b"OK", "empty ACL LOG")
    for name, command, zset in cases:
        for revoke in ("key", "command"):
            admin.cmd("DEL", "src", "dst")
            check(admin.cmd("ACL", "SETUSER", "woken", "reset", "on", "nopass", "~*", "+@all"),
                  b"OK", "fresh wake user")
            if name == "XREADGROUP":
                check(admin.cmd("XGROUP", "CREATE", "src", "g", "0", "MKSTREAM"), b"OK", "group")
            with connection(port) as user:
                check(user.cmd("AUTH", "woken", "x"), b"OK", "wake AUTH")
                parked(admin, user, command, args.oracle)
                rule = ("resetkeys", "~nothing:*") if revoke == "key" else ("-" + name.lower(),)
                check(admin.cmd("ACL", "SETUSER", "woken", *rule), b"OK", "revoke acknowledged")
                if name.startswith("XREAD"):
                    check(admin.cmd("XADD", "src", "1-0", "f", "v"), b"1-0", "stream wake")
                elif zset:
                    check(admin.cmd("ZADD", "src", "1", "v"), 1, "zset wake")
                else:
                    check(admin.cmd("RPUSH", "src", "v"), 1, "list wake")
                got = user.read()
                # The following PING is a reply fence: a duplicate NOPERM or stale
                # data/null frame cannot silently shift this connection's stream.
                check(user.cmd("PING"), b"PONG", "one reply per wake")
                want = DENIED if revoke == "key" else RespError(
                    f"NOPERM User woken has no permissions to run the '{name.lower()}' command")
                if name.startswith("XREAD"):
                    remaining = admin.cmd("XRANGE", "src", "-", "+")
                    expected = [[b"1-0", [b"f", b"v"]]]
                elif zset:
                    remaining = admin.cmd("ZRANGE", "src", 0, -1)
                    expected = [b"v"]
                else:
                    remaining = admin.cmd("LRANGE", "src", 0, -1)
                    expected = [b"v"]
                destination = admin.cmd("LRANGE", "dst", 0, -1)
                pending = admin.cmd("XPENDING", "src", "g")[0] if name == "XREADGROUP" else 0
                print(name, revoke, "reply", repr(got), "src", repr(remaining),
                      "dst", repr(destination), "pending", pending, flush=True)
                if got != want or remaining != expected or destination != [] or pending != 0:
                    failures.append((name, revoke, got, remaining, destination, pending))
    # One check per woken command: exactly one ACL LOG record per denial, never a second one
    # from a retire-time recheck of the same command.
    logged = acl_log_total(admin)
    print("woken denials logged", logged, "of", 2 * len(cases), flush=True)
    if logged != 2 * len(cases):
        failures.append(("one ACL LOG record per woken denial", logged, 2 * len(cases)))
    assert not failures, failures


@contextlib.contextmanager
def listener(args):
    args.output.mkdir(parents=True, exist_ok=True)
    args.aclfile = args.output.resolve() / "users.acl"
    args.aclfile.write_text("user default on nopass ~* &* +@all\n")
    with socket.socket() as guard:
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        guard.bind(("127.0.0.1", args.port))
    command = ["taskset", "-c", args.cores, str(Path(args.binary).resolve()), "--bind", "127.0.0.1",
               "--port", str(args.port), "--save", "", "--appendonly", "no",
               "--dir", str(args.output.resolve()), "--aclfile", str(args.aclfile)]
    if not args.oracle:
        command += ["--shards", "16", "--thread-mode", args.mode,
                    "--read-local", "1" if args.mode == "1s" else "0"]
        if args.mode == "2s":
            command += ["--ratio", args.ratio]
    print(json.dumps({"command": command, "case": args.case}), flush=True)
    with (args.output / "server.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            # The gate's own boots allow 30 s on a shared box; a quick server exits the loop early.
            deadline = time.monotonic() + 30
            while True:
                assert process.poll() is None, (args.output / "server.log").read_text()
                try:
                    with connection(args.port) as client:
                        check(client.cmd("PING"), b"PONG", "boot")
                    break
                except (ConnectionRefusedError, TimeoutError):
                    assert time.monotonic() < deadline, "boot deadline"
                    time.sleep(.02)
            yield
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
                raise AssertionError("SIGTERM did not finish in eight seconds")
            # A reaped exit status of 0 after SIGTERM is the clean stop (CC4.24's PRE dies with
            # SIGSEGV here). A post-stop connect probe was dropped: on this shared box it can only
            # observe a foreign listener on the reused port, never this process.
            print("SIGTERM exit", process.returncode, flush=True)
            assert process.returncode == 0, (args.output / "server.log").read_text()[-12000:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cores", required=True)
    parser.add_argument("--mode", choices=("1s", "2s"), default="2s")
    parser.add_argument("--ratio", default="6:2", help="2s io:ex ratio (the gate's GATE_RATIO)")
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--oracle", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    start = time.monotonic()
    try:
        with listener(args), connection(args.port) as admin:
            {"sort": sort_case, "streams-name": streams_case, "save-load": save_case,
             "capacity": capacity_case, "wake-pop": wake_case,
             "wake-scatter": wake_case}[args.case](admin, args.port, args)
    except Exception:
        traceback.print_exc()
        print(f"aclfix {args.case} FAIL ({time.monotonic()-start:.3f}s)", flush=True)
        return 1
    print(f"aclfix {args.case} PASS ({time.monotonic()-start:.3f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
