#!/usr/bin/env python3
"""Raw RESP error bytes and connection lifetime; connects only, never boots servers.

Usage: respcompat.py HOST PORT [--oracle HOST PORT]
The differential gate supplies its already-owned Redis 7.4 reference. Each arm
must match the explicit byte oracle, so two equally broken parsers cannot pass.
"""
import argparse
from dataclasses import dataclass
import socket
import ssl

from _lib import Conn, encode

PING = b"*1\r\n$4\r\nPING\r\n"
PONG = b"+PONG\r\n"
PREFIX = b"-ERR Protocol error: "


@dataclass(frozen=True)
class Case:
    name: str
    steps: tuple  # (bytes sent, exact bytes received); None requires silence
    closes: bool = False


def cases():
    rows = []

    def error(name, payload, text):
        rows.append(Case(name, ((payload, PREFIX + text + b"\r\n"),), True))

    for field in (b"", b"00", b"01", b"-0", b"-01", b"+1", b" 1", b"1 ", b"x",
                  b"2147483648", b"9223372036854775808", b"-9223372036854775809",
                  b"18446744073709551616"):
        error(f"array {field!r}", b"*" + field + b"\r\n", b"invalid multibulk length")
    for field in (b"", b"00", b"04", b"-0", b"-1", b"-2", b"-01", b"+1", b" 1", b"1 ", b"x",
                  b"536870913", b"9223372036854775808", b"18446744073709551616"):
        error(f"bulk {field!r}", b"*1\r\n$" + field + b"\r\n", b"invalid bulk length")
    for byte in range(1, 256):
        if byte == ord("$"):
            continue
        quoted = b" " if byte in (10, 13) else bytes([byte])
        error(f"bulk prefix 0x{byte:02x}", b"*1\r\n" + bytes([byte]) + b"\r\n",
              b"expected '$', got '" + quoted + b"'")
    for field in (b"0", b"-1", b"-2", b"-2147483649", b"-9223372036854775808"):
        empty = b"*" + field + b"\r\n"
        rows.append(Case(f"empty array {field!r}",
                         ((empty, None), (PING, PONG), (empty + empty + PING, PONG), (PING, PONG))))
    for wire in (b"PING\n", b"PING\r\n", b" \tPING\n"):
        rows.append(Case(f"inline {wire!r}", ((wire, PONG), (PING, PONG))))
    rows.append(Case("empty inline", ((b"\n\r\n \t\n" + PING, PONG), (PING, PONG))))
    rows.append(Case("split inline CRLF", ((b"PING\r", None), (b"\n", PONG), (PING, PONG))))
    rows.append(Case("split array count", ((b"*", None), (b"-1\r", None), (b"\n" + PING, PONG))))
    rows.append(Case("split invalid count", ((b"*x", None), (b"\r", None),
                    (b"\n", PREFIX + b"invalid multibulk length\r\n")), True))
    rows.append(Case("split bulk prefix", ((b"*1\r\n!", None), (b"\r", None),
                    (b"\n", PREFIX + b"expected '$', got '!'\r\n")), True))
    for wire in (b"*2147483647\r\n", b"*1048577\r\n", b"*1\r\n\0\r\n", b"PING\0\n"):
        rows.append(Case(f"incomplete {wire!r}", ((wire, None),)))
    for wire in (b'ECHO "a\n', b"ECHO 'a\r\n", b'ECHO "a"x\n', b"ECHO 'a'x\n",
                 b'ECHO "a\\"\n', b"ECHO 'a\\'\n"):
        error(f"quotes {wire!r}", wire, b"unbalanced quotes in request")
    for name, start, text in (("array", b"*", b"too big mbulk count string"),
                              ("bulk", b"*1\r\n$", b"too big bulk count string")):
        rows.append(Case(f"{name} incomplete 64 KiB boundary",
                         ((start + b"0" * 65535, None), (b"0", PREFIX + text + b"\r\n")), True))
    rows.append(Case("inline incomplete 64 KiB boundary",
                     ((b"x" * 65536, None), (b"x", PREFIX + b"too big inline request\r\n")), True))
    rows.append(Case("empty bulk", ((b"*2\r\n$4\r\nECHO\r\n$0\r\n\r\n", b"$0\r\n\r\n"), (PING, PONG))))
    rows.append(Case("binary bulk", ((b"*2\r\n$4\r\nECHO\r\n$3\r\na\0b\r\n", b"$3\r\na\0b\r\n"),)))
    rows.append(Case("Redis unchecked terminator bytes", ((b"*1\rX$4\rYPINGzz", PONG), (PING, PONG))))
    rows.append(Case("reply order then error then close",
                     ((PING + b"*01\r\n" + PING, PONG + PREFIX + b"invalid multibulk length\r\n"),), True))
    return rows


def exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise AssertionError(f"early EOF after {bytes(data)!r}")
        data.extend(chunk)
    return bytes(data)


def run_case(endpoint, case, tls=False):
    sock = socket.create_connection(endpoint, timeout=3)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        sock = context.wrap_socket(sock, server_hostname="localhost")
    with sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for payload, expected in case.steps:
            sock.settimeout(3)
            sock.sendall(payload)
            if expected is None:
                sock.settimeout(0.05)
                try:
                    unexpected = sock.recv(1)
                except socket.timeout:
                    continue
                raise AssertionError(f"expected silence and open connection; got {unexpected!r}")
            actual = exact(sock, len(expected))
            if actual != expected:
                raise AssertionError(f"expected {expected!r}, got {actual!r}")
        if case.closes:
            sock.settimeout(3)
            # Exact error bytes were already consumed. A reset can accompany
            # close when pipelined input remains unread; a timeout is not close.
            try:
                trailing = sock.recv(1)
            except ConnectionResetError:
                return
            if trailing != b"":
                raise AssertionError(f"expected close after error; extra bytes {trailing!r}")
        else:
            sock.settimeout(0.01)
            try:
                trailing = sock.recv(1)
            except socket.timeout:
                return
            raise AssertionError(f"expected open connection with no extra reply; got {trailing!r}")


def preauth_cases():
    """N3: grammar/configured bounds precede the authentication-specific bounds."""
    rows = []
    for field, text in ((b"11", b"unauthenticated multibulk length"),
                        (b"2147483647", b"unauthenticated multibulk length"),
                        (b"2147483648", b"invalid multibulk length"),
                        (b"011", b"invalid multibulk length")):
        for split in (False, True):
            steps = ((b"*" + field, None), (b"\r\n", PREFIX + text + b"\r\n")) if split else (
                (b"*" + field + b"\r\n", PREFIX + text + b"\r\n"),)
            rows.append(Case(f"preauth array {field!r} split={split}", steps, True))
    # CONFIG below sets proto-max-bulk-len=1mb. Both boundaries must keep Redis's
    # precedence, including a header parsed after a previously completed argument.
    for field, text in ((b"16385", b"unauthenticated bulk length"),
                        (b"1048576", b"unauthenticated bulk length"),
                        (b"1048577", b"invalid bulk length"),
                        (b"016385", b"invalid bulk length"),
                        (b"-1", b"invalid bulk length"),
                        (b"9223372036854775808", b"invalid bulk length")):
        prefix = b"*10\r\n$5\r\nhello\r\n$" + field
        rows.append(Case(f"preauth bulk {field!r}",
                         ((prefix + b"\r\n", PREFIX + text + b"\r\n"),), True))
        rows.append(Case(f"preauth bulk {field!r} split",
                         ((prefix, None), (b"\r\n", PREFIX + text + b"\r\n")), True))
    noauth = b"-NOAUTH Authentication required.\r\n"
    rows.append(Case("preauth count 10 accepted", ((encode("DEL", *(["absent"] * 9)), noauth),
                                                 (PING, noauth))))
    rows.append(Case("preauth bulk 16384 accepted",
                     ((encode("ECHO", b"x" * 16384), noauth), (PING, noauth))))
    rows.append(Case("pending AUTH succeeds",
                     ((b"*2\r\n$4\r\nAUTH\r\n$6\r\nsec", None),
                      (b"ret\r\n", b"+OK\r\n"), (PING, PONG))))
    return rows


def frontier_cases():
    """N4: completed prefixes stop counting; the unread suffix still counts."""
    from respresume_limits import small_args_frame
    mib = 1 << 20
    prefix_error = PREFIX + b"expected '$', got '!'\r\n"
    return [
        Case("many completed args then over limit",
             ((small_args_frame(400000, 100000), None),
              (b"$1\r\na\r\n" * 60000, None),
              (b"$1\r\na\r\n" * 10000, None),
              (b"!\r\n", prefix_error)), True),
        Case("partial header crosses limit",
             ((small_args_frame(200000, 149795), None), (b"$1", None),
              (b"\r\n", None), (b"a\r\n!\r\n", prefix_error)), True),
        # Before parsing this read the payload itself is exactly 1 MiB: legal.
        # The next byte must cause a silent close, not a protocol error.
        Case("unparsed payload equality then overflow",
             ((b"*2\r\n$4\r\nECHO\r\n$2097152\r\n", None),
              (b"x" * (mib // 2), None), (b"x" * (mib // 2), None),
              (b"x", b"")), True),
        Case("large legal frame completes",
             ((b"*2\r\n$4\r\nECHO\r\n$1048000\r\n", None),
              (b"y" * 524288, None),
              (b"y" * (1048000 - 524288) + b"\r\n",
               b"$1048000\r\n" + b"y" * 1048000 + b"\r\n"), (PING, PONG))),
    ]


def limits_row(endpoint, kind, tls_port=None):
    """Connect-only row, exact assertions on fresh TCP and optional TLS clients."""
    admin = Conn(*endpoint)
    fields = ("requirepass", "proto-max-bulk-len") if kind == "preauth" else (
        "client-query-buffer-limit",)
    old = {field: admin.must("CONFIG", "GET", field)[1] for field in fields}
    rows = preauth_cases() if kind == "preauth" else frontier_cases()
    try:
        if kind == "preauth":
            assert admin.must("CONFIG", "SET", "proto-max-bulk-len", "1mb") == b"OK"
            assert admin.must("CONFIG", "SET", "requirepass", "secret") == b"OK"
        else:
            assert admin.must("CONFIG", "SET", "client-query-buffer-limit", "1mb") == b"OK"
        for tls in ((False, True) if tls_port else (False,)):
            target = (endpoint[0], tls_port) if tls else endpoint
            for case in rows:
                try:
                    run_case(target, case, tls)
                except (AssertionError, OSError) as exc:
                    raise AssertionError(f"{kind} tls={tls}: {case.name}: {exc}") from exc
            print(f"PASS ntfix {kind}: {len(rows)} exact cases, tls={tls}", flush=True)
    finally:
        for field, value in old.items():
            assert admin.must("CONFIG", "SET", field, value) == b"OK"
        admin.close()


def verify_oracle(endpoint):
    with socket.create_connection(endpoint, timeout=3) as sock:
        sock.sendall(b"*2\r\n$4\r\nINFO\r\n$6\r\nserver\r\n")
        with sock.makefile("rb") as stream:
            line = stream.readline()
            if not line.startswith(b"$"):
                raise AssertionError(f"oracle INFO failed: {line!r}")
            info = stream.read(int(line[1:]))
        fields = dict(line.split(b":", 1) for line in info.split(b"\r\n") if b":" in line)
        version = fields.get(b"redis_version", b"")
        if not version.startswith(b"7.4.") or {b"tomokv_version", b"dragonfly_version"} & fields.keys():
            raise AssertionError(f"requires vanilla Redis 7.4, got {version!r}")
        print(f"oracle Redis {version.decode()}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--oracle", nargs=2, metavar=("HOST", "PORT"))
    parser.add_argument("--ntfix", choices=("preauth", "frontier"))
    parser.add_argument("--tls-port", type=int,
                        help="also run the ntfix row over decrypted TLS 1.3")
    args = parser.parse_args()
    if args.ntfix:
        if args.oracle:
            oracle = (args.oracle[0], int(args.oracle[1]))
            verify_oracle(oracle)
            limits_row(oracle, args.ntfix)
        limits_row((args.host, args.port), args.ntfix, args.tls_port)
        return
    arms = [("target", (args.host, args.port))]
    if args.oracle:
        oracle = (args.oracle[0], int(args.oracle[1]))
        verify_oracle(oracle)
        arms.insert(0, ("oracle", oracle))
    rows = cases()
    failures = []
    for arm, endpoint in arms:
        for case in rows:
            try:
                run_case(endpoint, case)
            except (AssertionError, OSError) as exc:
                failures.append((arm, case.name, str(exc)))
                print(f"FAIL {arm}: {case.name}: {exc}", flush=True)
        print(f"{arm}: {len(rows)} raw-wire cases attempted", flush=True)
    if failures:
        raise SystemExit(f"FAIL RESP protocol error compatibility: {len(failures)} cases")
    print(f"PASS RESP protocol error compatibility: {len(rows)} cases x {len(arms)} arms")


if __name__ == "__main__":
    main()
