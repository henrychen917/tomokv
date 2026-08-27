#!/usr/bin/env python3
"""Directed battery for the protocol / argument surface.

Usage: tests/edgeproto.py HOST PORT

Every row here was first observed to DIVERGE from vanilla redis 7.4 (or to kill the server) with
tests/differ.py's `edgeproto` suite or the corpus prober behind it; the expected bytes below are
the ORACLE's, captured from a live 7.4.2 binary, not from a reading of the code. Each row asserts
the exact reply, so a row can only pass when the mechanism it names actually behaves -- there is
no "nothing crashed" pass.

Sections
  1  remote abort: WATCH + disconnect  (P0; runs last, it can leave the server dead)
  2  canonical decimal: redis's string2ll rejects '+5', '05', ' 5', '-0'
  3  error text and validation order on numeric arguments
  4  arity: minimum arity of PFADD/GEOPOS/GEOHASH, truncated HSET arity text, XINFO/XGROUP subarity
  4b option grammar: composed EXPIRE conditions, BITCOUNT/COPY/WAIT/LCS/XREAD/SSCAN messages
  4c exactly one reply per rejected command (XTRIM emitted two and desynchronised the connection)
  5  null shapes: RESP2 null array vs null bulk, RESP3 '_'
  6  geo: coordinate error text must be printable; radius error text
  7  ZRANGE/ZRANGESTORE LIMIT on an index range
  8  unknown-command error text
  9  double formatting past 2^63
"""

import socket
import sys
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])

failures = []
checks = 0


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.append(b"$%d\r\n" % len(arg) + arg + b"\r\n")
    return b"".join(out)


def read_reply(f):
    line = f.readline()
    if not line:
        raise EOFError("server closed the connection")
    kind = line[:1]
    if kind in b"+-:,_#(":
        return line
    if kind in b"$=!":
        n = int(line[1:-2])
        return line if n == -1 else line + f.read(n + 2)
    if kind in b"*~>":
        n = int(line[1:-2])
        return line if n == -1 else line + b"".join(read_reply(f) for _ in range(n))
    if kind in b"%|":
        n = int(line[1:-2])
        return line + b"".join(read_reply(f) for _ in range(n * 2))
    raise AssertionError("unknown RESP marker %r" % line[:16])


class Conn:
    def __init__(self, timeout=10, resp3=False):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")
        if resp3:
            self.cmd("HELLO", "3")

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        return read_reply(self.file)

    def close(self):
        # socket.close() while a makefile is alive only drops an io-ref: the peer sees the
        # disconnect when the LAST reference goes. Close both or the server never runs its
        # connection-close path and section 1 tests nothing.
        try:
            self.file.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def check(label, got, want):
    global checks
    checks += 1
    if got != want:
        failures.append("%s\n      got:  %r\n      want: %r" % (label, got, want))


def expect(conn, argv, want, label=None):
    check(label or " ".join(a if isinstance(a, str) else repr(a) for a in argv),
          conn.cmd(*argv), want)


INT_ERR = b"-ERR value is not an integer or out of range\r\n"
POSITIVE_ERR = b"-ERR value is out of range, must be positive\r\n"
SYNTAX_ERR = b"-ERR syntax error\r\n"


def section_canonical(c):
    """string2ll canonicality: '+5', '05', ' 5', '5 ' and '-0' are NOT integers to redis.

    Every row was a real acceptance before the fix; `LPOP list 05` popped five elements.
    """
    c.cmd("DEL", "ep:l")
    c.cmd("RPUSH", "ep:l", "a", "b", "c", "d", "e")
    c.cmd("DEL", "ep:z")
    c.cmd("ZADD", "ep:z", "1", "a", "2", "b", "3", "c")
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    c.cmd("DEL", "ep:s")
    c.cmd("SADD", "ep:s", "a", "b", "c")
    c.cmd("SET", "ep:str", "hello world")

    for bad in ("05", "+5", " 5", "5 ", "-0", "\t5", "1e3", "0x10", "3.", "+0"):
        expect(c, ["LPOP", "ep:l", bad], POSITIVE_ERR)
        expect(c, ["RPOP", "ep:l", bad], POSITIVE_ERR)
        expect(c, ["LINDEX", "ep:l", bad], INT_ERR)
        expect(c, ["LRANGE", "ep:l", bad, "-1"], INT_ERR)
        expect(c, ["LSET", "ep:l", bad, "z"], INT_ERR)
        expect(c, ["LREM", "ep:l", bad, "a"], INT_ERR)
        expect(c, ["LTRIM", "ep:l", bad, "-1"], INT_ERR)
        expect(c, ["LPOS", "ep:l", "a", "RANK", bad], INT_ERR)
        expect(c, ["LPOS", "ep:l", "a", "COUNT", bad], b"-ERR COUNT can't be negative\r\n")
        expect(c, ["LPOS", "ep:l", "a", "MAXLEN", bad], b"-ERR MAXLEN can't be negative\r\n")
        expect(c, ["SINTERCARD", bad, "ep:s"], b"-ERR numkeys should be greater than 0\r\n")
        expect(c, ["SINTERCARD", "1", "ep:s", "LIMIT", bad], b"-ERR LIMIT can't be negative\r\n")
        expect(c, ["ZINTERCARD", "1", "ep:z", "LIMIT", bad], b"-ERR LIMIT can't be negative\r\n")
        expect(c, ["ZUNIONSTORE", "ep:d", bad, "ep:z"], INT_ERR)
        expect(c, ["XRANGE", "ep:x", "-", "+", "COUNT", bad], INT_ERR)
        expect(c, ["XREVRANGE", "ep:x", "+", "-", "COUNT", bad], INT_ERR)
        expect(c, ["XTRIM", "ep:x", "MAXLEN", bad], INT_ERR)
        expect(c, ["XADD", "ep:x", "MAXLEN", bad, "*", "f", "v"], INT_ERR)
        expect(c, ["WAIT", bad, "1"], INT_ERR)
        expect(c, ["WAIT", "0", bad], b"-ERR timeout is not an integer or out of range\r\n")
        expect(c, ["SLOWLOG", "GET", bad],
               b"-ERR count should be greater than or equal to -1\r\n")
        expect(c, ["LCS", "ep:str", "ep:str", "MINMATCHLEN", bad], INT_ERR)
        expect(c, ["ZRANGESTORE", "ep:d", "ep:z", "(1", "+inf", "BYSCORE", "LIMIT", "0", bad],
               INT_ERR)
    # NEGATIVE CONTROL: the canonical spellings must still work, or the guard is over-tight.
    expect(c, ["LPOP", "ep:l", "0"], b"*0\r\n")
    expect(c, ["LINDEX", "ep:l", "-1"], b"$1\r\ne\r\n")
    expect(c, ["LRANGE", "ep:l", "0", "0"], b"*1\r\n$1\r\na\r\n")
    expect(c, ["SINTERCARD", "1", "ep:s", "LIMIT", "0"], b":3\r\n")
    expect(c, ["XRANGE", "ep:x", "-", "+", "COUNT", "1"],
           b"*1\r\n*2\r\n$3\r\n1-1\r\n*2\r\n$1\r\nf\r\n$1\r\nv\r\n")
    expect(c, ["WAIT", "0", "0"], b":0\r\n")
    expect(c, ["LPOS", "ep:l", "a", "RANK", "-1"], b":0\r\n")
    # LPOP with a real count must still pop exactly that many.
    check("LPOP ep:l 2 pops two", c.cmd("LPOP", "ep:l", "2"), b"*2\r\n$1\r\na\r\n$1\r\nb\r\n")


def section_numeric_text(c):
    """Error TEXT and validation ORDER on numeric arguments."""
    c.cmd("SET", "ep:str", "hello world")
    c.cmd("DEL", "ep:l")
    c.cmd("RPUSH", "ep:l", "a", "b", "c")
    c.cmd("DEL", "ep:s")
    c.cmd("SADD", "ep:s", "a", "b", "c")
    c.cmd("DEL", "ep:zp")
    c.cmd("ZADD", "ep:zp", "1", "a")

    # Expire-time family: redis validates the INTEGER first and the RANGE second, so a
    # non-integer never reaches the "invalid expire time" message.
    for argv in (["SETEX", "ep:e", "abc", "v"],
                 ["PSETEX", "ep:e", "abc", "v"],
                 ["SET", "ep:e", "v", "EX", "abc"],
                 ["SET", "ep:e", "v", "PX", "abc"],
                 ["SET", "ep:e", "v", "EXAT", "abc"],
                 ["GETEX", "ep:str", "EX", "abc"],
                 ["GETEX", "ep:str", "EXAT", "abc"],
                 ["EXPIRE", "ep:str", "abc"],
                 ["PEXPIRE", "ep:str", "abc"],
                 ["EXPIREAT", "ep:str", "abc"],
                 ["PEXPIREAT", "ep:str", "abc"],
                 ["SETEX", "ep:e", "9223372036854775808", "v"],
                 ["GETEX", "ep:str", "EX", "9223372036854775808"]):
        expect(c, argv, INT_ERR)
    # NEGATIVE CONTROL: a well-formed integer out of the allowed range still gets the range text.
    expect(c, ["SETEX", "ep:e", "0", "v"], b"-ERR invalid expire time in 'setex' command\r\n")
    expect(c, ["SETEX", "ep:e", "-1", "v"], b"-ERR invalid expire time in 'setex' command\r\n")
    expect(c, ["PSETEX", "ep:e", "0", "v"], b"-ERR invalid expire time in 'psetex' command\r\n")
    expect(c, ["SET", "ep:e", "v", "EX", "0"], b"-ERR invalid expire time in 'set' command\r\n")
    expect(c, ["GETEX", "ep:str", "EX", "0"], b"-ERR invalid expire time in 'getex' command\r\n")

    # Count arguments answer with redis's positional message, not the generic integer one.
    for argv in (["LPOP", "ep:l", "abc"], ["RPOP", "ep:l", "abc"], ["LPOP", "ep:l", "-1"],
                 ["SPOP", "ep:s", "abc"], ["SPOP", "ep:s", "-1"],
                 ["ZPOPMIN", "ep:zp", "abc"], ["ZPOPMAX", "ep:zp", "-1"]):
        expect(c, argv, POSITIVE_ERR)
    for argv in (["SINTERCARD", "abc", "ep:s"], ["SINTERCARD", "-1", "ep:s"],
                 ["SINTERCARD", "0", "ep:s"]):
        expect(c, argv, b"-ERR numkeys should be greater than 0\r\n")
    expect(c, ["SINTERCARD", "1", "ep:s", "LIMIT", "abc"], b"-ERR LIMIT can't be negative\r\n")
    expect(c, ["ZINTERCARD", "1", "ep:zp", "LIMIT", "abc"], b"-ERR LIMIT can't be negative\r\n")
    expect(c, ["LPOS", "ep:l", "a", "COUNT", "abc"], b"-ERR COUNT can't be negative\r\n")
    expect(c, ["LPOS", "ep:l", "a", "MAXLEN", "-1"], b"-ERR MAXLEN can't be negative\r\n")
    # ...and the random-member family names the bounds it enforces.
    bounds = (b"-ERR value is out of range, value must between "
              b"-9223372036854775807 and 9223372036854775807\r\n")
    expect(c, ["SRANDMEMBER", "ep:s", "-9223372036854775808"], bounds)
    expect(c, ["ZRANDMEMBER", "ep:zp", "-9223372036854775808"], bounds)
    c.cmd("DEL", "ep:h")
    c.cmd("HSET", "ep:h", "f", "1")
    expect(c, ["HRANDFIELD", "ep:h", "-9223372036854775808"], bounds)
    # WAIT names its own argument.
    expect(c, ["WAIT", "0", "abc"], b"-ERR timeout is not an integer or out of range\r\n")
    expect(c, ["WAIT", "abc", "0"], INT_ERR)
    # Stream trim bounds.
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    expect(c, ["XTRIM", "ep:x", "MAXLEN", "-1"], b"-ERR The MAXLEN argument must be >= 0.\r\n")
    expect(c, ["XADD", "ep:x", "MAXLEN", "-1", "*", "f", "v"],
           b"-ERR The MAXLEN argument must be >= 0.\r\n")
    expect(c, ["XTRIM", "ep:x", "MAXLEN", "~", "1", "LIMIT", "-1"],
           b"-ERR The LIMIT argument must be >= 0.\r\n")
    # NEGATIVE CONTROL: valid forms still work.
    expect(c, ["XTRIM", "ep:x", "MAXLEN", "5"], b":0\r\n")
    expect(c, ["SINTERCARD", "1", "ep:s", "LIMIT", "2"], b":2\r\n")


def section_arity(c):
    """Minimum arity of the member-list geo/HLL commands, and container|sub arity."""
    c.cmd("DEL", "ep:hll")
    expect(c, ["PFADD", "ep:hll"], b":1\r\n")
    check("PFADD created the key", c.cmd("EXISTS", "ep:hll"), b":1\r\n")
    expect(c, ["PFADD", "ep:hll"], b":0\r\n")
    check("PFADD key is an HLL", c.cmd("PFCOUNT", "ep:hll"), b":0\r\n")
    c.cmd("DEL", "ep:g")
    c.cmd("GEOADD", "ep:g", "13.361389", "38.115556", "P")
    expect(c, ["GEOPOS", "ep:g"], b"*0\r\n")
    expect(c, ["GEOHASH", "ep:g"], b"*0\r\n")
    expect(c, ["GEOPOS", "ep:missing"], b"*0\r\n")
    # NEGATIVE CONTROL: one below the new minimum is still an arity error.
    expect(c, ["PFADD"], b"-ERR wrong number of arguments for 'pfadd' command\r\n")
    expect(c, ["GEOPOS"], b"-ERR wrong number of arguments for 'geopos' command\r\n")
    expect(c, ["GEOHASH"], b"-ERR wrong number of arguments for 'geohash' command\r\n")

    # HSET's odd-pair message was truncated to "ERR wrong number of arguments".
    expect(c, ["HSET", "ep:h", "f", "1", "g"],
           b"-ERR wrong number of arguments for 'hset' command\r\n")
    expect(c, ["HMSET", "ep:h", "f", "1", "g"],
           b"-ERR wrong number of arguments for 'hmset' command\r\n")

    # XGROUP/XINFO enforced the container arity only, so a wrong-arity subcommand EXECUTED.
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    for argv in (["XGROUP", "CREATE", "ep:x", "g"],
                 ["XGROUP", "DESTROY", "ep:x", "g", "extra"],
                 ["XGROUP", "CREATECONSUMER", "ep:x", "g"],
                 ["XGROUP", "CREATECONSUMER", "ep:x", "g", "c", "extra"],
                 ["XGROUP", "DELCONSUMER", "ep:x", "g"],
                 ["XGROUP", "SETID", "ep:x", "g"]):
        sub = argv[1].lower()
        expect(c, argv, b"-ERR wrong number of arguments for 'xgroup|%s' command\r\n"
               % sub.encode())
    for argv in (["XINFO", "CONSUMERS", "ep:x"],
                 ["XINFO", "CONSUMERS", "ep:x", "g", "extra"],
                 ["XINFO", "GROUPS", "ep:x", "extra"]):
        sub = argv[1].lower()
        expect(c, argv, b"-ERR wrong number of arguments for 'xinfo|%s' command\r\n"
               % sub.encode())
    # An unknown ARM is not a missing key: XINFO looked the key up first and answered
    # "no such key" for "XINFO NOPE somekey", and XGROUP answered NOGROUP.
    expect(c, ["XINFO", "NOPE", "ep:x"], b"-ERR unknown subcommand 'NOPE'. Try XINFO HELP.\r\n")
    expect(c, ["XINFO", "NOPE", "ep:nosuchkey"],
           b"-ERR unknown subcommand 'NOPE'. Try XINFO HELP.\r\n")
    expect(c, ["XGROUP", "NOPE", "ep:x", "g"],
           b"-ERR unknown subcommand 'NOPE'. Try XGROUP HELP.\r\n")
    # NEGATIVE CONTROL: the right arity still runs.
    expect(c, ["XGROUP", "CREATE", "ep:x", "g", "0"], b"+OK\r\n")
    expect(c, ["XGROUP", "CREATECONSUMER", "ep:x", "g", "c"], b":1\r\n")
    expect(c, ["XGROUP", "DESTROY", "ep:x", "g"], b":1\r\n")


def section_options(c):
    """Option grammar: composed EXPIRE conditions, and the messages redis gives by name."""
    # EXPIRE took at most ONE condition (max arity 4), so "EXPIRE key ttl XX GT" -- a legal
    # command -- came back as an arity error, and the illegal combinations had no message of
    # their own.
    c.cmd("SET", "ep:e2", "v")
    c.cmd("PERSIST", "ep:e2")
    expect(c, ["EXPIRE", "ep:e2", "100", "NX", "XX"],
           b"-ERR NX and XX, GT or LT options at the same time are not compatible\r\n")
    expect(c, ["EXPIRE", "ep:e2", "100", "NX", "GT"],
           b"-ERR NX and XX, GT or LT options at the same time are not compatible\r\n")
    expect(c, ["EXPIRE", "ep:e2", "100", "GT", "LT"],
           b"-ERR GT and LT options at the same time are not compatible\r\n")
    expect(c, ["EXPIRE", "ep:e2", "100", "NOPE"], b"-ERR Unsupported option NOPE\r\n")
    # ...and the legal combinations must actually behave. A key with NO ttl counts as an infinite
    # one, so GT can never beat it and XX must still refuse even when LT would have accepted.
    expect(c, ["EXPIRE", "ep:e2", "100", "XX", "GT"], b":0\r\n")
    expect(c, ["EXPIREAT", "ep:e2", "1", "XX", "LT"], b":0\r\n")
    check("XX LT left the key alive", c.cmd("EXISTS", "ep:e2"), b":1\r\n")
    expect(c, ["EXPIRE", "ep:e2", "100", "LT"], b":1\r\n")
    expect(c, ["TTL", "ep:e2"], b":100\r\n")
    expect(c, ["EXPIRE", "ep:e2", "50", "XX", "LT"], b":1\r\n")
    expect(c, ["TTL", "ep:e2"], b":50\r\n")
    expect(c, ["EXPIRE", "ep:e2", "500", "XX", "GT"], b":1\r\n")
    expect(c, ["TTL", "ep:e2"], b":500\r\n")
    expect(c, ["EXPIRE", "ep:e2", "100", "XX", "GT"], b":0\r\n")
    expect(c, ["TTL", "ep:e2"], b":500\r\n")

    # BITCOUNT's maximum arity was 5, so an extra word was an arity error rather than a syntax one.
    c.cmd("SET", "ep:bs", "hello world")
    expect(c, ["BITCOUNT", "ep:bs", "0", "1", "BYTE", "extra"], SYNTAX_ERR)
    expect(c, ["BITCOUNT", "ep:bs", "0", "1", "BIT"], b":1\r\n")     # NEGATIVE CONTROL

    # Messages that name the thing they are about.
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    expect(c, ["XREAD", "STREAMS", "ep:x", "ep:x", "0-0"],
           b"-ERR Unbalanced 'xread' list of streams: for each stream key an ID or '$' "
           b"must be specified.\r\n")
    c.cmd("DEL", "ep:s")
    c.cmd("SADD", "ep:s", "a")
    expect(c, ["SSCAN", "ep:s", "0", "NOVALUES"],
           b"-ERR NOVALUES option can only be used in HSCAN\r\n")

    # COPY's DB index answers a typo as a typo, an int-range overflow with redis's bounds, and
    # only then reports the database itself. WAIT rejects a timeout that would overflow the
    # deadline. LCS parses MINMATCHLEN as a signed long long.
    c.cmd("SET", "ep:cs", "v")
    c.cmd("DEL", "ep:cd")
    expect(c, ["COPY", "ep:cs", "ep:cd", "DB", "abc"], INT_ERR)
    expect(c, ["COPY", "ep:cs", "ep:cd", "DB", "+5"], INT_ERR)
    expect(c, ["COPY", "ep:cs", "ep:cd", "DB", "2147483648"],
           b"-ERR value is out of range, value must between -2147483648 and 2147483647\r\n")
    expect(c, ["COPY", "ep:cs", "ep:cd", "DB", "0"], b":1\r\n")      # NEGATIVE CONTROL
    expect(c, ["WAIT", "0", "9223372036854775807"], b"-ERR timeout is out of range\r\n")
    expect(c, ["WAIT", "0", "9223372036854775"], b":0\r\n")          # NEGATIVE CONTROL
    expect(c, ["LCS", "ep:cs", "ep:cs", "MINMATCHLEN", "9223372036854775808"], INT_ERR)
    expect(c, ["LCS", "ep:cs", "ep:cs", "MINMATCHLEN", "9223372036854775807"], b"$1\r\nv\r\n")


def section_one_reply(c):
    """A rejected command must put EXACTLY ONE reply on the wire.

    XTRIM's option errors emitted two: the handler wrote the real error through op.sink(), which
    puts a short reply in the direct region and leaves op.reply empty, and the caller's
    "did I already answer?" guard read op.reply alone, decided nothing had been written, and
    appended a second 'syntax error'. Every later reply on that connection was then off by one,
    which is worse than any wrong error string. The sentinel below is the whole test: a second
    reply shows up in place of the ECHO.
    """
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    cases = [
        (["XTRIM", "ep:x", "MINID", "notanid"],
         b"-ERR Invalid stream ID specified as stream command argument\r\n"),
        (["XTRIM", "ep:x", "BOGUS", "1"], SYNTAX_ERR),
        (["XTRIM", "ep:x", "MAXLEN", "abc"], INT_ERR),
        (["XTRIM", "ep:x", "MAXLEN", "-1"], b"-ERR The MAXLEN argument must be >= 0.\r\n"),
        (["XTRIM", "ep:x", "MAXLEN", "~", "1", "LIMIT", "-1"],
         b"-ERR The LIMIT argument must be >= 0.\r\n"),
        (["XTRIM", "ep:x", "MAXLEN", "5"], b":0\r\n"),          # NEGATIVE CONTROL: success path
    ]
    for argv, want in cases:
        c.sock.sendall(encode(*argv) + encode("ECHO", "EPSENT"))
        first = read_reply(c.file)
        second = read_reply(c.file)
        check("one reply for %s" % " ".join(argv), (first, second),
              (want, b"$6\r\nEPSENT\r\n"))
        while second != b"$6\r\nEPSENT\r\n":       # resynchronise so later rows stay meaningful
            second = read_reply(c.file)


def section_nulls(c3):
    """Null SHAPES: RESP2 null-array vs null-bulk, and RESP3 '_'."""
    c = Conn()
    c.cmd("DEL", "ep:nl", "ep:nd")
    # BRPOPLPUSH/BLMOVE answer a timeout with a null ARRAY in RESP2.
    expect(c, ["BRPOPLPUSH", "ep:nl", "ep:nd", "0.01"], b"*-1\r\n")
    expect(c, ["BLMOVE", "ep:nl", "ep:nd", "LEFT", "RIGHT", "0.01"], b"*-1\r\n")
    # ...while a plain missing-key GET stays a null BULK. (Negative control for the row above.)
    expect(c, ["GET", "ep:nomissing"], b"$-1\r\n")
    expect(c, ["BLPOP", "ep:nl", "0.01"], b"*-1\r\n")
    # XRANGE with a negative COUNT is a null array, not an error.
    c.cmd("DEL", "ep:x")
    c.cmd("XADD", "ep:x", "1-1", "f", "v")
    expect(c, ["XRANGE", "ep:x", "-", "+", "COUNT", "-1"], b"*-1\r\n")
    expect(c, ["XREVRANGE", "ep:x", "+", "-", "COUNT", "-1"], b"*-1\r\n")
    # NEGATIVE CONTROL: a usable COUNT still returns the entries. (COUNT 0 is ALSO a null
    # array on redis -- only a positive count produces a list -- so it cannot serve as the
    # control here.)
    expect(c, ["XRANGE", "ep:x", "-", "+", "COUNT", "2"],
           b"*1\r\n*2\r\n$3\r\n1-1\r\n*2\r\n$1\r\nf\r\n$1\r\nv\r\n")
    expect(c, ["XRANGE", "ep:x", "-", "+", "COUNT", "0"], b"*-1\r\n")
    c.close()

    # RESP3 renders every null as '_', including DUMP's.
    expect(c3, ["DUMP", "ep:nomissing"], b"_\r\n")
    expect(c3, ["GET", "ep:nomissing"], b"_\r\n")
    expect(c3, ["BRPOPLPUSH", "ep:nl", "ep:nd", "0.01"], b"_\r\n")
    expect(c3, ["XRANGE", "ep:x", "-", "+", "COUNT", "-1"], b"_\r\n")
    # NEGATIVE CONTROL: a present DUMP is still a bulk string.
    c3.cmd("SET", "ep:dk", "v")
    check("RESP3 DUMP present is a bulk", c3.cmd("DUMP", "ep:dk")[:1], b"$")


def section_geo(c):
    """A rejected coordinate must come back as PRINTABLE text, not raw double bytes."""
    c.cmd("DEL", "ep:g")
    c.cmd("GEOADD", "ep:g", "13.361389", "38.115556", "P")
    reply = c.cmd("GEOADD", "ep:ga", "1e100", "0", "m")
    checks_ok = reply.startswith(b"-ERR invalid longitude,latitude pair ")
    printable = all(32 <= b < 127 or b in (13, 10) for b in reply)
    check("GEOADD 1e100 error is printable ascii", (checks_ok, printable), (True, True))
    check("GEOADD 1e100 error body", reply,
          b"-ERR invalid longitude,latitude pair 100000000000000001590289110975991804683608085639"
          b"45281389781327557747838772170381060813469985856815104.000000,0.000000\r\n")
    reply = c.cmd("GEOADD", "ep:ga", "0", "1e100", "m")
    check("GEOADD lat 1e100 error is printable ascii",
          all(32 <= b < 127 or b in (13, 10) for b in reply), True)
    # Radius parse failure has its own message.
    for bad in ("abc", " 5", "", "nan"):
        expect(c, ["GEOSEARCH", "ep:g", "FROMLONLAT", "0", "0", "BYRADIUS", bad, "m"],
               b"-ERR need numeric radius\r\n")
    # NEGATIVE CONTROL: a good radius still searches.
    expect(c, ["GEOSEARCH", "ep:g", "FROMLONLAT", "13.361389", "38.115556", "BYRADIUS", "1", "km"],
           b"*1\r\n$1\r\nP\r\n")


def section_zrange_limit(c):
    """LIMIT on an index range is rejected only when the COUNT is not the -1 default."""
    c.cmd("DEL", "ep:z", "ep:zd")
    c.cmd("ZADD", "ep:z", "1", "a", "2", "b", "3", "c")
    three = b"*3\r\n$1\r\na\r\n$1\r\nb\r\n$1\r\nc\r\n"
    expect(c, ["ZRANGE", "ep:z", "0", "-1", "LIMIT", "0", "-1"], three)
    expect(c, ["ZRANGE", "ep:z", "0", "-1", "LIMIT", "5", "-1"], three)
    expect(c, ["ZRANGE", "ep:z", "0", "-1", "LIMIT", "-1", "-1"], three)
    expect(c, ["ZRANGESTORE", "ep:zd", "ep:z", "0", "-1", "LIMIT", "0", "-1"], b":3\r\n")
    # NEGATIVE CONTROL: a LIMIT that would actually bound the answer is still refused.
    refused = (b"-ERR syntax error, LIMIT is only supported in combination with either "
               b"BYSCORE or BYLEX\r\n")
    expect(c, ["ZRANGE", "ep:z", "0", "-1", "LIMIT", "1", "2"], refused)
    expect(c, ["ZRANGE", "ep:z", "0", "-1", "LIMIT", "0", "0"], refused)
    expect(c, ["ZRANGESTORE", "ep:zd", "ep:z", "0", "-1", "LIMIT", "1", "2"], refused)


def section_unknown_command(c):
    """The unknown-command error names the command and echoes the first arguments."""
    expect(c, ["NOSUCHCOMMAND"],
           b"-ERR unknown command 'NOSUCHCOMMAND', with args beginning with: \r\n")
    expect(c, ["NOSUCHCOMMAND", "a", "b"],
           b"-ERR unknown command 'NOSUCHCOMMAND', with args beginning with: 'a' 'b' \r\n")
    expect(c, ["quit2", "x"],
           b"-ERR unknown command 'quit2', with args beginning with: 'x' \r\n")
    # NEGATIVE CONTROL: a known command with bad arity keeps the arity message.
    expect(c, ["GET"], b"-ERR wrong number of arguments for 'get' command\r\n")


def section_double_format(c):
    """Doubles past the signed-64 range print as redis prints them (shortest round-trip)."""
    c.cmd("DEL", "ep:dz")
    expect(c, ["ZADD", "ep:dz", "INCR", "9223372036854775808", "m"],
           b"$19\r\n9223372036854776000\r\n")
    expect(c, ["ZSCORE", "ep:dz", "m"], b"$19\r\n9223372036854776000\r\n")
    c.cmd("DEL", "ep:dz2")
    expect(c, ["ZINCRBY", "ep:dz2", "-9223372036854775809", "m"],
           b"$20\r\n-9223372036854776000\r\n")
    # NEGATIVE CONTROL: values inside the range still print as exact integers.
    c.cmd("DEL", "ep:dz3")
    expect(c, ["ZADD", "ep:dz3", "INCR", "9007199254740993", "m"],
           b"$16\r\n9007199254740992\r\n")
    expect(c, ["ZADD", "ep:dz3", "INCR", "0", "m2"], b"$1\r\n0\r\n")


def section_watch_disconnect():
    """P0: a connection that closes while it still WATCHes a key aborted the whole server.

    The cleanup fragment is posted with no client and no op (multi.inc's own tail handles
    op_id == UINT64_MAX), but the notify-v2 carrier check in front of it called std::abort().
    """
    global checks
    victim = Conn()
    reply = victim.cmd("WATCH", "ep:watchkey")
    check("WATCH replies OK", reply, b"+OK\r\n")
    victim.close()
    time.sleep(0.5)
    checks += 1
    for _ in range(20):
        try:
            probe = Conn(timeout=3)
            alive = probe.cmd("PING")
            probe.close()
            if alive == b"+PONG\r\n":
                return True
        except (OSError, EOFError):
            time.sleep(0.1)
    failures.append("WATCH + disconnect killed the server (no PING after 2s)")
    return False


def main():
    c = Conn()
    if c.cmd("PING") != b"+PONG\r\n":
        print("edgeproto: server did not answer PING")
        return 2
    section_canonical(c)
    section_numeric_text(c)
    section_arity(c)
    section_options(c)
    section_one_reply(c)
    c3 = Conn(resp3=True)
    section_nulls(c3)
    c3.close()
    section_geo(c)
    section_zrange_limit(c)
    section_unknown_command(c)
    section_double_format(c)
    c.close()
    alive = section_watch_disconnect()

    for line in failures:
        print("  FAIL %s" % line)
    print("edgeproto: %d checks, %d failures -> %s" %
          (checks, len(failures), "PASS" if not failures else "FAIL"))
    if not alive:
        print("edgeproto: server is DOWN after the WATCH row; later runs need a fresh boot")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
