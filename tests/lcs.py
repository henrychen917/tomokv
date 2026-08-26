#!/usr/bin/env python3
"""Exhaustive LCS battery, checked against an independent Python reference.

Usage: tests/lcs.py HOST PORT

The reference is a second implementation of the same algorithm written directly from the
definition, so a shared bug would have to be made twice in two languages. Key pairs are chosen to
land BOTH on one shard and across shards, because those are two different code paths in this tree
(the local fast path and the scatter/gather lowering) and they must not diverge.
"""

import random
import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 11
failures = []
checks = 0


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
            # latin-1, not utf-8: replies are decoded latin-1, so a round trip must be
            # byte-preserving for the binary-safety case.
            arg = arg.encode("latin1")
        out.append(b"$%d\r\n" % len(arg) + arg + b"\r\n")
    return b"".join(out)


class Conn:
    def __init__(self, timeout=60):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError
        kind, body = line[:1], line[1:-2]
        if kind == b"+":
            return body.decode()
        if kind == b"-":
            return RuntimeError(body.decode())
        if kind == b":":
            return int(body)
        if kind in (b"$", b"="):
            n = int(body)
            return None if n == -1 else self.file.read(n + 2)[:-2].decode("latin1")
        if kind in (b"*", b"~", b">"):
            n = int(body)
            return None if n == -1 else [self.read() for _ in range(n)]
        if kind == b"%":
            return [self.read() for _ in range(int(body) * 2)]
        if kind == b"_":
            return None
        raise AssertionError("unexpected RESP marker %r" % line[:16])

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def check(label, got, want):
    global checks
    checks += 1
    ok = (want(got) if callable(want) else got == want)
    if not ok:
        failures.append("%s: got %r want %r" % (label, got, want))
        print("  FAIL %-44s got=%r want=%r" % (label, got, want))
    return ok


def err(text):
    return lambda got: isinstance(got, RuntimeError) and str(got) == text


# --------------------------------------------------------------------------- reference
def reference(a, b, minmatchlen=0):
    """Returns (subsequence, length, matches) with redis's traceback ordering."""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            table[i][j] = (table[i - 1][j - 1] + 1 if a[i - 1] == b[j - 1]
                           else max(table[i - 1][j], table[i][j - 1]))
    out, matches = [], []
    i, j = n, m
    run = 0
    end_a = end_b = 0
    def flush():
        nonlocal run
        if run and run >= max(minmatchlen, 1):
            matches.append(((end_a + 1 - run, end_a), (end_b + 1 - run, end_b), run))
        run = 0
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            out.append(a[i - 1])
            if not run:
                end_a, end_b = i - 1, j - 1
            run += 1
            i -= 1
            j -= 1
            continue
        flush()
        if table[i - 1][j] > table[i][j - 1]:
            i -= 1
        else:
            j -= 1
    flush()
    return "".join(reversed(out)), table[n][m], matches


def parse_idx(reply):
    fields = dict(zip(reply[0::2], reply[1::2]))
    out = []
    for match in fields["matches"]:
        a, b = match[0], match[1]
        length = match[2] if len(match) > 2 else None
        out.append(((a[0], a[1]), (b[0], b[1]), length))
    return out, fields["len"]


def main():
    rng = random.Random(SEED)
    c = Conn()
    c.cmd("FLUSHALL")

    print("directed cases")
    c.cmd("SET", "lcs:1", "ohmytext")
    c.cmd("SET", "lcs:2", "mynewtext")
    check("plain", c.cmd("LCS", "lcs:1", "lcs:2"), "mytext")
    check("LEN", c.cmd("LCS", "lcs:1", "lcs:2", "LEN"), 6)
    idx, length = parse_idx(c.cmd("LCS", "lcs:1", "lcs:2", "IDX"))
    check("IDX len", length, 6)
    check("IDX matches", idx, [((4, 7), (5, 8), None), ((2, 3), (0, 1), None)])
    idx, _ = parse_idx(c.cmd("LCS", "lcs:1", "lcs:2", "IDX", "WITHMATCHLEN"))
    check("WITHMATCHLEN", idx, [((4, 7), (5, 8), 4), ((2, 3), (0, 1), 2)])
    idx, length = parse_idx(c.cmd("LCS", "lcs:1", "lcs:2", "IDX", "MINMATCHLEN", "4"))
    check("MINMATCHLEN filters matches", idx, [((4, 7), (5, 8), None)])
    check("MINMATCHLEN leaves len alone", length, 6)
    idx, _ = parse_idx(c.cmd("LCS", "lcs:1", "lcs:2", "IDX", "MINMATCHLEN", "100"))
    check("MINMATCHLEN can filter everything", idx, [])

    print("edge cases")
    c.cmd("SET", "lcs:empty", "")
    check("missing key", c.cmd("LCS", "lcs:1", "lcs:nosuch"), "")
    check("both missing", c.cmd("LCS", "lcs:no1", "lcs:no2"), "")
    check("empty value", c.cmd("LCS", "lcs:empty", "lcs:1"), "")
    idx, length = parse_idx(c.cmd("LCS", "lcs:empty", "lcs:1", "IDX"))
    check("empty IDX", (idx, length), ([], 0))
    check("self", c.cmd("LCS", "lcs:1", "lcs:1"), "ohmytext")
    check("no common bytes", (c.cmd("SET", "lcs:abc", "abc"),
                              c.cmd("SET", "lcs:xyz", "xyz"),
                              c.cmd("LCS", "lcs:abc", "lcs:xyz"))[2], "")
    # An int-encoded value must be compared as its decimal text, not its 8 raw bytes.
    c.cmd("SET", "lcs:int", "12345")
    c.cmd("SET", "lcs:txt", "a1b2c3")
    check("int-encoded operand", c.cmd("LCS", "lcs:int", "lcs:txt"), reference("12345", "a1b2c3")[0])
    check("binary-safe operand",
          (c.cmd("SET", "lcs:bin", "a\x00b\xffc"),
           c.cmd("LCS", "lcs:bin", "lcs:bin"))[1], "a\x00b\xffc")

    print("grammar")
    check("LEN + IDX", c.cmd("LCS", "lcs:1", "lcs:2", "LEN", "IDX"),
          err("ERR If you want both the length and indexes, please just use IDX."))
    check("unknown option", c.cmd("LCS", "lcs:1", "lcs:2", "BOGUS"), err("ERR syntax error"))
    check("MINMATCHLEN needs a value", c.cmd("LCS", "lcs:1", "lcs:2", "MINMATCHLEN"),
          err("ERR syntax error"))
    check("MINMATCHLEN needs an integer", c.cmd("LCS", "lcs:1", "lcs:2", "MINMATCHLEN", "abc"),
          err("ERR value is not an integer or out of range"))
    check("negative MINMATCHLEN is no filter",
          parse_idx(c.cmd("LCS", "lcs:1", "lcs:2", "IDX", "MINMATCHLEN", "-5"))[0],
          [((4, 7), (5, 8), None), ((2, 3), (0, 1), None)])
    check("WITHMATCHLEN without IDX is ignored",
          c.cmd("LCS", "lcs:1", "lcs:2", "WITHMATCHLEN"), "mytext")
    check("wrong arity", c.cmd("LCS", "lcs:1"),
          err("ERR wrong number of arguments for 'lcs' command"))
    c.cmd("DEL", "lcs:list")
    c.cmd("RPUSH", "lcs:list", "a")
    check("wrong type", c.cmd("LCS", "lcs:1", "lcs:list"),
          err("ERR The specified keys must contain string values"))
    check("wrong type first", c.cmd("LCS", "lcs:list", "lcs:1"),
          err("ERR The specified keys must contain string values"))

    print("randomised vs reference, both routings")
    alphabet = "abcdefg"
    # Long distinctive names spread the pair over the router; short shared prefixes collide it.
    for trial in range(220):
        a = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
        if trial % 2:
            ka, kb = "lcs:same:%d" % trial, "lcs:same:%d" % trial   # identical key: one shard
            c.cmd("SET", ka, a)
            want_a = want_b = a
        else:
            ka = "lcs:r:%d:%s" % (trial, "q" * 30)
            kb = "lcs:s:%d:%s" % (trial, "w" * 30)
            c.cmd("SET", ka, a)
            c.cmd("SET", kb, b)
            want_a, want_b = a, b
        minmatch = rng.choice([0, 0, 2, 3])
        expect_value, expect_len, expect_matches = reference(want_a, want_b, minmatch)

        got = c.cmd("LCS", ka, kb)
        if got != expect_value:
            checks_fail("plain trial %d (%r,%r)" % (trial, want_a, want_b), got, expect_value)
        got_len = c.cmd("LCS", ka, kb, "LEN")
        if got_len != expect_len:
            checks_fail("LEN trial %d" % trial, got_len, expect_len)
        idx, length = parse_idx(
            c.cmd("LCS", ka, kb, "IDX", "MINMATCHLEN", str(minmatch), "WITHMATCHLEN"))
        if length != expect_len:
            checks_fail("IDX len trial %d" % trial, length, expect_len)
        if idx != expect_matches:
            checks_fail("IDX matches trial %d (%r,%r,min=%d)"
                        % (trial, want_a, want_b, minmatch), idx, expect_matches)
        global checks
        checks += 4

    print("larger inputs")
    big_a = "".join(rng.choice("abcd") for _ in range(600))
    big_b = "".join(rng.choice("abcd") for _ in range(600))
    c.cmd("SET", "lcs:big:a" + "z" * 40, big_a)
    c.cmd("SET", "lcs:big:b" + "y" * 40, big_b)
    want_value, want_len, _ = reference(big_a, big_b)
    check("600x600 LEN", c.cmd("LCS", "lcs:big:a" + "z" * 40, "lcs:big:b" + "y" * 40, "LEN"),
          want_len)
    check("600x600 value", c.cmd("LCS", "lcs:big:a" + "z" * 40, "lcs:big:b" + "y" * 40),
          want_value)

    c.close()
    print("\nlcs: %d checks, %d failures -> %s"
          % (checks, len(failures), "PASS" if not failures else "FAIL"))
    for line in failures[:12]:
        print("  " + line)
    return 1 if failures else 0


def checks_fail(label, got, want):
    failures.append("%s: got %r want %r" % (label, got, want))
    print("  FAIL %-44s got=%r want=%r" % (label, str(got)[:40], str(want)[:40]))


if __name__ == "__main__":
    sys.exit(main())
