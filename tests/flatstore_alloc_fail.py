#!/usr/bin/env python3
"""FlatStore resize-allocation fault gate.

Boot a dedicated empty server with one shard and the DEBUG surface enabled, for example:

  taskset -c 32,33 ./build/tomokv --port 7953 --shards 1 --ratio 1:1 \
      --save "" --enable-debug-command yes
  python3 tests/flatstore_alloc_fail.py 127.0.0.1 7953

The 717th key is the exact growth edge of the reset 1024-slot table. The injected calloc failure
must become a command error while the old table remains readable; retrying after the one-shot fault
must then grow normally.
"""

import socket
import sys


class RespError(Exception):
    pass


class Client:
    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.file = self.sock.makefile("rb")

    def command(self, *parts):
        encoded = []
        for part in parts:
            if not isinstance(part, bytes):
                part = str(part).encode()
            encoded.append(part)
        frame = b"*%d\r\n" % len(encoded)
        frame += b"".join(b"$%d\r\n%s\r\n" % (len(part), part) for part in encoded)
        self.sock.sendall(frame)
        return self.read()

    def read(self):
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise RuntimeError("connection closed while reading reply")
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body
        if kind == b"-":
            raise RespError(body.decode("utf-8", "replace"))
        if kind == b":":
            return int(body)
        if kind == b"$":
            length = int(body)
            if length < 0:
                return None
            data = self.file.read(length)
            if self.file.read(2) != b"\r\n":
                raise RuntimeError("invalid bulk reply")
            return data
        raise RuntimeError("unsupported reply: %r" % line)


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError("%s: got %r, wanted %r" % (label, actual, wanted))


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7953
    client = Client(host, port)

    expect(client.command("FLUSHALL"), b"OK", "reset keyspace")
    expect(client.command("DBSIZE"), 0, "empty precondition")
    for index in range(716):
        expect(client.command("SET", "flatfix:%d" % index, "v"), b"OK",
               "seed key %d" % index)
    expect(client.command("DBSIZE"), 716, "growth-edge precondition")

    expect(client.command("DEBUG", "TABLE-ALLOC-FAIL", "1"), b"OK", "arm fault")
    try:
        client.command("SET", "flatfix:failed", "v")
    except RespError as error:
        expect(str(error), "ERR keyspace insert failed", "defined allocation error")
    else:
        raise AssertionError("resize allocation failure unexpectedly succeeded")

    expect(client.command("PING"), b"PONG", "server remains responsive")
    expect(client.command("GET", "flatfix:0"), b"v", "old table remains readable")
    expect(client.command("GET", "flatfix:failed"), None, "failed insert stayed absent")
    expect(client.command("DBSIZE"), 716, "failed insert preserved cardinality")
    expect(client.command("SET", "flatfix:failed", "v"), b"OK", "retry grows table")
    expect(client.command("GET", "flatfix:failed"), b"v", "retry is readable")
    expect(client.command("DEBUG", "TABLE-ALLOC-FAIL", "0"), b"OK", "disarm fault")
    print("ok: FlatStore allocation failure returned an error and preserved the live table")


if __name__ == "__main__":
    main()
