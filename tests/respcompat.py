#!/usr/bin/env python3
"""Raw RESP error bytes and connection lifetime; connects only, never boots servers.

Usage: respcompat.py HOST PORT [--oracle HOST PORT]
The differential gate supplies its already-owned Redis 7.4 reference. Each arm
must match the explicit byte oracle, so two equally broken parsers cannot pass.
"""
import argparse
from dataclasses import dataclass
import socket

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


def run_case(endpoint, case):
    with socket.create_connection(endpoint, timeout=3) as sock:
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
    args = parser.parse_args()
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
