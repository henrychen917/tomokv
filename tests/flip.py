#!/usr/bin/env python3
"""Directed manual-FLIP ownership/conservation battery.

Usage: tests/flip.py HOST PORT

This is intentionally not part of the build. The operator starts the desired io_uring or epoll
server and runs it explicitly; this lane's implementation rule permits compilation only here.
"""

import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])
failures = []
checks = 0


def encode(*args):
    parts = [b"*%d\r\n" % len(args)]
    for arg in args:
        value = str(arg).encode() if not isinstance(arg, bytes) else arg
        parts.append(b"$%d\r\n" % len(value) + value + b"\r\n")
    return b"".join(parts)


class Conn:
    def __init__(self, timeout=20):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.file = self.sock.makefile("rb")

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed connection")
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body.decode()
        if kind == b"-":
            return RuntimeError(body.decode())
        if kind == b":":
            return int(body)
        if kind in (b"$", b"="):
            length = int(body)
            return None if length < 0 else self.file.read(length + 2)[:-2].decode("latin1")
        if kind in (b"*", b"~", b">"):
            length = int(body)
            return None if length < 0 else [self.read() for _ in range(length)]
        if kind == b"%":
            return [self.read() for _ in range(int(body) * 2)]
        if kind == b"_":
            return None
        raise AssertionError("unexpected RESP marker %r" % line)

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def pipeline(self, commands):
        self.sock.sendall(b"".join(encode(*command) for command in commands))
        return [self.read() for _ in commands]

    def close(self):
        self.sock.close()


def check(label, got, want):
    global checks
    checks += 1
    ok = want(got) if callable(want) else got == want
    if not ok:
        failures.append("%s: got %r, want %r" % (label, got, want))
        print("  FAIL %-54s got=%r" % (label, got))
    return ok


def record(reply):
    return dict(zip(reply[0::2], reply[1::2]))


def info(c, section):
    body = c.cmd("INFO", section)
    result = {}
    for line in body.split("\r\n"):
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            result[key] = value
    return result


def is_error_containing(fragment):
    return lambda value: isinstance(value, RuntimeError) and fragment in str(value)


def main():
    control = Conn(timeout=30)
    initial = record(control.cmd("FLIP"))
    live_io, live_ex = initial["live_io"], initial["live_ex"]
    unit_threads = initial["unit_threads"]
    total = live_io + live_ex
    check("report starts stable", initial["moving"], 0)
    check("initial conservation", total, lambda value: value >= 2)
    check("report SMT mode is numeric", initial["smt_mode"], lambda value: value in (0, 1))
    check("report scheduling unit", unit_threads, 2 if initial["smt_mode"] else 1)
    metadata = control.cmd("COMMAND", "INFO", "FLIP")[0]
    check("metadata row names FLIP", metadata[0].lower(), "flip")
    check("metadata inherits fork arity", metadata[1], -2)
    for flag in ("write", "admin", "noscript", "no_multi", "no_async_loading"):
        check("metadata carries %s" % flag, flag in metadata[2], True)

    before = info(control, "stats")
    refused = control.cmd("FLIP", total, 1)
    check("wrong total refused", refused, is_error_containing("must equal"))
    after_refusal = record(control.cmd("FLIP"))
    check("refusal leaves live io unchanged", after_refusal["live_io"], live_io)
    check("refusal leaves live ex unchanged", after_refusal["live_ex"], live_ex)
    check("refused target remains visible", after_refusal["target_io"], total)
    check("refusal is not moving", after_refusal["moving"], 0)

    if initial["smt_mode"]:
        pair_refused = control.cmd("FLIP", live_io - 1, live_ex + 1)
        check("split sibling pair refused", pair_refused,
              is_error_containing("nearest achievable splits"))
        after_pair_refusal = record(control.cmd("FLIP"))
        check("pair refusal leaves live io unchanged", after_pair_refusal["live_io"], live_io)
        check("pair refusal leaves live ex unchanged", after_pair_refusal["live_ex"], live_ex)
        check("pair refusal reports two-thread unit", after_pair_refusal["unit_threads"], 2)

    check("one-argument grammar rejected", control.cmd("FLIP", live_io),
          is_error_containing("wrong number"))
    check("MULTI starts", control.cmd("MULTI"), "OK")
    check("FLIP is forbidden in MULTI", control.cmd("FLIP", live_io, live_ex),
          is_error_containing("not allowed inside a transaction"))
    check("DISCARD after forbidden FLIP", control.cmd("DISCARD"), "OK")

    if live_ex <= unit_threads:
        print("SKIP role-conversion half: the running server has only one EX unit")
    else:
        grown_io, grown_ex = live_io + unit_threads, live_ex - unit_threads
        baseline = int(before.get("flip_completed", "0"))
        seed = [("SET", "flip:seed:%d" % index, "seed:%d" % index)
                for index in range(256)]
        check("seed keys before EX evacuation", control.pipeline(seed), ["OK"] * len(seed))
        check("EX -> IO completes", control.cmd("FLIP", grown_io, grown_ex), "OK")
        grown = record(control.cmd("FLIP"))
        check("grown live io", grown["live_io"], grown_io)
        check("grown live ex", grown["live_ex"], grown_ex)
        check("grown target io", grown["target_io"], grown_io)
        check("grown target ex", grown["target_ex"], grown_ex)
        seed_reads = [("GET", "flip:seed:%d" % index) for index in range(256)]
        check("keys survive EX -> IO bucket evacuation", control.pipeline(seed_reads),
              ["seed:%d" % index for index in range(256)])

        # These connections are created after the extra IO listener is live. With SO_REUSEPORT a
        # subset should land on it; the reverse FLIP must transfer every such connection intact.
        clients = [Conn(timeout=30) for _ in range(96)]
        for index, client in enumerate(clients):
            replies = client.pipeline([
                ("SET", "flip:key:%d" % index, "value:%d" % index),
                ("GET", "flip:key:%d" % index),
                ("PING",),
            ])
            check("pre-shrink pipeline %d" % index, replies,
                  ["OK", "value:%d" % index, "PONG"])

        check("IO -> EX completes", control.cmd("FLIP", live_io, live_ex), "OK")
        restored = record(control.cmd("FLIP"))
        check("restored live io", restored["live_io"], live_io)
        check("restored live ex", restored["live_ex"], live_ex)
        check("keys survive IO -> EX bucket acquisition", control.pipeline(seed_reads),
              ["seed:%d" % index for index in range(256)])
        for index, client in enumerate(clients):
            check("migrated connection %d" % index,
                  client.pipeline([("GET", "flip:key:%d" % index), ("PING",)]),
                  ["value:%d" % index, "PONG"])
            client.close()

        stats = info(control, "stats")
        check("completed counter proves both actuations",
              int(stats["flip_completed"]), lambda value: value >= baseline + 2)
        check("refused counter moved",
              int(stats["flip_refused"]), lambda value: value >= int(before["flip_refused"]) + 1)
        check("conservation checks fired",
              int(stats["flip_conservation_checks"]), lambda value: value > 0)
        check("no conservation violation", int(stats["flip_conservation_violations"]), 0)
        server = info(control, "server")
        check("INFO live io split", int(server["io_threads"]), live_io)
        check("INFO live ex split", int(server["ex_threads"]), live_ex)

    control.close()
    if failures:
        print("FAIL: %d/%d checks" % (len(failures), checks))
        for failure in failures:
            print("  " + failure)
        return 1
    print("ok: %d FLIP checks" % checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
