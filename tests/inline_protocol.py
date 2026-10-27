#!/usr/bin/env python3
"""NET-INLINE-1: exact wire bytes AND connection lifetime against Redis 7.4.10.

Connects only. Each endpoint must independently match explicit expected bytes;
agreement between two broken implementations cannot pass. No timing/rate claim.
"""
import argparse
from contextlib import closing

from _lib import Conn, encode
from respcompat import Case, run_case, PING, PONG, PREFIX


def bulk(value):
    return b"$%d\r\n" % len(value) + value + b"\r\n"


def cases():
    rows = []

    def echo(name, argument, expected):
        for ending in (b"\n", b"\r\n"):
            rows.append(Case(name + repr(ending),
                             ((b"ECHO " + argument + ending + PING, bulk(expected) + PONG),
                              (PING, PONG))))

    for encoded, decoded in ((b"n", b"\n"), (b"r", b"\r"), (b"t", b"\t"),
                             (b"b", b"\b"), (b"a", b"\a"), (b"\\", b"\\"),
                             (b'"', b'"'), (b"'", b"'"), (b"q", b"q"),
                             (b"0", b"0"), (b"v", b"v"), (b"f", b"f")):
        echo("double escape " + repr(encoded), b'"a\\' + encoded + b'b"', b"a" + decoded + b"b")
    for n in range(256):
        for spelling in (b"%02x" % n, b"%02X" % n):
            echo("hex " + repr(spelling), b'"a\\x' + spelling + b'b"', b"a" + bytes([n]) + b"b")
    for spelling in (b"x", b"x0", b"xG0", b"x0G", b"xgg", b"X41", b"x-1", b"x 1"):
        echo("invalid/short hex " + repr(spelling), b'"\\' + spelling + b'"', spelling)
    echo("hex consumes two digits", b'"\\x4142"', b"A42")
    echo("all bytes in one arg", b'"' + b"".join(b"\\x%02x" % n for n in range(256)) + b'"', bytes(range(256)))
    echo("single escaped quote", b"'a\\'b'", b"a'b")
    echo("single literal escapes", b"'\\n\\r\\t\\b\\a\\x00\\\\z'", b"\\n\\r\\t\\b\\a\\x00\\\\z")
    echo("unquoted literal escapes", b"a\\n\\x00\\\\", b"a\\n\\x00\\\\")
    for quote in (b'"', b"'"):
        echo("empty " + repr(quote), quote + quote, b"")
        echo("prefix " + repr(quote), b"prefix" + quote + b"with space" + quote, b"prefixwith space")
        echo("opposite quote " + repr(quote), quote + (b"'" if quote == b'"' else b'"') + quote,
             b"'" if quote == b'"' else b'"')
        for space in (b" ", b"\t", b"\r", b"\v", b"\f"):
            echo("closing whitespace " + repr(quote + space), quote + b"v" + quote + space, b"v")
        for tail in (b"x", b"\\", b'"', b"'", b"\xff"):
            wire = b"ECHO " + quote + b"v" + quote + tail + b"\n"
            rows.append(Case("quote followed by nonspace " + repr(wire),
                             ((PING + wire + PING, PONG + PREFIX + b"unbalanced quotes in request\r\n"),), True))
    for wire in (b'ECHO "a\n', b"ECHO 'a\r\n", b'ECHO "a\\\n', b"ECHO 'a\\\n",
                 b'ECHO "a\\"\n', b"ECHO 'a\\'\n", b"ECHO 'a\\\\'\n", b'ECHO prefix"\n', b'ECHO ok "bad\n'):
        rows.append(Case("unbalanced " + repr(wire),
                         ((wire + PING, PREFIX + b"unbalanced quotes in request\r\n"),), True))
    for spaces in (b"", b" ", b"\t", b"\v", b"\f", b"\r", b" \t\v\f\r"):
        for ending in (b"\n", b"\r\n"):
            rows.append(Case("empty line " + repr(spaces + ending),
                             ((spaces + ending + PING, PONG), (PING, PONG))))
        rows.append(Case("leading blanks " + repr(spaces), ((spaces + b"ECHO v\n", bulk(b"v")), (PING, PONG))))
    echo("unquoted embedded VT/FF", b"a\vb\fc", b"a\vb\fc")
    echo("unquoted CR delimiter", b"v\r", b"v")
    rows.append(Case("CR between arguments", ((b"ECHO\rv\n", bulk(b"v")), (PING, PONG))))
    # At the bound Redis waits. Only an unfinished line above it is too large.
    for size in (65535, 65536):
        value = b"v" * (size - 7)
        line = b'ECHO "' + value + b'"'
        assert len(line) == size
        rows.append(Case("complete boundary " + str(size), ((line, None), (b"\n" + PING, bulk(value) + PONG))))
    rows.append(Case("unfinished 64 KiB + 1", ((b'x' * 65536, None),
                     (b'x', PREFIX + b"too big inline request\r\n")), True))
    rows.append(Case("quoted unfinished 64 KiB + 1", ((b'ECHO "' + b'x' * 65530, None),
                     (b'x', PREFIX + b"too big inline request\r\n")), True))
    rows.append(Case("raw NUL blocks LF search", ((b'ECHO "a\0b"\n', None),)))
    rows.append(Case("fragmented hex and CRLF", ((b'ECHO "a\\', None), (b'x0', None),
                     (b'0b"\r', None), (b'\n' + PING, bulk(b'a\0b') + PONG))))
    # Many ROB turns; every frame uses different bytes, including empty/binary
    # keys and replies. The next RESP frame must remain completely untouched.
    wire, expected = bytearray(), bytearray()
    for n in range(257):
        key, value = b"inline key\0" + str(n).encode(), b"v " + str(n).encode()
        quoted_key = b'"inline key\\x00' + str(n).encode() + b'"'
        wire += b'SET ' + quoted_key + b' "' + value + b'"\r\n'
        wire += encode("GET", key) + b'GET ' + quoted_key + b'\n'
        wire += encode("ECHO", b'"\\\0\r\n*1') + b'\nECHO ""\n'
        expected += b'+OK\r\n' + bulk(value) * 2 + bulk(b'"\\\0\r\n*1') + bulk(b'')
    rows.append(Case("mixed pipeline and ROB reuse", ((bytes(wire), bytes(expected)), (PING, PONG))))
    rows.append(Case("heap argv plus decoded bytes", ((b'MGET ' + b'"" ' * 40 + b'\n' + PING,
                     b'*40\r\n' + b'$-1\r\n' * 40 + PONG),)))
    rows.append(Case("transaction retains decoded argv", ((b'MULTI\nECHO "a\\x00b"\n' + encode("ECHO", b"next") + b'EXEC\n',
                     b'+OK\r\n+QUEUED\r\n+QUEUED\r\n*2\r\n' + bulk(b'a\0b') + bulk(b'next')), (PING, PONG))))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--oracle", nargs=2, required=True, metavar=("HOST", "PORT"))
    args = parser.parse_args()
    oracle = (args.oracle[0], int(args.oracle[1]))
    with closing(Conn(*oracle)) as conn:
        assert b"redis_version:7.4.10\r\n" in conn.cmd("INFO", "server"), "wrong oracle version"
    rows = cases()
    failures = 0
    for name, endpoint in (("Redis 7.4.10", oracle), ("TomoKV", (args.host, args.port))):
        passed = 0
        for case in rows:
            try:
                run_case(endpoint, case)
                passed += 1
            except (AssertionError, OSError) as error:
                failures += 1
                print(f"FAIL {name}: {case.name}: {str(error)[:600]}", flush=True)
        print(f"{name}: {passed}/{len(rows)} exact bytes + connection states", flush=True)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
