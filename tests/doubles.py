#!/usr/bin/env python3
"""Directed double battery: the text a score is rendered as, and the spellings a float argument
may be written in.

    tests/doubles.py HOST PORT

Every row is an exact reply, and the whole battery passes unchanged against the redis 7.4 oracle
(`redis-server --port P --save '' --enable-debug-command yes`), which is what makes it a parity
battery rather than a transcript of current behaviour. Run it against the oracle first if you
change a row.

Two campaigns are locked here.

FORMAT. Redis renders every double through Grisu2, which is round-trip correct but not always the
SHORTEST digit string; std::to_chars is shortest. The rows in section 1 are values where the two
disagree -- 1e126 is "9.999999999999999e+125" on redis and would be "1e+126" from to_chars -- so
each of them fails loudly if the formatter is ever swapped back.

PARSE. Redis has three float grammars, not one, and which applies depends on the argument:

  * a VALUE (score, weight, coordinate, radius) uses getDoubleFromObject: no empty string, no
    leading space, an out-of-range magnitude refused, NaN refused -- but hexadecimal accepted,
    because strtod accepts it;
  * a score RANGE BOUND uses a bare strtod: "" is 0, " 5" is 5, "1e309" is +inf;
  * numeric SORT is that same bare strtod plus an ERANGE test, so a subnormal is refused where a
    score would keep it.

Every rejection below sits next to an accepted spelling of the same argument, and every rejection
that could have written something is followed by a read proving it wrote nothing. An over-tight
parser and an over-loose one both turn this battery red.
"""

import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])

checks = 0
failures = []


def encode(args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        out += [b"$%d\r\n" % len(a), a, b"\r\n"]
    return b"".join(out)


class Conn:
    def __init__(self, timeout=20):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def read_raw(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed the connection")
        marker = line[:1]
        if marker in b"+-:,_#(":
            return line
        if marker in (b"$", b"=", b"!"):
            size = int(line[1:-2])
            return line if size == -1 else line + self.file.read(size + 2)
        if marker in (b"*", b"~", b">"):
            count = int(line[1:-2])
            return line if count == -1 else line + b"".join(
                self.read_raw() for _ in range(count))
        if marker in (b"%", b"|"):
            count = int(line[1:-2])
            return line + b"".join(self.read_raw() for _ in range(count * 2))
        raise AssertionError("unsupported RESP marker: %r" % line)

    def command(self, *args):
        self.sock.sendall(encode(args))
        return self.read_raw()

    def send_only(self, *args):
        self.sock.sendall(encode(args))

    def close(self):
        # Closing the socket while a makefile is alive only drops one io reference; the peer sees
        # the disconnect when the LAST one dies. Both, in this order, or the server never runs its
        # connection-close path.
        self.file.close()
        self.sock.close()


def expect(actual, wanted, label):
    global checks
    checks += 1
    if actual == wanted:
        print("  ok   %s" % label, flush=True)
    else:
        failures.append(label)
        print("  FAIL %s\n         got    %r\n         wanted %r" % (label, actual, wanted),
              flush=True)


def section(title):
    print("\n== %s ==" % title, flush=True)


# --------------------------------------------------------------------------- 1. score TEXT

def section_format(c):
    section("1. score text: Grisu2 digits, then redis's fixed/scientific rule")
    expect(c.command("DEL", "d:f"), b":0\r\n", "clean formatter key")

    # Values where Grisu2's digits are NOT the shortest round-trip digits. Every one of these
    # renders differently under std::to_chars, so the row fails if the formatter regresses.
    grisu = [
        ("1e126", b"$22\r\n9.999999999999999e+125\r\n", "1e126 keeps Grisu2's 16 digits"),
        ("1000000000000000.2", b"$18\r\n1000000000000000.3\r\n", "last digit rounds Grisu2's way"),
        ("7.18288826277728e18", b"$19\r\n7182888262777281000\r\n", "padded integer, Grisu2 digits"),
        ("-1.1919455290949598e-37", b"$23\r\n-1.1919455290949599e-37\r\n",
         "negative exponent, last digit"),
        ("9474039721387.188", b"$17\r\n9474039721387.187\r\n", "fixed notation, last digit"),
    ]
    for index, (value, wanted, label) in enumerate(grisu):
        expect(c.command("ZINCRBY", "d:f", value, "g%d" % index), wanted, label)

    # The rendering RULE: which values print as integers, where fixed turns into scientific, and
    # the signed-zero and infinity spellings.
    rule = [
        ("1e23", b"$23\r\n99999999999999990000000\r\n", "1e23 is a padded integer, not 1e+23"),
        ("9223372036854775808", b"$19\r\n9223372036854776000\r\n",
         "2^63 is past the integral fast path"),
        ("4611686018427387904", b"$19\r\n4611686018427387904\r\n",
         "2^62 is the inclusive top of the integral fast path"),
        ("-4611686018427387904", b"$20\r\n-4611686018427387904\r\n",
         "-2^62 is the inclusive bottom"),
        ("1e15", b"$16\r\n1000000000000000\r\n", "1e15 prints as an integer"),
        ("1e18", b"$19\r\n1000000000000000000\r\n", "1e18 prints as an integer"),
        ("1e-5", b"$7\r\n0.00001\r\n", "1e-5 is fixed"),
        ("1e-6", b"$8\r\n0.000001\r\n", "1e-6 is fixed"),
        ("1e-7", b"$4\r\n1e-7\r\n", "1e-7 crosses to scientific, exponent unpadded"),
        ("5e-324", b"$6\r\n5e-324\r\n", "the smallest subnormal"),
        ("1.7976931348623157e308", b"$23\r\n1.7976931348623157e+308\r\n", "the largest finite"),
        ("3.141592653589793", b"$17\r\n3.141592653589793\r\n", "an ordinary fraction"),
        ("0.5", b"$3\r\n0.5\r\n", "NEGATIVE CONTROL: a value both algorithms spell the same"),
        ("inf", b"$3\r\ninf\r\n", "infinity"),
        ("-inf", b"$4\r\n-inf\r\n", "negative infinity"),
    ]
    for index, (value, wanted, label) in enumerate(rule):
        expect(c.command("ZINCRBY", "d:f", value, "r%d" % index), wanted, label)

    # One formatter, every score-shaped reply.
    expect(c.command("DEL", "d:sh"), b":0\r\n", "clean shared-formatter key")
    expect(c.command("ZADD", "d:sh", "1e126", "m"), b":1\r\n", "shared-formatter member stored")
    expect(c.command("ZSCORE", "d:sh", "m"), b"$22\r\n9.999999999999999e+125\r\n",
           "ZSCORE shares the formatter")
    expect(c.command("ZMSCORE", "d:sh", "m", "gone"),
           b"*2\r\n$22\r\n9.999999999999999e+125\r\n$-1\r\n", "ZMSCORE shares the formatter")
    expect(c.command("ZRANGE", "d:sh", "0", "-1", "WITHSCORES"),
           b"*2\r\n$1\r\nm\r\n$22\r\n9.999999999999999e+125\r\n",
           "WITHSCORES shares the formatter")
    expect(c.command("ZPOPMIN", "d:sh"),
           b"*2\r\n$1\r\nm\r\n$22\r\n9.999999999999999e+125\r\n", "ZPOPMIN shares the formatter")

    # A signed zero survives ZADD INCR and is flattened by a plain ZADD, exactly as on redis.
    expect(c.command("DEL", "d:z"), b":0\r\n", "clean signed-zero key")
    expect(c.command("ZADD", "d:z", "INCR", "-0", "neg"), b"$2\r\n-0\r\n",
           "ZADD INCR keeps a negative zero")
    expect(c.command("ZADD", "d:z", "-0", "plain"), b":1\r\n", "plain ZADD of a negative zero")
    expect(c.command("ZSCORE", "d:z", "plain"), b"$1\r\n0\r\n",
           "NEGATIVE CONTROL: a stored -0 reads back as 0")


# --------------------------------------------------------------------------- 2. VALUE grammar

def section_value_grammar(c):
    section("2. score VALUE grammar: getDoubleFromObject")
    expect(c.command("DEL", "d:v"), b":0\r\n", "clean value key")

    accepted = [
        ("0x10", b"$2\r\n16\r\n", "hexadecimal integer"),
        ("0X1A", b"$2\r\n26\r\n", "upper-case hexadecimal"),
        ("0x1p-2", b"$4\r\n0.25\r\n", "hexadecimal float"),
        ("+5", b"$1\r\n5\r\n", "leading plus"),
        ("05", b"$1\r\n5\r\n", "leading zero"),
        (".5", b"$3\r\n0.5\r\n", "leading point"),
        ("5.", b"$1\r\n5\r\n", "trailing point"),
        ("5e-324", b"$6\r\n5e-324\r\n", "a subnormal is a legal score"),
        ("infinity", b"$3\r\ninf\r\n", "the word infinity"),
        ("INF", b"$3\r\ninf\r\n", "upper-case inf"),
    ]
    for index, (value, wanted, label) in enumerate(accepted):
        expect(c.command("ZADD", "d:v", "INCR", value, "v%d" % index), wanted,
               "ZADD accepts %s" % label)

    rejected = [
        ("", "empty string"),
        (" 5", "leading space"),
        ("\t5", "leading tab"),
        ("5 ", "trailing space"),
        ("5\x005", "embedded NUL"),
        ("1e309", "magnitude past double range"),
        ("-1e309", "negative magnitude past double range"),
        ("1e-400", "magnitude that underflows to zero"),
        ("nan", "NaN"),
        ("-nan", "negative NaN"),
        ("abc", "a word"),
        ("5abc", "trailing text"),
        ("++5", "a doubled sign"),
        ("1e", "a truncated exponent"),
        (".", "a bare point"),
    ]
    expect(c.command("DEL", "d:neg"), b":0\r\n", "clean rejection key")
    for value, label in rejected:
        expect(c.command("ZADD", "d:neg", value, "m"), b"-ERR value is not a valid float\r\n",
               "ZADD refuses %s" % label)
    expect(c.command("ZCARD", "d:neg"), b":0\r\n",
           "no refused ZADD wrote a member")
    expect(c.command("ZADD", "d:neg", "5", "m"), b":1\r\n",
           "NEGATIVE CONTROL: the same key still takes an ordinary score")

    # ZINCRBY and the ZADD flag forms take the same grammar.
    expect(c.command("DEL", "d:inc"), b":0\r\n", "clean increment key")
    expect(c.command("ZADD", "d:inc", "1", "m"), b":1\r\n", "increment control seeded")
    expect(c.command("ZINCRBY", "d:inc", "0x10", "m"), b"$2\r\n17\r\n", "ZINCRBY accepts hex")
    expect(c.command("ZINCRBY", "d:inc", " 1", "m"),
           b"-ERR value is not a valid float\r\n", "ZINCRBY refuses a leading space")
    expect(c.command("ZSCORE", "d:inc", "m"), b"$2\r\n17\r\n",
           "the refused ZINCRBY did not move the score")
    expect(c.command("ZADD", "d:inc", "GT", "CH", "0x20", "m"), b":1\r\n",
           "ZADD GT accepts hex")
    expect(c.command("ZSCORE", "d:inc", "m"), b"$2\r\n32\r\n", "ZADD GT applied the hex score")

    # Weights are values too.
    expect(c.command("DEL", "d:w", "d:wd"), b":0\r\n", "clean weight keys")
    expect(c.command("ZADD", "d:w", "1", "a", "2", "b"), b":2\r\n", "weight source seeded")
    expect(c.command("ZUNION", "1", "d:w", "WEIGHTS", "0x10", "WITHSCORES"),
           b"*4\r\n$1\r\na\r\n$2\r\n16\r\n$1\r\nb\r\n$2\r\n32\r\n", "WEIGHTS accepts hex")
    expect(c.command("ZUNIONSTORE", "d:wd", "1", "d:w", "WEIGHTS", "1e309"),
           b"-ERR weight value is not a float\r\n", "WEIGHTS refuses an out-of-range magnitude")
    expect(c.command("EXISTS", "d:wd"), b":0\r\n", "the refused ZUNIONSTORE wrote no destination")
    expect(c.command("ZINTERSTORE", "d:wd", "1", "d:w", "WEIGHTS", " 1"),
           b"-ERR weight value is not a float\r\n", "WEIGHTS refuses a leading space")
    expect(c.command("EXISTS", "d:wd"), b":0\r\n",
           "NEGATIVE CONTROL: still nothing at the destination")
    expect(c.command("ZINTERSTORE", "d:wd", "1", "d:w", "WEIGHTS", "2"), b":2\r\n",
           "NEGATIVE CONTROL: an ordinary weight still stores")


# --------------------------------------------------------------------------- 3. RANGE grammar

def section_range_grammar(c):
    section("3. score RANGE grammar: a bare strtod, so looser than a value")
    expect(c.command("DEL", "d:r"), b":0\r\n", "clean range key")
    expect(c.command("ZADD", "d:r", "-5", "a", "0", "b", "5", "c", "16", "d"), b":4\r\n",
           "range corpus seeded")

    # Each of these is an ERROR under the value grammar and a RESULT under the bound grammar.
    expect(c.command("ZCOUNT", "d:r", "", "+inf"), b":3\r\n",
           "an empty min is zero, not an error")
    expect(c.command("ZCOUNT", "d:r", "(", "+inf"), b":2\r\n",
           "a bare '(' is an exclusive zero")
    expect(c.command("ZRANGEBYSCORE", "d:r", " 5", "+inf"), b"*2\r\n$1\r\nc\r\n$1\r\nd\r\n",
           "a leading space is skipped")
    expect(c.command("ZRANGEBYSCORE", "d:r", "\t\n 5", "+inf"),
           b"*2\r\n$1\r\nc\r\n$1\r\nd\r\n", "any leading whitespace is skipped")
    expect(c.command("ZRANGE", "d:r", "0x10", "+inf", "BYSCORE"), b"*1\r\n$1\r\nd\r\n",
           "a hexadecimal bound is 16")
    expect(c.command("ZRANGE", "d:r", "(0x10", "+inf", "BYSCORE"), b"*0\r\n",
           "an exclusive hexadecimal bound")
    expect(c.command("ZCOUNT", "d:r", "1e309", "+inf"), b":0\r\n",
           "an overflowing bound saturates to +inf instead of erroring")
    expect(c.command("ZCOUNT", "d:r", "-1e309", "+inf"), b":4\r\n",
           "and to -inf on the other side")
    expect(c.command("ZCOUNT", "d:r", "1e-400", "+inf"), b":3\r\n",
           "an underflowing bound is zero")
    expect(c.command("ZCOUNT", "d:r", "5\x005", "+inf"), b":2\r\n",
           "a bound ends at an embedded NUL, as it does on redis")
    expect(c.command("ZREVRANGEBYSCORE", "d:r", "", "-inf"),
           b"*2\r\n$1\r\nb\r\n$1\r\na\r\n", "the max bound takes the same grammar")

    # The bound grammar is looser, not absent.
    still_refused = [
        ("nan", "NaN"),
        ("5 ", "trailing space"),
        ("abc", "a word"),
        ("5abc", "trailing text"),
        ("++5", "a doubled sign"),
        (".", "a bare point"),
        ("1e", "a truncated exponent"),
        (" (5", "a space before the exclusive marker"),
    ]
    for value, label in still_refused:
        expect(c.command("ZCOUNT", "d:r", value, "+inf"),
               b"-ERR min or max is not a float\r\n", "a bound still refuses %s" % label)

    # Ranges that WRITE take the same grammar, and a refused one must not write.
    expect(c.command("DEL", "d:rd"), b":0\r\n", "clean range destination")
    expect(c.command("ZRANGESTORE", "d:rd", "d:r", "", "+inf", "BYSCORE"), b":3\r\n",
           "ZRANGESTORE accepts an empty min")
    expect(c.command("ZRANGE", "d:rd", "0", "-1"),
           b"*3\r\n$1\r\nb\r\n$1\r\nc\r\n$1\r\nd\r\n", "and stored what the bound selected")
    expect(c.command("ZRANGESTORE", "d:rd", "d:r", "nan", "+inf", "BYSCORE"),
           b"-ERR min or max is not a float\r\n", "ZRANGESTORE still refuses NaN")
    expect(c.command("ZRANGE", "d:rd", "0", "-1"),
           b"*3\r\n$1\r\nb\r\n$1\r\nc\r\n$1\r\nd\r\n",
           "NEGATIVE CONTROL: the refused ZRANGESTORE left the destination alone")
    expect(c.command("DEL", "d:rw"), b":0\r\n", "clean remove-range key")
    expect(c.command("ZADD", "d:rw", "1", "a", "2", "b"), b":2\r\n", "remove-range seeded")
    expect(c.command("ZREMRANGEBYSCORE", "d:rw", "", "(-inf"), b":0\r\n",
           "ZREMRANGEBYSCORE accepts an empty min and removes nothing for this range")
    expect(c.command("ZCARD", "d:rw"), b":2\r\n", "and left both members")


# --------------------------------------------------------------------------- 4. long doubles

def section_long_double(c):
    section("4. INCRBYFLOAT and HINCRBYFLOAT: the string2ld grammar")
    expect(c.command("DEL", "d:lf", "d:lh"), b":0\r\n", "clean long-double keys")
    expect(c.command("INCRBYFLOAT", "d:lf", "0x1p-2"), b"$4\r\n0.25\r\n",
           "INCRBYFLOAT accepts a hexadecimal float")
    expect(c.command("INCRBYFLOAT", "d:lf", "+0.25"), b"$3\r\n0.5\r\n",
           "INCRBYFLOAT accepts a leading plus")
    expect(c.command("INCRBYFLOAT", "d:lf", " 1"), b"-ERR value is not a valid float\r\n",
           "INCRBYFLOAT refuses a leading space")
    expect(c.command("INCRBYFLOAT", "d:lf", "nan"), b"-ERR value is not a valid float\r\n",
           "INCRBYFLOAT refuses NaN")
    expect(c.command("INCRBYFLOAT", "d:lf", "inf"),
           b"-ERR increment would produce NaN or Infinity\r\n",
           "an infinite increment parses, then fails the result check")
    expect(c.command("GET", "d:lf"), b"$3\r\n0.5\r\n", "no refused increment moved the value")
    expect(c.command("HINCRBYFLOAT", "d:lh", "f", "0x1p-2"), b"$4\r\n0.25\r\n",
           "HINCRBYFLOAT accepts a hexadecimal float")
    expect(c.command("HINCRBYFLOAT", "d:lh", "f", "\t1"),
           b"-ERR value is not a valid float\r\n", "HINCRBYFLOAT refuses a leading tab")
    expect(c.command("HGET", "d:lh", "f"), b"$4\r\n0.25\r\n",
           "the refused hash increment left the field alone")
    # The STORED value takes the same grammar as the increment.
    expect(c.command("SET", "d:lf2", "0x10"), b"+OK\r\n", "a hex string stored by SET")
    expect(c.command("INCRBYFLOAT", "d:lf2", "1"), b"$2\r\n17\r\n",
           "INCRBYFLOAT reads the stored value with the same grammar")
    expect(c.command("SET", "d:lf3", " 1"), b"+OK\r\n", "a spaced string stored by SET")
    expect(c.command("INCRBYFLOAT", "d:lf3", "1"), b"-ERR value is not a valid float\r\n",
           "NEGATIVE CONTROL: a stored leading space is still refused")


# --------------------------------------------------------------------------- 5. GEO

def section_geo(c):
    section("5. GEO coordinates, radii and box sides")
    expect(c.command("DEL", "d:g"), b":0\r\n", "clean geo key")
    expect(c.command("GEOADD", "d:g", "0x10", "0", "hex"), b":1\r\n",
           "GEOADD accepts a hexadecimal longitude")
    expect(c.command("GEOADD", "d:g", "0x1p-2", "0", "hexfrac"), b":1\r\n",
           "GEOADD accepts a hexadecimal float longitude")
    expect(c.command("GEOADD", "d:g", "1e309", "0", "over"),
           b"-ERR value is not a valid float\r\n", "GEOADD refuses an out-of-range longitude")
    expect(c.command("GEOADD", "d:g", " 5", "0", "space"),
           b"-ERR value is not a valid float\r\n", "GEOADD refuses a leading space")
    expect(c.command("GEOADD", "d:g", "inf", "0", "infinite"),
           b"-ERR invalid longitude,latitude pair inf,0.000000\r\n",
           "an infinite coordinate parses, then fails the range check")
    expect(c.command("ZCARD", "d:g"), b":2\r\n", "only the two accepted coordinates are stored")
    expect(c.command("GEOSEARCH", "d:g", "FROMLONLAT", "16", "0", "BYRADIUS", "0x10", "km"),
           b"*1\r\n$3\r\nhex\r\n", "GEOSEARCH accepts a hexadecimal radius")
    expect(c.command("GEOSEARCH", "d:g", "FROMLONLAT", "16", "0", "BYBOX", "0x10", "0x10", "km"),
           b"*1\r\n$3\r\nhex\r\n", "GEOSEARCH accepts hexadecimal box sides")
    expect(c.command("GEOSEARCH", "d:g", "FROMLONLAT", "16", "0", "BYRADIUS", "1e309", "km"),
           b"-ERR need numeric radius\r\n", "GEOSEARCH refuses an out-of-range radius")
    expect(c.command("GEOSEARCH", "d:g", "FROMLONLAT", "16", "0", "BYRADIUS", "-1", "km"),
           b"-ERR radius cannot be negative\r\n",
           "NEGATIVE CONTROL: a negative radius keeps its own message")
    expect(c.command("GEORADIUS_RO", "d:g", "16", "0", "0x10", "km"),
           b"*1\r\n$3\r\nhex\r\n", "GEORADIUS_RO accepts a hexadecimal radius")
    expect(c.command("GEORADIUSBYMEMBER_RO", "d:g", "hex", "0x10", "km"),
           b"*1\r\n$3\r\nhex\r\n", "GEORADIUSBYMEMBER_RO accepts a hexadecimal radius")
    expect(c.command("DEL", "d:gd"), b":0\r\n", "clean geo destination")
    expect(c.command("GEOSEARCHSTORE", "d:gd", "d:g", "FROMLONLAT", "16", "0",
                     "BYRADIUS", "1e309", "km"),
           b"-ERR need numeric radius\r\n", "GEOSEARCHSTORE refuses an out-of-range radius")
    expect(c.command("EXISTS", "d:gd"), b":0\r\n", "and wrote no destination")
    expect(c.command("GEOSEARCHSTORE", "d:gd", "d:g", "FROMLONLAT", "16", "0",
                     "BYRADIUS", "0x10", "km"), b":1\r\n",
           "NEGATIVE CONTROL: a hexadecimal radius still stores")


# --------------------------------------------------------------------------- 6. SORT

def section_sort(c):
    section("6. numeric SORT: a bare strtod with an ERANGE test")
    expect(c.command("DEL", "d:s"), b":0\r\n", "clean sort key")
    expect(c.command("RPUSH", "d:s", "", "1"), b":2\r\n", "empty-element list seeded")
    expect(c.command("SORT", "d:s"), b"*2\r\n$0\r\n\r\n$1\r\n1\r\n",
           "an empty element sorts as zero")
    expect(c.command("DEL", "d:s"), b":1\r\n", "sort key cleared")
    expect(c.command("RPUSH", "d:s", " 5", "1"), b":2\r\n", "spaced-element list seeded")
    expect(c.command("SORT", "d:s"), b"*2\r\n$1\r\n1\r\n$2\r\n 5\r\n",
           "a leading space sorts as five")
    expect(c.command("DEL", "d:s"), b":1\r\n", "sort key cleared")
    expect(c.command("RPUSH", "d:s", "0x10", "1"), b":2\r\n", "hex-element list seeded")
    expect(c.command("SORT", "d:s"), b"*2\r\n$1\r\n1\r\n$4\r\n0x10\r\n",
           "a hexadecimal element sorts as sixteen")
    expect(c.command("DEL", "d:s"), b":1\r\n", "sort key cleared")
    expect(c.command("RPUSH", "d:s", "5e-324", "1"), b":2\r\n", "subnormal-element list seeded")
    expect(c.command("SORT", "d:s"),
           b"-ERR One or more scores can't be converted into double\r\n",
           "a subnormal element is refused, because strtod raises ERANGE for it")
    expect(c.command("SORT_RO", "d:s"),
           b"-ERR One or more scores can't be converted into double\r\n",
           "SORT_RO takes the same grammar")
    expect(c.command("DEL", "d:s"), b":1\r\n", "sort key cleared")
    expect(c.command("RPUSH", "d:s", "1e400", "1"), b":2\r\n", "overflow-element list seeded")
    expect(c.command("SORT", "d:s"),
           b"-ERR One or more scores can't be converted into double\r\n",
           "an overflowing element is refused for the same reason")
    expect(c.command("DEL", "d:s"), b":1\r\n", "sort key cleared")
    expect(c.command("RPUSH", "d:s", "2", "1"), b":2\r\n", "ordinary list seeded")
    expect(c.command("SORT", "d:s"), b"*2\r\n$1\r\n1\r\n$1\r\n2\r\n",
           "NEGATIVE CONTROL: an ordinary numeric SORT still sorts")


# --------------------------------------------------------------------------- 7. timeouts

def section_timeouts(c):
    section("7. blocking timeouts: string2ld, then range, then the sign of the MILLISECONDS")

    def ready(*extra):
        c.command("DEL", "d:t")
        c.command("RPUSH", "d:t", "v")

    accepted = [
        ("0x10", "hexadecimal"),
        ("0x1p-2", "hexadecimal float"),
        ("+5", "leading plus"),
        ("+0", "plus zero"),
        ("1e-400", "a magnitude below double range but inside long double range"),
        ("5e-324", "a subnormal"),
        ("-0.0004", "a negative that truncates to zero milliseconds"),
        ("0.0005", "a positive that truncates to zero milliseconds"),
    ]
    for value, label in accepted:
        ready()
        expect(c.command("BLPOP", "d:t", value), b"*2\r\n$3\r\nd:t\r\n$1\r\nv\r\n",
               "BLPOP accepts %s" % label)

    ranged = [
        ("1e309", b"-ERR timeout is out of range\r\n", "a magnitude past the millisecond range"),
        ("inf", b"-ERR timeout is out of range\r\n", "infinity"),
        ("infinity", b"-ERR timeout is out of range\r\n", "the word infinity"),
        ("9223372036854775.808", b"-ERR timeout is out of range\r\n", "just past LLONG_MAX ms"),
        ("-inf", b"-ERR timeout is negative\r\n", "negative infinity"),
        ("-1e309", b"-ERR timeout is negative\r\n", "a negative magnitude past the range"),
        ("-0.5", b"-ERR timeout is negative\r\n", "an ordinary negative"),
        (" 5", b"-ERR timeout is not a float or out of range\r\n", "a leading space"),
        ("", b"-ERR timeout is not a float or out of range\r\n", "an empty timeout"),
        ("nan", b"-ERR timeout is not a float or out of range\r\n", "NaN"),
        ("abc", b"-ERR timeout is not a float or out of range\r\n", "a word"),
    ]
    for value, wanted, label in ranged:
        ready()
        expect(c.command("BLPOP", "d:t", value), wanted, "BLPOP answers %s correctly" % label)
        expect(c.command("LLEN", "d:t"), b":1\r\n", "  and did not pop for %s" % label)

    # Every timeout-taking shape shares the parser, including the two that put it first.
    ready()
    expect(c.command("BLMPOP", "0x10", "1", "d:t", "LEFT"),
           b"*2\r\n$3\r\nd:t\r\n*1\r\n$1\r\nv\r\n", "BLMPOP shares the timeout grammar")
    ready()
    expect(c.command("BLMOVE", "d:t", "d:td", "LEFT", "LEFT", "+5"), b"$1\r\nv\r\n",
           "BLMOVE shares the timeout grammar")
    ready()
    expect(c.command("BRPOPLPUSH", "d:t", "d:td", "0x10"), b"$1\r\nv\r\n",
           "BRPOPLPUSH shares the timeout grammar")
    c.command("DEL", "d:tz")
    c.command("ZADD", "d:tz", "1", "m")
    expect(c.command("BZPOPMIN", "d:tz", "0x1p-2"),
           b"*3\r\n$4\r\nd:tz\r\n$1\r\nm\r\n$1\r\n1\r\n", "BZPOPMIN shares the timeout grammar")
    c.command("DEL", "d:tz")
    c.command("ZADD", "d:tz", "1", "m")
    expect(c.command("BZMPOP", "+5", "1", "d:tz", "MIN"),
           b"*2\r\n$4\r\nd:tz\r\n*1\r\n*2\r\n$1\r\nm\r\n$1\r\n1\r\n",
           "BZMPOP shares the timeout grammar")
    c.command("DEL", "d:t", "d:td", "d:tz")


def section_timeout_truncation():
    """Seconds are scaled to milliseconds and rounded UP, then the SIGN is read off the result.

    A positive timeout is therefore never zero however small, while a negative one smaller than a
    millisecond rounds to -0 and becomes a zero timeout, which means no deadline at all. Neither
    can be shown on a ready key -- it pops either way -- so this needs an EMPTY key and a bounded
    wait. Rows that must come back and rows that must not are interleaved, so a detector stuck on
    one answer fails instead of passing everything.
    """
    section("8. sub-millisecond timeouts: positive rounds up, negative rounds to a zero deadline")

    def blpop_within(timeout_text, seconds):
        c = Conn(timeout=seconds)
        c.command("DEL", "d:empty")
        c.send_only("BLPOP", "d:empty", timeout_text)
        try:
            reply = c.read_raw()
        except (socket.timeout, TimeoutError):
            reply = b"<STILL BLOCKED>"
        c.close()
        return reply

    expect(blpop_within("0.002", 3.0), b"*-1\r\n",
           "NEGATIVE CONTROL: 2 ms is two milliseconds and the wait ends")
    expect(blpop_within("1e-9", 3.0), b"*-1\r\n",
           "a nanosecond rounds UP to one millisecond and the wait ends")
    expect(blpop_within("0.0005", 3.0), b"*-1\r\n",
           "half a millisecond rounds up too; truncating here would hang the client")
    expect(blpop_within("-0.0004", 1.5), b"<STILL BLOCKED>",
           "-0.4 ms rounds up to -0, so it is a zero timeout, not 'timeout is negative'")
    expect(blpop_within("0", 1.5), b"<STILL BLOCKED>",
           "NEGATIVE CONTROL: an explicit zero is the same no-deadline case")


# --------------------------------------------------------------------------- 9. RESP3

def section_resp3():
    section("9. RESP3 renders the same digits behind a different marker")
    c = Conn()
    hello = c.command("HELLO", "3")
    if not hello.startswith(b"%"):
        failures.append("HELLO 3")
        print("  FAIL HELLO 3 -> %r" % hello, flush=True)
        c.close()
        return
    global checks
    checks += 1
    print("  ok   RESP3 selected", flush=True)
    c.command("DEL", "d:p3")
    expect(c.command("ZADD", "d:p3", "1e126", "m"), b":1\r\n", "RESP3 member stored")
    expect(c.command("ZSCORE", "d:p3", "m"), b",9.999999999999999e+125\r\n",
           "the RESP3 double carries the Grisu2 digits")
    expect(c.command("ZINCRBY", "d:p3", "0x10", "hexmember"), b",16\r\n",
           "a RESP3 double from a hexadecimal increment")
    expect(c.command("ZADD", "d:p3", "INCR", "1e-7", "tiny"), b",1e-7\r\n",
           "the RESP3 double uses the same scientific cutover")
    c.command("DEL", "d:p3")
    c.close()


def main():
    c = Conn()
    expect(c.command("FLUSHDB"), b"+OK\r\n", "clean slate")
    section_format(c)
    section_value_grammar(c)
    section_range_grammar(c)
    section_long_double(c)
    section_geo(c)
    section_sort(c)
    section_timeouts(c)
    c.command("FLUSHDB")
    c.close()
    section_timeout_truncation()
    section_resp3()

    print("\ndoubles: %d checks, %d failures -> %s" %
          (checks, len(failures), "FAIL" if failures else "PASS"))
    for name in failures:
        print("  %s" % name)
    if checks < 145:
        print("VACUOUS: only %d checks fired" % checks)
        return 1
    return 1 if failures else 0


sys.exit(main())
