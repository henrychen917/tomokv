#!/usr/bin/env python3
"""CC4.12: empty patterns retain pmessage framing in both RESP dialects."""
from compat3_lib import equal, run
from _lib import Conn


def frame(c):
    line = c.file.readline()
    assert line.endswith(b"\r\n"), line
    tag, body = line[:1], line[1:-2]
    if tag in (b"*", b">"):
        return tag, [frame(c)[1] for _ in range(int(body))]
    if tag == b"$":
        data = c.file.read(int(body))
        equal(c.file.read(2), b"\r\n", "bulk trailer")
        return tag, data
    if tag == b":":
        return tag, int(body)
    if tag == b"+":
        return tag, body
    raise AssertionError(line)


def probe(c, case):
    out = []
    for protocol in (2, 3):
        sub = Conn(c.host, c.port, timeout=8, buffering=0)
        try:
            if protocol == 3:
                assert isinstance(sub.cmd("HELLO", 3), list)
            # A single subscriber to both direct and empty-pattern routes gets BOTH frames.
            for command in ("PSUBSCRIBE", "SUBSCRIBE"):
                sub.send(command, b"")
                out.append(frame(sub))
            equal(c.cmd("PUBLISH", b"", b"v\x00tail"), 2, "two recipients")
            delivered = [frame(sub), frame(sub)]
            # Route iteration order is not specified. Frame shape/bytes and multiplicity are.
            out.append(sorted(delivered, key=repr))
            sub.send("PUNSUBSCRIBE", b"")
            out.append(frame(sub))
            equal(c.cmd("PUBLISH", b"", b"direct"), 1, "pattern removed")
            out.append(frame(sub))
            sub.send("UNSUBSCRIBE", b"")
            out.append(frame(sub))
        finally:
            sub.close()
    return out


if __name__ == "__main__":
    run(probe, ("pubsub",))
