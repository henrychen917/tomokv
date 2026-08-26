#!/usr/bin/env python3
"""Scripting-surface gate: SCRIPT family, EVAL_RO/EVALSHA_RO, FUNCTION library, FCALL/FCALL_RO.

Usage: python3 tests/scriptsurf.py <host> <port> [<oracle_host> <oracle_port>]

Every check proves its mechanism FIRED, not merely that nothing broke:
  * the read-only gate is asserted by counter delta AND by the write not landing,
  * the process-wide script store is proven by loading on one connection and running the sha on
    another, on a key owned by a different executor thread,
  * the per-thread library materialization is proven by the function_thread_rebuilds counter
    moving when the generation moves and NOT moving when it does not,
  * every error path has a negative control that must succeed.
When the two optional oracle arguments are given, every error shape is byte-compared against
vanilla Redis instead of being matched by substring.
"""
import os
import socket
import sys
import time


HOST, PORT = sys.argv[1], int(sys.argv[2])
ORACLE = (sys.argv[3], int(sys.argv[4])) if len(sys.argv) > 4 else None
PREFIX = "ss:%d" % os.getpid()
FAIL = 0
CHECKS = 0


def note(name, ok, extra=""):
    global FAIL, CHECKS
    CHECKS += 1
    print(("  ok   " if ok else "  FAIL ") + name + (" " + str(extra) if extra else ""),
          flush=True)
    if not ok:
        FAIL += 1


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, int):
            arg = str(arg)
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Conn:
    """Raw RESP client. `raw` returns the exact reply bytes; `cmd` returns a decoded value."""

    def __init__(self, host=HOST, port=PORT, resp3=False):
        self.sock = socket.create_connection((host, port), timeout=20)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")
        if resp3:
            self.raw("HELLO", "3")

    def close(self):
        self.file.close()
        self.sock.close()

    def _read_raw(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind in (b"+", b"-", b":", b",", b"#", b"(", b"_"):
            return line
        if kind in (b"$", b"="):
            size = int(line[1:-2])
            return line if size == -1 else line + self.file.read(size + 2)
        if kind in (b"*", b"~", b">"):
            count = int(line[1:-2])
            return line if count == -1 else line + b"".join(
                self._read_raw() for _ in range(count))
        if kind == b"%":
            return line + b"".join(self._read_raw() for _ in range(int(line[1:-2]) * 2))
        raise ValueError("bad RESP marker %r" % kind)

    def raw(self, *args):
        self.sock.sendall(frame(*args))
        return self._read_raw()

    def cmd(self, *args):
        return decode(self.raw(*args))

    def read(self):
        """Read one already-pending frame (a pub/sub push) without sending anything."""
        return decode(self._read_raw())


def decode(reply):
    def one(pos):
        marker = reply[pos:pos + 1]
        end = reply.index(b"\r\n", pos)
        line = reply[pos + 1:end]
        nxt = end + 2
        if marker in (b"+", b":"):
            return (int(line) if marker == b":" else line), nxt
        if marker == b"-":
            return Err(line.decode()), nxt
        if marker == b"_":
            return None, nxt
        if marker in (b"$", b"="):
            size = int(line)
            if size == -1:
                return None, nxt
            return reply[nxt:nxt + size], nxt + size + 2
        if marker in (b"*", b"~", b">"):
            count = int(line)
            if count == -1:
                return None, nxt
            out = []
            for _ in range(count):
                value, nxt = one(nxt)
                out.append(value)
            return out, nxt
        if marker == b"%":
            out = []
            for _ in range(int(line) * 2):
                value, nxt = one(nxt)
                out.append(value)
            return out, nxt
        raise ValueError("bad RESP marker %r" % marker)
    return one(0)[0]


class Err(str):
    pass


def info_counters(conn):
    body = conn.cmd("INFO", "stats")
    out = {}
    for line in body.decode(errors="replace").split("\r\n"):
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            try:
                out[key] = int(value)
            except ValueError:
                pass
    return out


ORACLE_CONN = None


def shape(conn, name, *args):
    """Assert the reply BYTES. Against the oracle when one was supplied, else record for print."""
    got = conn.raw(*args)
    if ORACLE_CONN is None:
        return got
    want = ORACLE_CONN.raw(*args)
    note("oracle shape: " + name, got == want, "\n     tomo=%r\n     oracle=%r" % (got, want))
    return got


# --------------------------------------------------------------------------------------------
c = Conn()
c2 = Conn()
if ORACLE:
    ORACLE_CONN = Conn(ORACLE[0], ORACLE[1])

LIB_MAIN = ("#!lua name=%slib\n" % "ss"
            + "redis.register_function('ssget', function(keys, args)\n"
            + "  return {redis.call('GET', keys[1]), #keys, #args}\n"
            + "end)\n"
            + "redis.register_function{function_name='ssset',\n"
            + "  callback=function(keys, args) return redis.call('SET', keys[1], args[1]) end,\n"
            + "  description='writes a key'}\n"
            + "redis.register_function{function_name='ssro',\n"
            + "  callback=function(keys, args) return redis.call('GET', keys[1]) end,\n"
            + "  flags={'no-writes'}, description='read only'}\n"
            + "redis.register_function{function_name='sswronly',\n"
            + "  callback=function(keys, args) return redis.call('SET', keys[1], 'x') end,\n"
            + "  flags={'no-writes'}}\n")
LIB_SECOND = ("#!lua name=sslib2\n"
              + "redis.register_function('ssecho', function(keys, args) return args[1] end)\n")

keys = ["%s:%d" % (PREFIX, i) for i in range(40)]
try:
    for target in ([c] + ([ORACLE_CONN] if ORACLE_CONN else [])):
        target.cmd("SCRIPT", "FLUSH")
        target.cmd("FUNCTION", "FLUSH")
    c.cmd("DEL", *keys)

    # ---- 1. process-wide script store ------------------------------------------------------
    print("[1] SCRIPT LOAD / EXISTS across connections and executor threads")
    source = "return {KEYS[1], ARGV[1], redis.call('GET', KEYS[1])}"
    sha = c.cmd("SCRIPT", "LOAD", source)
    note("SCRIPT LOAD returns a 40-char sha", isinstance(sha, bytes) and len(sha) == 40, sha)
    note("SCRIPT LOAD is idempotent", c.cmd("SCRIPT", "LOAD", source) == sha)
    note("SCRIPT EXISTS sees it on ANOTHER connection",
         c2.cmd("SCRIPT", "EXISTS", sha, "0" * 40) == [1, 0])

    # Run the same sha against keys owned by many different shards. A per-connection or
    # per-thread cache would NOSCRIPT on the first key whose owner had never seen the sha.
    owners = 0
    for key in keys[:32]:
        c2.cmd("SET", key, b"v-" + key.encode())
        reply = c2.cmd("EVALSHA", sha, 1, key)
        if isinstance(reply, Err):
            note("EVALSHA on shard-spread key %s" % key, False, reply)
            break
        owners += 1
    note("EVALSHA from a second connection over 32 shard-spread keys", owners == 32, owners)

    counters = info_counters(c)
    note("script chunk cache counters fired (vacuous-check)",
         counters["script_chunk_cache_hits"] > 0 and counters["script_chunk_cache_misses"] > 0,
         "hits=%d misses=%d" % (counters["script_chunk_cache_hits"],
                                counters["script_chunk_cache_misses"]))
    note("number_of_cached_scripts counts the store", counters["number_of_cached_scripts"] >= 1,
         counters["number_of_cached_scripts"])

    # ---- 2. SCRIPT FLUSH generation --------------------------------------------------------
    print("[2] SCRIPT FLUSH generation")
    before = info_counters(c)["script_flush_generation"]
    note("SCRIPT FLUSH ASYNC ok", c.cmd("SCRIPT", "FLUSH", "ASYNC") == b"OK")
    after = info_counters(c)
    note("flush generation advanced", after["script_flush_generation"] == before + 1,
         "%d -> %d" % (before, after["script_flush_generation"]))
    note("store emptied", after["number_of_cached_scripts"] == 0)
    note("EXISTS now 0 on both connections",
         c.cmd("SCRIPT", "EXISTS", sha) == [0] and c2.cmd("SCRIPT", "EXISTS", sha) == [0])
    note("EVALSHA after flush is NOSCRIPT",
         str(c2.cmd("EVALSHA", sha, 0)).startswith("NOSCRIPT "))
    # The interpreter state itself must rebuild, and EVAL must still work afterwards.
    rebuilds_before = after["script_interpreter_builds"]
    note("EVAL still works after flush", c2.cmd("EVAL", "return 7", 0) == 7)
    note("interpreter rebuilt after flush",
         info_counters(c)["script_interpreter_builds"] > rebuilds_before)

    # ---- 3. SCRIPT subcommand surface ------------------------------------------------------
    print("[3] SCRIPT KILL / DEBUG / HELP / errors")
    note("SCRIPT KILL is NOTBUSY",
         c.raw("SCRIPT", "KILL") == b"-NOTBUSY No scripts in execution right now.\r\n")
    note("SCRIPT DEBUG NO accepted", c.raw("SCRIPT", "DEBUG", "no") == b"+OK\r\n")
    note("SCRIPT DEBUG YES refused (documented divergence)",
         c.raw("SCRIPT", "DEBUG", "yes").startswith(b"-ERR SCRIPT DEBUG YES|SYNC is not supported"))
    note("SCRIPT DEBUG SYNC refused",
         c.raw("SCRIPT", "DEBUG", "sync").startswith(b"-ERR SCRIPT DEBUG YES|SYNC is not supported"))
    note("SCRIPT HELP is a status array",
         c.raw("SCRIPT", "HELP")[:1] == b"*" and b"SCRIPT <subcommand>" in c.raw("SCRIPT", "HELP"))
    shape(c, "SCRIPT DEBUG bogus", "SCRIPT", "DEBUG", "bogus")
    shape(c, "SCRIPT DEBUG arity", "SCRIPT", "DEBUG")
    shape(c, "SCRIPT unknown subcommand", "SCRIPT", "NOPE")
    shape(c, "SCRIPT LOAD arity", "SCRIPT", "LOAD")
    shape(c, "SCRIPT LOAD extra args", "SCRIPT", "LOAD", "return 1", "x")
    shape(c, "SCRIPT LOAD syntax error", "SCRIPT", "LOAD", "return (")
    shape(c, "SCRIPT EXISTS arity", "SCRIPT", "EXISTS")
    shape(c, "SCRIPT FLUSH bad mode", "SCRIPT", "FLUSH", "BOGUS")
    shape(c, "SCRIPT KILL extra args", "SCRIPT", "KILL", "x")
    shape(c, "EVAL compile error", "EVAL", "return (", "0")
    shape(c, "EVAL nonexistent global", "EVAL", "return sszzz", "0")
    shape(c, "EVAL error(string)", "EVAL", "error('boom')", "0")
    shape(c, "EVAL error(table)", "EVAL", "error({err='My Error'})", "0")
    shape(c, "EVAL numkeys negative", "EVAL", "return 1", "-1")
    shape(c, "EVAL numkeys > argc", "EVAL", "return 1", "5", "a")
    shape(c, "EVAL numkeys not a number", "EVAL", "return 1", "x")
    shape(c, "EVALSHA unknown sha", "EVALSHA", "0" * 40, "0")

    # ---- 4. the read-only matrix -----------------------------------------------------------
    print("[4] EVAL_RO / EVALSHA_RO read-only gate")
    rw = keys[0]
    c.cmd("DEL", rw)
    c.cmd("SET", rw, "seed")
    writes = [
        ("SET", "return redis.call('SET', KEYS[1], 'w')"),
        ("APPEND", "return redis.call('APPEND', KEYS[1], 'w')"),
        ("SETRANGE", "return redis.call('SETRANGE', KEYS[1], 0, 'w')"),
        ("GETSET", "return redis.call('GETSET', KEYS[1], 'w')"),
        ("SETNX", "return redis.call('SETNX', KEYS[1], 'w')"),
        ("SETBIT", "return redis.call('SETBIT', KEYS[1], 0, 1)"),
        ("INCR", "return redis.call('INCR', KEYS[1])"),
        ("INCRBYFLOAT", "return redis.call('INCRBYFLOAT', KEYS[1], 1.5)"),
        ("DECRBY", "return redis.call('DECRBY', KEYS[1], 1)"),
        ("DEL", "return redis.call('DEL', KEYS[1])"),
        ("UNLINK", "return redis.call('UNLINK', KEYS[1])"),
        ("PERSIST", "return redis.call('PERSIST', KEYS[1])"),
        ("LPUSH", "return redis.call('LPUSH', KEYS[1], 'w')"),
        ("RPUSH", "return redis.call('RPUSH', KEYS[1], 'w')"),
        ("LPOP", "return redis.call('LPOP', KEYS[1])"),
        ("LSET", "return redis.call('LSET', KEYS[1], 0, 'w')"),
        ("LTRIM", "return redis.call('LTRIM', KEYS[1], 0, 0)"),
        ("LREM", "return redis.call('LREM', KEYS[1], 0, 'w')"),
        ("HSET", "return redis.call('HSET', KEYS[1], 'f', 'w')"),
        ("HDEL", "return redis.call('HDEL', KEYS[1], 'f')"),
        ("HINCRBY", "return redis.call('HINCRBY', KEYS[1], 'f', 1)"),
        ("SADD", "return redis.call('SADD', KEYS[1], 'w')"),
        ("SREM", "return redis.call('SREM', KEYS[1], 'w')"),
        ("ZADD", "return redis.call('ZADD', KEYS[1], 1, 'w')"),
        ("ZINCRBY", "return redis.call('ZINCRBY', KEYS[1], 1, 'w')"),
        ("ZREM", "return redis.call('ZREM', KEYS[1], 'w')"),
        ("ZPOPMIN", "return redis.call('ZPOPMIN', KEYS[1])"),
        ("ZREMRANGEBYRANK", "return redis.call('ZREMRANGEBYRANK', KEYS[1], 0, 0)"),
        ("PFADD", "return redis.call('PFADD', KEYS[1], 'w')"),
    ]
    ro_before = info_counters(c)["script_readonly_rejections"]
    refused = []
    for name, body in writes:
        reply = c.raw("EVAL_RO", body, "1", rw)
        expected = b"-ERR Write commands are not allowed from read-only scripts."
        if not reply.startswith(expected):
            refused.append((name, reply))
    note("EVAL_RO refuses every write form (%d)" % len(writes), not refused, refused[:3])
    note("value untouched by the refused writes", c.cmd("GET", rw) == b"seed")
    ro_after = info_counters(c)["script_readonly_rejections"]
    note("read-only rejection counter fired",
         ro_after - ro_before >= len(writes), "%d -> %d" % (ro_before, ro_after))

    # NEGATIVE CONTROL: the same gate must not refuse reads.
    c.cmd("DEL", keys[1]); c.cmd("RPUSH", keys[1], "a", "b")
    c.cmd("DEL", keys[2]); c.cmd("HSET", keys[2], "f", "v")
    c.cmd("DEL", keys[3]); c.cmd("ZADD", keys[3], 1, "m")
    c.cmd("DEL", keys[4]); c.cmd("SADD", keys[4], "m")
    reads = [
        ("GET", "return redis.call('GET', KEYS[1])", rw),
        ("STRLEN", "return redis.call('STRLEN', KEYS[1])", rw),
        ("TYPE", "return redis.call('TYPE', KEYS[1])", rw),
        ("EXISTS", "return redis.call('EXISTS', KEYS[1])", rw),
        ("TOUCH", "return redis.call('TOUCH', KEYS[1])", rw),
        ("GETRANGE", "return redis.call('GETRANGE', KEYS[1], 0, -1)", rw),
        ("BITCOUNT", "return redis.call('BITCOUNT', KEYS[1])", rw),
        ("LRANGE", "return redis.call('LRANGE', KEYS[1], 0, -1)", keys[1]),
        ("LLEN", "return redis.call('LLEN', KEYS[1])", keys[1]),
        ("HGETALL", "return redis.call('HGETALL', KEYS[1])", keys[2]),
        ("ZSCORE", "return redis.call('ZSCORE', KEYS[1], 'm')", keys[3]),
        ("ZRANGE", "return redis.call('ZRANGE', KEYS[1], 0, -1)", keys[3]),
        ("SMEMBERS", "return redis.call('SMEMBERS', KEYS[1])", keys[4]),
        ("SCARD", "return redis.call('SCARD', KEYS[1])", keys[4]),
    ]
    read_failures = [(name, c.cmd("EVAL_RO", body, "1", key)) for name, body, key in reads
                     if isinstance(c.cmd("EVAL_RO", body, "1", key), Err)]
    note("EVAL_RO allows every read form (negative control)", not read_failures, read_failures[:3])

    ro_sha = c.cmd("SCRIPT", "LOAD", "return redis.call('SET', KEYS[1], 'w')")
    note("EVALSHA_RO enforces the same gate",
         c.raw("EVALSHA_RO", ro_sha, "1", rw).startswith(
             b"-ERR Write commands are not allowed from read-only scripts."))
    note("EVALSHA (not _RO) of the same sha still writes",
         c.cmd("EVALSHA", ro_sha, "1", rw) == b"OK" and c.cmd("GET", rw) == b"w")
    note("EVALSHA_RO unknown sha is NOSCRIPT",
         str(c.cmd("EVALSHA_RO", "0" * 40, 0)).startswith("NOSCRIPT "))
    note("redis.pcall surfaces the gate as a table error",
         c.cmd("EVAL_RO", "local r = redis.pcall('SET', KEYS[1], 'x') return r.err", "1", rw)
         == b"ERR Write commands are not allowed from read-only scripts.")
    shape(c, "EVAL_RO write rejection", "EVAL_RO",
          "return redis.call('SET', KEYS[1], 'v')", "1", "ss:shape:key")

    # ---- 5. FUNCTION lifecycle -------------------------------------------------------------
    print("[5] FUNCTION lifecycle")
    gen_before = info_counters(c)["function_generation"]
    note("FUNCTION LOAD returns the library name", c.cmd("FUNCTION", "LOAD", LIB_MAIN) == b"sslib")
    note("duplicate FUNCTION LOAD is refused",
         c.raw("FUNCTION", "LOAD", LIB_MAIN) == b"-ERR Library 'sslib' already exists\r\n")
    note("FUNCTION LOAD REPLACE succeeds",
         c.cmd("FUNCTION", "LOAD", "REPLACE", LIB_MAIN) == b"sslib")
    note("FUNCTION LOAD of a second library", c.cmd("FUNCTION", "LOAD", LIB_SECOND) == b"sslib2")
    if ORACLE_CONN:
        # Mirror the libraries so the FCALL / cross-library-collision shape probes below compare
        # like with like instead of comparing against an empty oracle registry.
        ORACLE_CONN.cmd("FUNCTION", "LOAD", "REPLACE", LIB_MAIN)
        ORACLE_CONN.cmd("FUNCTION", "LOAD", "REPLACE", LIB_SECOND)
    gen_after = info_counters(c)
    note("function generation advanced per mutation",
         gen_after["function_generation"] > gen_before,
         "%d -> %d" % (gen_before, gen_after["function_generation"]))
    note("library/function counts published",
         gen_after["number_of_libraries"] == 2 and gen_after["number_of_functions"] == 5,
         "libs=%d fns=%d" % (gen_after["number_of_libraries"],
                             gen_after["number_of_functions"]))

    listing = c.cmd("FUNCTION", "LIST")
    note("FUNCTION LIST reports both libraries", isinstance(listing, list) and len(listing) == 2)
    entry = dict(zip(listing[0][0::2], listing[0][1::2]))
    note("library entry carries name/engine/functions",
         entry.get(b"engine") == b"LUA" and b"library_name" in entry and b"functions" in entry)
    note("FUNCTION LIST omits code unless asked", b"library_code" not in entry)
    with_code = c.cmd("FUNCTION", "LIST", "LIBRARYNAME", "sslib", "WITHCODE")
    coded = dict(zip(with_code[0][0::2], with_code[0][1::2]))
    note("FUNCTION LIST WITHCODE echoes the source byte-exactly",
         coded.get(b"library_code") == LIB_MAIN.encode())
    note("FUNCTION LIST LIBRARYNAME filters",
         len(with_code) == 1 and c.cmd("FUNCTION", "LIST", "LIBRARYNAME", "nope") == [])
    fns = {f[1]: dict(zip(f[0::2], f[1::2])) for f in coded[b"functions"]}
    note("descriptions round-trip",
         fns[b"ssset"][b"description"] == b"writes a key" and fns[b"ssget"][b"description"] is None)
    note("flags round-trip",
         fns[b"ssro"][b"flags"] == [b"no-writes"] and fns[b"ssget"][b"flags"] == [])
    stats = c.cmd("FUNCTION", "STATS")
    stats_map = dict(zip(stats[0::2], stats[1::2]))
    engines = dict(zip(stats_map[b"engines"][1][0::2], stats_map[b"engines"][1][1::2]))
    note("FUNCTION STATS shape",
         stats_map[b"running_script"] is None and stats_map[b"engines"][0] == b"LUA" and
         engines[b"libraries_count"] == 2 and engines[b"functions_count"] == 5, stats)

    # ---- 6. FCALL ---------------------------------------------------------------------------
    print("[6] FCALL / FCALL_RO")
    fk = keys[10]
    c.cmd("SET", fk, "fv")
    note("FCALL passes keys and args positionally",
         c.cmd("FCALL", "ssget", "1", fk, "a", "b") == [b"fv", 1, 2])
    note("FCALL_RO runs a no-writes function", c.cmd("FCALL_RO", "ssro", "1", fk) == b"fv")
    fro_before = info_counters(c)["function_readonly_rejections"]
    note("FCALL_RO refuses a function without no-writes",
         c.raw("FCALL_RO", "ssset", "1", fk, "z") ==
         b"-ERR Can not execute a script with write flag using *_ro command.\r\n")
    note("FCALL_RO rejection counter fired",
         info_counters(c)["function_readonly_rejections"] == fro_before + 1)
    note("plain FCALL of a no-writes function is still read-only",
         c.raw("FCALL", "sswronly", "1", fk).startswith(
             b"-ERR Write commands are not allowed from read-only scripts."))
    note("the refused no-writes write did not land", c.cmd("GET", fk) == b"fv")
    note("plain FCALL of a writing function does write",
         c.cmd("FCALL", "ssset", "1", fk, "written") == b"OK" and c.cmd("GET", fk) == b"written")
    calls_before = info_counters(c)["function_calls"]
    c.cmd("FCALL", "ssget", "1", fk)
    note("function_calls counter fired", info_counters(c)["function_calls"] > calls_before)

    # Prove the per-thread materialization: spread FCALL over keys on many executor threads.
    # Own key namespace so the type fixtures built for the read-only controls cannot leak in.
    spread = ["%s:spread:%d" % (PREFIX, i) for i in range(32)]
    for k in spread:
        c2.cmd("SET", k, "sv")
    spread_failures = [(k, r) for k, r in ((k, c2.cmd("FCALL", "ssget", "1", k)) for k in spread)
                       if r != [b"sv", 1, 0]]
    note("FCALL over 32 shard-spread keys from another connection", not spread_failures,
         spread_failures[:3])
    rebuilds = info_counters(c)["function_thread_rebuilds"]
    note("thread materializations happened", rebuilds > 0, rebuilds)
    for k in spread[:8]:
        c2.cmd("FCALL", "ssget", "1", k)
    note("no rebuild without a generation change (negative control)",
         info_counters(c)["function_thread_rebuilds"] == rebuilds, rebuilds)
    c.cmd("FUNCTION", "LOAD", "REPLACE", LIB_MAIN)
    for k in spread[:8]:
        c2.cmd("FCALL", "ssget", "1", k)
    after_rebuild = info_counters(c)["function_thread_rebuilds"]
    note("generation change forces a rebuild", after_rebuild > rebuilds,
         "%d -> %d" % (rebuilds, after_rebuild))

    shape(c, "FCALL unknown function", "FCALL", "ss_no_such_function", "0")
    shape(c, "FCALL numkeys not a number", "FCALL", "ssget", "x")
    shape(c, "FCALL numkeys negative", "FCALL", "ssget", "-1")
    shape(c, "FCALL numkeys > argc", "FCALL", "ssget", "5", "a")
    shape(c, "FCALL arity", "FCALL", "ssget")

    # ---- 7. FUNCTION LOAD error matrix ------------------------------------------------------
    print("[7] FUNCTION error matrix")
    bad = [
        ("missing shebang", "redis.register_function('f', function() return 1 end)"),
        ("unknown engine", "#!py name=ssx\nredis.register_function('f', function() return 1 end)"),
        ("no library name", "#!lua\nredis.register_function('f', function() return 1 end)"),
        ("illegal library name",
         "#!lua name=ss-x\nredis.register_function('f', function() return 1 end)"),
        ("unknown metadata field",
         "#!lua name=ssy zz=1\nredis.register_function('f', function() return 1 end)"),
        ("no functions registered", "#!lua name=ssempty\nlocal x = 1"),
        ("body syntax error", "#!lua name=ssbad\nreturn ("),
        ("redis.call at load time",
         "#!lua name=sscall\nredis.call('GET','x')\nredis.register_function('f', function() return 1 end)"),
        ("register_function single non-table", "#!lua name=ssr1\nredis.register_function('f')"),
        ("register_function 3 args",
         "#!lua name=ssr2\nredis.register_function('f', function() return 1 end, 'x')"),
        ("register_function missing name",
         "#!lua name=ssr3\nredis.register_function{callback=function() return 1 end}"),
        ("register_function missing callback",
         "#!lua name=ssr4\nredis.register_function{function_name='f'}"),
        ("register_function callback not a function",
         "#!lua name=ssr5\nredis.register_function{function_name='f', callback=5}"),
        ("register_function unknown key",
         "#!lua name=ssr6\nredis.register_function{function_name='f', "
         "callback=function() return 1 end, zz=1}"),
        ("register_function unknown flag",
         "#!lua name=ssr7\nredis.register_function{function_name='f', "
         "callback=function() return 1 end, flags={'nope'}}"),
        ("register_function flags not a table",
         "#!lua name=ssr8\nredis.register_function{function_name='f', "
         "callback=function() return 1 end, flags='no-writes'}"),
        ("duplicate function inside one library",
         "#!lua name=ssr9\nredis.register_function('f', function() return 1 end)\n"
         "redis.register_function('f', function() return 2 end)"),
        ("duplicate function across libraries",
         "#!lua name=ssr10\nredis.register_function('ssget', function() return 1 end)"),
    ]
    for name, code in bad:
        reply = shape(c, "FUNCTION LOAD " + name, "FUNCTION", "LOAD", code)
        note("FUNCTION LOAD refuses: " + name, reply[:1] == b"-", reply[:90])
    note("no failed library leaked into the registry",
         info_counters(c)["number_of_libraries"] == 2,
         info_counters(c)["number_of_libraries"])
    shape(c, "FUNCTION LOAD arity", "FUNCTION", "LOAD")
    shape(c, "FUNCTION LOAD unknown option", "FUNCTION", "LOAD", "BOGUS", LIB_SECOND)
    shape(c, "FUNCTION DELETE missing", "FUNCTION", "DELETE", "ss_nope")
    shape(c, "FUNCTION DELETE arity", "FUNCTION", "DELETE")
    shape(c, "FUNCTION LIST unknown arg", "FUNCTION", "LIST", "BOGUS")
    shape(c, "FUNCTION LIST LIBRARYNAME without value", "FUNCTION", "LIST", "LIBRARYNAME")
    shape(c, "FUNCTION FLUSH bad mode", "FUNCTION", "FLUSH", "BOGUS")
    shape(c, "FUNCTION STATS extra args", "FUNCTION", "STATS", "x")
    shape(c, "FUNCTION DUMP extra args", "FUNCTION", "DUMP", "x")
    shape(c, "FUNCTION KILL", "FUNCTION", "KILL")
    shape(c, "FUNCTION unknown subcommand", "FUNCTION", "NOPE")
    shape(c, "FUNCTION RESTORE garbage", "FUNCTION", "RESTORE", "not-a-payload")
    note("FUNCTION HELP is a status array",
         c.raw("FUNCTION", "HELP")[:1] == b"*" and b"FUNCTION <subcommand>" in
         c.raw("FUNCTION", "HELP"))
    # A body whose error is raised at load time must not half-register.
    note("failed library registers nothing", c.cmd("FUNCTION", "LIST", "LIBRARYNAME", "ssr9") == [])

    # ---- 8. DUMP / RESTORE ------------------------------------------------------------------
    print("[8] FUNCTION DUMP / RESTORE round trip")
    payload = c.cmd("FUNCTION", "DUMP")
    note("DUMP payload is framed and non-trivial",
         isinstance(payload, bytes) and payload.startswith(b"TOMOFUN1") and len(payload) > 40,
         len(payload) if isinstance(payload, bytes) else payload)
    note("RESTORE APPEND onto a colliding registry is refused",
         c.raw("FUNCTION", "RESTORE", payload) == b"-ERR Library sslib already exists\r\n")
    note("registry untouched by the refused restore",
         info_counters(c)["number_of_libraries"] == 2)
    note("RESTORE REPLACE succeeds", c.cmd("FUNCTION", "RESTORE", payload, "REPLACE") == b"OK")
    note("RESTORE bad policy is refused",
         c.raw("FUNCTION", "RESTORE", payload, "BOGUS").startswith(
             b"-ERR Wrong restore policy given"))
    corrupt = bytearray(payload)
    corrupt[len(corrupt) // 2] ^= 0xFF
    note("RESTORE detects a corrupted payload",
         c.raw("FUNCTION", "RESTORE", bytes(corrupt)) ==
         b"-ERR DUMP payload version or checksum are wrong\r\n")
    note("RESTORE detects a truncated payload",
         c.raw("FUNCTION", "RESTORE", payload[:-4]) ==
         b"-ERR DUMP payload version or checksum are wrong\r\n")
    note("FUNCTION FLUSH clears everything", c.cmd("FUNCTION", "FLUSH", "SYNC") == b"OK")
    note("registry empty after flush",
         c.cmd("FUNCTION", "LIST") == [] and info_counters(c)["number_of_functions"] == 0)
    note("FCALL after flush is Function not found",
         c.raw("FCALL", "ssget", "1", fk) == b"-ERR Function not found\r\n")
    note("RESTORE into an empty registry", c.cmd("FUNCTION", "RESTORE", payload) == b"OK")
    note("round trip restored both libraries and every function",
         info_counters(c)["number_of_libraries"] == 2 and
         info_counters(c)["number_of_functions"] == 5)
    note("restored function runs on a fresh connection",
         Conn().cmd("FCALL", "ssget", "1", fk) == [b"written", 1, 0])
    note("restored FUNCTION LIST WITHCODE matches the original source",
         dict(zip(c.cmd("FUNCTION", "LIST", "LIBRARYNAME", "sslib", "WITHCODE")[0][0::2],
                  c.cmd("FUNCTION", "LIST", "LIBRARYNAME", "sslib", "WITHCODE")[0][1::2]))
         [b"library_code"] == LIB_MAIN.encode())
    note("FUNCTION DELETE removes one library",
         c.cmd("FUNCTION", "DELETE", "sslib2") == b"OK" and
         info_counters(c)["number_of_libraries"] == 1)
    note("its function is gone", c.raw("FCALL", "ssecho", "0", "x") ==
         b"-ERR Function not found\r\n")
    note("the other library still runs", c.cmd("FCALL", "ssget", "1", fk)[0] == b"written")

    # ---- 9. keyspace notifications through FCALL ---------------------------------------------
    print("[9] keyspace notifications through FCALL")
    saved_events = c.cmd("CONFIG", "GET", "notify-keyspace-events")
    c.cmd("CONFIG", "SET", "notify-keyspace-events", "KEA")
    sub = Conn()
    sub.cmd("SUBSCRIBE", "__keyevent@0__:set")
    fired_before = info_counters(c)["notify_events_fired"]
    c.cmd("FCALL", "ssset", "1", fk, "notified")
    deadline = time.time() + 3
    event = None
    sub.sock.settimeout(3)
    while time.time() < deadline:
        try:
            message = sub.read()  # pending push only: sending here would corrupt the stream
        except Exception:
            break
        if isinstance(message, list) and message[0] == b"message":
            event = message
            break
    note("FCALL write emitted the keyevent notification",
         event is not None and event[2] == fk.encode(), event)
    note("notify counter fired", info_counters(c)["notify_events_fired"] > fired_before)
    sub.close()
    c.cmd("CONFIG", "SET", "notify-keyspace-events",
          saved_events[1].decode() if saved_events[1] else "")

finally:
    try:
        c.cmd("FUNCTION", "FLUSH")
        c.cmd("SCRIPT", "FLUSH")
        c.cmd("DEL", *keys)
        c.cmd("DEL", *["%s:spread:%d" % (PREFIX, i) for i in range(32)])
    except Exception:
        pass
    for conn in (c, c2, ORACLE_CONN):
        if conn:
            try:
                if conn is ORACLE_CONN:
                    conn.cmd("FUNCTION", "FLUSH")
                    conn.cmd("SCRIPT", "FLUSH")
                conn.close()
            except Exception:
                pass

print("SCRIPTSURF: %d checks, %d FAIL%s" %
      (CHECKS, FAIL, "" if ORACLE else " (no oracle: error shapes not byte-compared)"))
sys.exit(1 if FAIL else 0)
