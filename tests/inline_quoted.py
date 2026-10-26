#!/usr/bin/env python3
"""NT4.17/NET15: valid inline quotes must decode, including binary escapes."""
import sys
from contextlib import closing
from _lib import Conn, encode

CASES = [(b'ECHO "a b"\r\n', b'a b'), (b"ECHO 'a b'\n", b'a b'),
         (b'ECHO "a\\"b"\n', b'a"b'), (b"ECHO 'a\\'b'\n", b"a'b"),
         (b'ECHO "\\x00"\n', b'\0'), (b'ECHO "\\n\\t\\r"\n', b'\n\t\r'),
         (b'ECHO ""\n', b'')]
failures = 0
for wire, expected in CASES:
    with closing(Conn(sys.argv[1], int(sys.argv[2]))) as conn:
        conn.raw(wire + encode("PING", "sentinel"))
        actual = conn.read()
        if actual != expected:
            print(f"FAIL decoded inline {wire!r}: expected={expected!r} actual={actual!r}")
            failures += 1
        assert conn.read() == b"sentinel", "inline parse consumed the next frame"
print(f"inline decoding: {len(CASES)} cases, {failures} failures")
raise SystemExit(bool(failures))
