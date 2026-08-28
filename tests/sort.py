#!/usr/bin/env python3
"""SORT BY/GET battery.

Usage: tests/sort.py HOST PORT [SEED]

Two configurations must both be exercised, and the script detects which one it is talking to:

  * ONE EXECUTOR  -- the BY/GET dereference is admitted, because that executor owns every shard and
    a derived key can never belong to another thread.  The battery then checks the whole reference
    surface: substitution, hash-field patterns, NULL weights, the conversion error, the collation
    split, dontsort per type, the set/STORE determinism rule, GET projection and STORE.
  * MORE THAN ONE -- every '*'-bearing BY/GET must be refused with the single-owner error, and every
    form that dereferences nothing must still work.

VACUOUS-VALIDATION GUARD.  Replies alone cannot tell a dereference that ran from patterns that
resolved to nothing, nor a refusal from an unrelated failure, nor which of the two execution arms
(localfast / cross-shard engine) served the command.  Every phase below therefore asserts on INFO's
sort_deref_lookups, sort_deref_refusals, sort_scatter_general and sort_deref_escapes, and each is
another phase's negative control: the refusal phase must report zero lookups, the deref phase must
report zero refusals, and sort_deref_escapes must be zero everywhere.
"""

import random
import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 17
failures = []
checks = 0


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
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
            n = int(body)
            return dict((self.read(), self.read()) for _ in range(n))
        if kind == b"_":
            return None
        if kind == b"#":
            return body == b"t"
        if kind == b",":
            return float(body)
        raise AssertionError("unknown reply type %r" % kind)

    def close(self):
        self.sock.close()


def check(label, got, want):
    global checks
    checks += 1
    if isinstance(got, RuntimeError):
        got = "ERR:" + str(got)
    if got != want:
        failures.append("%s: got %r want %r" % (label, got, want))
        print("  FAIL %-52s got=%r want=%r" % (label, got, want))


def check_err(label, got, prefix):
    global checks
    checks += 1
    text = str(got) if isinstance(got, RuntimeError) else repr(got)
    if not (isinstance(got, RuntimeError) and text.startswith(prefix)):
        failures.append("%s: got %r want prefix %r" % (label, text, prefix))
        print("  FAIL %-52s got=%r want prefix=%r" % (label, text[:60], prefix))


def stats(c):
    text = c.cmd("INFO", "stats")
    out = {}
    for line in text.split("\r\n"):
        if ":" in line and line.startswith("sort_"):
            key, value = line.split(":", 1)
            out[key] = int(value)
    return out


def executors(c):
    """Number of ex threads, read from the server's own placement report."""
    for line in str(c.cmd("INFO", "LB")).split("\r\n"):
        if line.startswith("lb_ex_threads:"):
            return int(line.split(":", 1)[1])
    raise AssertionError("INFO LB did not report lb_ex_threads")


def fixture(c):
    c.cmd("FLUSHALL")
    c.cmd("RPUSH", "s:L", "3", "1", "2")
    c.cmd("SADD", "s:S", "3", "1", "2")
    c.cmd("ZADD", "s:Z", "30", "a", "10", "b", "20", "c")
    c.cmd("MSET", "s:w_1", "10", "s:w_2", "5", "s:w_3", "1",
          "s:d_1", "one", "s:d_2", "two", "s:d_3", "three")
    c.cmd("HSET", "s:h_1", "f", "100", "g", "A")
    c.cmd("HSET", "s:h_2", "f", "50", "g", "B")
    c.cmd("HSET", "s:h_3", "f", "25", "g", "C")
    c.cmd("MSET", "s:nn_1", "abc", "s:nn_2", "2", "s:nn_3", "3")
    c.cmd("SET", "s:p_2", "5")
    c.cmd("MSET", "s:a1b", "Y", "s:w3x", "1", "s:w1x", "2", "s:w2x", "3")
    c.cmd("MSET", "s:w\\1x", "100", "s:w\\2x", "50", "s:w\\3x", "25")
    c.cmd("MSET", "s:x->f1", "5", "s:x->f2", "1", "s:x->f3", "3")
    c.cmd("SET", "s:h_1->", "V1")


DENY_BY = "BY option of SORT denied"
DENY_GET = "GET option of SORT denied"


def phase_no_deref(c):
    """Forms that read no derived key at all. These must behave identically in EVERY config."""
    print("-- forms that dereference nothing --")
    before = stats(c)
    check("BY globless suppresses ordering", c.cmd("SORT", "s:L", "BY", "nosort"),
          ["3", "1", "2"])
    check("BY globless, other spelling", c.cmd("SORT", "s:L", "BY", "constant"),
          ["3", "1", "2"])
    # '?' and '[' are glob metacharacters but NOT substitution points: only '*' is.
    check("BY '?' is not a substitution", c.cmd("SORT", "s:L", "BY", "?_w"), ["3", "1", "2"])
    check("BY '[' is not a substitution", c.cmd("SORT", "s:L", "BY", "[ab]_w"), ["3", "1", "2"])
    check("BY globless + DESC reverses a list",
          c.cmd("SORT", "s:L", "BY", "nosort", "DESC"), ["2", "1", "3"])
    check("BY globless + DESC reverses a zset",
          c.cmd("SORT", "s:Z", "BY", "nosort", "DESC"), ["a", "c", "b"])
    check("BY globless + LIMIT", c.cmd("SORT", "s:L", "BY", "nosort", "LIMIT", "1", "1"), ["1"])
    check("BY globless + LIMIT past the end",
          c.cmd("SORT", "s:L", "BY", "nosort", "LIMIT", "5", "5"), [])
    check("BY globless + negative offset clamps",
          c.cmd("SORT", "s:L", "BY", "nosort", "LIMIT", "-1", "2"), ["3", "1"])
    check("GET # is the element", c.cmd("SORT", "s:L", "GET", "#"), ["1", "2", "3"])
    check("GET # twice", c.cmd("SORT", "s:L", "GET", "#", "GET", "#"),
          ["1", "1", "2", "2", "3", "3"])
    check("BY globless + GET #", c.cmd("SORT", "s:L", "BY", "nosort", "GET", "#"),
          ["3", "1", "2"])
    # A GET pattern with no '*' never looks a key up; the reference answers a null per element.
    check("GET globless is a constant null", c.cmd("SORT", "s:L", "GET", "literal"),
          [None, None, None])
    check("GET '##' is not the element", c.cmd("SORT", "s:L", "GET", "##"), [None, None, None])
    check("BY globless + STORE", c.cmd("SORT", "s:L", "BY", "nosort", "STORE", "s:dl"), 3)
    check("BY globless + STORE contents", c.cmd("LRANGE", "s:dl", "0", "-1"), ["3", "1", "2"])
    check("GET null stores an empty element",
          c.cmd("SORT", "s:L", "GET", "literal", "GET", "#", "STORE", "s:dm"), 6)
    check("GET null STORE contents", c.cmd("LRANGE", "s:dm", "0", "-1"),
          ["", "1", "", "2", "", "3"])
    check("missing source with BY globless", c.cmd("SORT", "s:none", "BY", "nosort"), [])
    check_err("wrong type source", c.cmd("SORT", "s:h_1", "BY", "nosort"), "WRONGTYPE")
    check_err("syntax error precedes a later BY",
              c.cmd("SORT", "s:L", "BADTOKEN", "BY", "s:w_*"), "ERR syntax error")
    check_err("BY needs an argument", c.cmd("SORT", "s:L", "BY"), "ERR syntax error")
    check_err("GET needs an argument", c.cmd("SORT", "s:L", "GET"), "ERR syntax error")
    after = stats(c)
    # MECHANISM CONTROL: not one of the forms above may read a derived key.
    check("no-deref phase performed no lookups",
          after["sort_deref_lookups"] - before["sort_deref_lookups"], 0)


def phase_refused(c):
    print("-- multi-executor: every '*'-bearing BY/GET is refused --")
    before = stats(c)
    for label, args in [
        ("BY string pattern", ("SORT", "s:L", "BY", "s:w_*")),
        ("BY hash-field pattern", ("SORT", "s:L", "BY", "s:h_*->f")),
        ("BY on SORT_RO", ("SORT_RO", "s:L", "BY", "s:w_*")),
        ("BY refused before a later syntax error", ("SORT", "s:L", "BY", "s:w_*", "BADTOKEN")),
        ("BY refused with STORE", ("SORT", "s:L", "BY", "s:w_*", "STORE", "s:d")),
        ("BY refused on a missing source", ("SORT", "s:none", "BY", "s:w_*")),
    ]:
        check_err(label, c.cmd(*args), "ERR " + DENY_BY)
    for label, args in [
        ("GET string pattern", ("SORT", "s:L", "GET", "s:d_*")),
        ("GET hash-field pattern", ("SORT", "s:L", "GET", "s:h_*->g")),
        ("GET on SORT_RO", ("SORT_RO", "s:L", "GET", "s:d_*")),
        ("GET refused after an admitted BY", ("SORT", "s:L", "BY", "nosort", "GET", "s:d_*")),
    ]:
        check_err(label, c.cmd(*args), "ERR " + DENY_GET)
    after = stats(c)
    check("refusals counted", after["sort_deref_refusals"] - before["sort_deref_refusals"], 10)
    # MECHANISM CONTROL: a refusal must happen BEFORE any key is read.
    check("refusal phase performed no lookups",
          after["sort_deref_lookups"] - before["sort_deref_lookups"], 0)


def phase_deref(c):
    print("-- single executor: the full BY/GET surface --")
    before = stats(c)

    # substitution is the FIRST '*' only, and a backslash escapes nothing.
    check("first '*' only", c.cmd("SORT", "s:L", "BY", "s:a*b*c"), ["1", "2", "3"])
    check("substituted key found", c.cmd("SORT", "s:L", "BY", "s:a*b", "ALPHA"), ["3", "2", "1"])
    check("backslash is an ordinary byte", c.cmd("SORT", "s:L", "BY", "s:w\\*x"), ["3", "2", "1"])
    check("plain substitution", c.cmd("SORT", "s:L", "BY", "s:w*x"), ["3", "1", "2"])

    # "->" is a field separator only AFTER the '*' and only with a non-empty tail.
    check("hash field weight", c.cmd("SORT", "s:L", "BY", "s:h_*->f"), ["3", "2", "1"])
    check_err("empty field is key bytes", c.cmd("SORT", "s:L", "BY", "s:h_*->"),
              "ERR One or more scores can't be converted into double")
    check("'->' before the '*' is key bytes", c.cmd("SORT", "s:L", "BY", "s:x->f*"),
          ["2", "3", "1"])

    # NULL weights: missing key, wrong-type key, or a hash without the field.
    check("all weights null, numeric", c.cmd("SORT", "s:L", "BY", "s:none_*"), ["1", "2", "3"])
    check("all weights null, alpha", c.cmd("SORT", "s:L", "BY", "s:none_*", "ALPHA"),
          ["3", "1", "2"])
    check("one weight present, numeric", c.cmd("SORT", "s:L", "BY", "s:p_*"), ["1", "3", "2"])
    check("null sorts before present, alpha",
          c.cmd("SORT", "s:L", "BY", "s:p_*", "ALPHA"), ["3", "1", "2"])
    check("desc keeps ties in input order",
          c.cmd("SORT", "s:L", "BY", "s:p_*", "ALPHA", "DESC"), ["2", "3", "1"])
    check("hash without a field is null", c.cmd("SORT", "s:L", "BY", "s:h_*"), ["1", "2", "3"])
    check("collection weight is null", c.cmd("SORT", "s:L", "BY", "s:L*"), ["1", "2", "3"])

    # A PRESENT non-numeric weight is the error; an ABSENT one is zero.
    check_err("non-numeric weight errors", c.cmd("SORT", "s:L", "BY", "s:nn_*"),
              "ERR One or more scores can't be converted into double")
    check_err("...even under LIMIT", c.cmd("SORT", "s:L", "BY", "s:nn_*", "LIMIT", "0", "1"),
              "ERR One or more scores can't be converted into double")
    check("...but ALPHA accepts it", c.cmd("SORT", "s:L", "BY", "s:nn_*", "ALPHA"),
          ["2", "3", "1"])

    # GET projection.
    check("GET string pattern", c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "s:d_*"),
          ["three", "two", "one"])
    check("GET # with BY", c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "#"), ["3", "2", "1"])
    check("interleaved GETs",
          c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "#", "GET", "s:d_*", "GET", "s:h_*->g"),
          ["3", "three", "C", "2", "two", "B", "1", "one", "A"])
    check("GET on missing keys", c.cmd("SORT", "s:L", "GET", "s:nope_*"), [None, None, None])
    check("GET on a hash without a field", c.cmd("SORT", "s:L", "GET", "s:h_*"),
          [None, None, None])
    check("GET hash field, alpha", c.cmd("SORT", "s:L", "GET", "s:h_*->g", "ALPHA"),
          ["A", "B", "C"])
    check("dontsort keeps list order under GET",
          c.cmd("SORT", "s:L", "BY", "nosort", "GET", "#", "GET", "s:d_*"),
          ["3", "three", "1", "one", "2", "two"])

    # STORE of a projection, and the empty-result deletion.
    check("STORE a projection",
          c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "s:d_*", "STORE", "s:dst"), 3)
    check("stored projection", c.cmd("LRANGE", "s:dst", "0", "-1"), ["three", "two", "one"])
    check("stored type", c.cmd("TYPE", "s:dst"), "list")
    check("nulls store as empty elements",
          c.cmd("SORT", "s:L", "GET", "s:nope_*", "STORE", "s:dst2"), 3)
    check("stored nulls", c.cmd("LRANGE", "s:dst2", "0", "-1"), ["", "", ""])
    c.cmd("SET", "s:keep", "v")
    check("empty result returns 0", c.cmd("SORT", "s:none", "BY", "s:w_*", "STORE", "s:keep"), 0)
    check("empty result deletes the destination", c.cmd("EXISTS", "s:keep"), 0)
    check("missing source with BY/GET", c.cmd("SORT", "s:none", "BY", "s:w_*", "GET", "s:d_*"),
          [])
    check("SORT_RO dereferences", c.cmd("SORT_RO", "s:L", "BY", "s:w_*", "GET", "s:d_*"),
          ["three", "two", "one"])
    check_err("SORT_RO still refuses STORE",
              c.cmd("SORT_RO", "s:L", "BY", "s:w_*", "STORE", "s:x"), "ERR syntax error")
    check_err("last BY wins", c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "#", "BY", "s:nn_*"),
              "ERR One or more scores can't be converted into double")

    after = stats(c)
    # MECHANISM CONTROL: this phase must have read derived keys, and refused nothing.
    if after["sort_deref_lookups"] - before["sort_deref_lookups"] <= 0:
        failures.append("deref phase performed no lookups at all")
        print("  FAIL deref phase performed no lookups at all")
    check("deref phase refused nothing",
          after["sort_deref_refusals"] - before["sort_deref_refusals"], 0)


def phase_set_determinism(c):
    """A set has no order, so a STOREd dontsort must not be allowed to be unordered."""
    print("-- set/STORE determinism rule --")
    members = ["delta", "alpha", "charlie", "bravo", "echo"]
    c.cmd("DEL", "s:HS")
    c.cmd("SADD", "s:HS", *members)
    unordered = c.cmd("SORT", "s:HS", "BY", "nosort")
    check("dontsort on a set returns the whole set", sorted(unordered), sorted(members))
    check("dontsort + STORE forces an alphabetic order",
          c.cmd("SORT", "s:HS", "BY", "nosort", "STORE", "s:ds"), 5)
    check("stored set order", c.cmd("LRANGE", "s:ds", "0", "-1"), sorted(members))
    check("dontsort + ALPHA + STORE also forced",
          c.cmd("SORT", "s:HS", "BY", "nosort", "ALPHA", "STORE", "s:ds2"), 5)
    check("stored set order (alpha)", c.cmd("LRANGE", "s:ds2", "0", "-1"), sorted(members))
    # The rule is set-specific: a list and a zset keep their own order through STORE.
    check("list keeps its order through STORE",
          c.cmd("SORT", "s:L", "BY", "nosort", "STORE", "s:dl2"), 3)
    check("stored list order", c.cmd("LRANGE", "s:dl2", "0", "-1"), ["3", "1", "2"])
    check("zset keeps score order through STORE",
          c.cmd("SORT", "s:Z", "BY", "nosort", "STORE", "s:dz"), 3)
    check("stored zset order", c.cmd("LRANGE", "s:dz", "0", "-1"), ["b", "c", "a"])
    # DESC is honoured for the two ordered types and ignored for a set.
    check("DESC ignored for a set",
          sorted(c.cmd("SORT", "s:HS", "BY", "nosort", "DESC")), sorted(members))


def phase_scatter_arm(c, one_executor):
    """The cross-shard engine arm: a STORE whose destination lands on another shard."""
    print("-- cross-shard arm --")
    before = stats(c)
    names = ["s:sc%d" % i for i in range(12)]
    for name in names:
        if one_executor:
            got = c.cmd("SORT", "s:L", "BY", "s:w_*", "GET", "s:d_*", "STORE", name)
            check("scatter STORE %s" % name, got, 3)
            check("scatter STORE %s contents" % name, c.cmd("LRANGE", name, "0", "-1"),
                  ["three", "two", "one"])
        else:
            got = c.cmd("SORT", "s:L", "BY", "nosort", "GET", "#", "STORE", name)
            check("scatter STORE %s" % name, got, 3)
            check("scatter STORE %s contents" % name, c.cmd("LRANGE", name, "0", "-1"),
                  ["3", "1", "2"])
    after = stats(c)
    fired = after["sort_scatter_general"] - before["sort_scatter_general"]
    if fired <= 0:
        failures.append("cross-shard SORT arm never ran (sort_scatter_general did not move)")
        print("  FAIL cross-shard SORT arm never ran")
    else:
        print("  cross-shard arm ran %d times" % fired)
    global checks
    checks += 1


def phase_ryow(c, one_executor):
    """Read-your-own-writes across the dereference.

    REGRESSION PIN. The read cut and the originating connection are per-shard state that the owning
    task binds only on the shard it was posted for. A dereference reads OTHER shards, and reading
    them at "latest, no connection" hides this connection's own not-yet-committed group -- so a
    weight key written by the immediately preceding MSET read back as absent, and only on the boots
    whose hash seed placed it off the source's shard. The loop below writes the weights and sorts by
    them on the same connection many times, with weight names spread wide enough that some of them
    land on another shard in any multi-shard placement.
    """
    print("-- read-your-own-writes through BY/GET --")
    if not one_executor:
        print("  (skipped: dereference is not admitted in this configuration)")
        return
    elements = [str(i) for i in range(12)]
    c.cmd("DEL", "s:ry")
    c.cmd("RPUSH", "s:ry", *elements)
    for round_index in range(40):
        weights = {e: (round_index * 37 + int(e) * 11) % 97 for e in elements}
        pairs = []
        for e in elements:
            pairs += ["s:ryw_%s_%d" % (e, round_index), str(weights[e])]
            pairs += ["s:ryd_%s_%d" % (e, round_index), "v%s" % e]
        c.cmd("MSET", *pairs)
        want = sorted(elements, key=lambda e: (weights[e], e.encode("latin1")))
        check("ryow round %d order" % round_index,
              c.cmd("SORT", "s:ry", "BY", "s:ryw_*_%d" % round_index), want)
        check("ryow round %d projection" % round_index,
              c.cmd("SORT", "s:ry", "BY", "s:ryw_*_%d" % round_index,
                    "GET", "s:ryd_*_%d" % round_index),
              ["v%s" % e for e in want])
        c.cmd("DEL", *[p for i, p in enumerate(pairs) if i % 2 == 0])


def phase_random(c, one_executor, rng):
    """Random weight sets checked against a Python model of the reference's rules."""
    print("-- randomised model comparison --")
    if not one_executor:
        print("  (skipped: dereference is not admitted in this configuration)")
        return
    for trial in range(60):
        n = rng.randint(1, 12)
        elements = [str(rng.randint(0, 40)) for _ in range(n)]
        elements = list(dict.fromkeys(elements))          # SORT of a list, distinct for clarity
        c.cmd("DEL", "s:r")
        c.cmd("RPUSH", "s:r", *elements)
        weights = {}
        for element in elements:
            if rng.random() < 0.25:
                continue                                   # missing -> NULL weight
            weights[element] = rng.randint(-500, 500)
            c.cmd("SET", "s:rw_" + element, str(weights[element]))
        for element in elements:
            if rng.random() < 0.3:
                c.cmd("DEL", "s:rd_" + element)
            else:
                c.cmd("SET", "s:rd_" + element, "v" + element)
        desc = rng.random() < 0.5
        # Numeric ordering: a missing weight is zero, and equal weights fall back to a byte
        # comparison of the ELEMENTS -- a total order, so the model is exact.
        order = sorted(elements,
                       key=lambda e: (weights.get(e, 0), e.encode("latin1")),
                       reverse=desc)
        args = ["SORT", "s:r", "BY", "s:rw_*"]
        if desc:
            args.append("DESC")
        check("random %d order" % trial, c.cmd(*args), order)
        args = ["SORT", "s:r", "BY", "s:rw_*"] + (["DESC"] if desc else []) + \
               ["GET", "#", "GET", "s:rd_*"]
        want = []
        for element in order:
            want.append(element)
            got_key = c.cmd("EXISTS", "s:rd_" + element)
            want.append("v" + element if got_key else None)
        check("random %d projection" % trial, c.cmd(*args), want)
        for element in elements:
            c.cmd("DEL", "s:rw_" + element, "s:rd_" + element)


def main():
    rng = random.Random(SEED)
    c = Conn()
    n_ex = executors(c)
    one_executor = n_ex == 1
    print("sort battery: %s:%d, %d executor(s) -> dereference %s"
          % (HOST, PORT, n_ex, "ADMITTED" if one_executor else "REFUSED"))
    fixture(c)
    phase_no_deref(c)
    if one_executor:
        phase_deref(c)
    else:
        phase_refused(c)
    phase_set_determinism(c)
    phase_scatter_arm(c, one_executor)
    phase_ryow(c, one_executor)
    phase_random(c, one_executor, rng)

    # THE INVARIANT THAT MUST READ ZERO IN EVERY CONFIGURATION: no dereference ever reached a shard
    # this executor does not own.
    final = stats(c)
    check("no foreign-shard dereference", final.get("sort_deref_escapes", -1), 0)
    print("  counters: %s" % final)

    c.cmd("FLUSHALL")
    c.close()
    print("\nsort: %d checks, %d failures -> %s"
          % (checks, len(failures), "PASS" if not failures else "FAIL"))
    for line in failures[:15]:
        print("  " + line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
