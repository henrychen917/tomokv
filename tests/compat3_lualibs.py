#!/usr/bin/env python3
"""CC4.7: exact RESP frames from Redis 7.4's Lua helpers, EVAL and FUNCTION.

Called by gate.sh's compat3_case lifetime/geometry matrix. Every case executes
even on PRE; missing helpers cannot hide later calls or later owners. Errors are
returned by pcall as ordinary values, without normalizing their bytes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

from _lib import Conn, RespError, info, owner_buckets, topology


class Wire(Conn):
    def frame(self):
        line = self.file.readline()
        assert line.endswith(b"\r\n"), repr(line)
        kind, value = line[:1], line[1:-2]
        if kind == b"$" and int(value) >= 0:
            payload = self.file.read(int(value) + 2)
            assert len(payload) == int(value) + 2 and payload.endswith(b"\r\n")
            return line + payload
        if kind == b"*" and int(value) >= 0:
            return line + b"".join(self.frame() for _ in range(int(value)))
        assert kind in (b"+", b"-", b":", b"$", b"*"), line
        return line

    def command(self, *args):
        self.send(*args)
        return self.frame()


def cases():
    result = []

    def add(name, body):
        result.append((name, body))

    add("globals", "return {type(cjson),type(cmsgpack),type(bit),type(struct),type(redis.sha1hex)}")
    for lib in ("cjson", "cmsgpack", "bit", "struct"):
        add(lib + ".exports", f"local a={{}}; for k,v in pairs({lib}) do a[#a+1]=k..':'..type(v) end; table.sort(a); return a")
    for name, expression in (
        ("empty", "{}"), ("array", "{1,true,false,cjson.null,'x'}"),
        ("object", "{key='value'}"), ("null", "cjson.null"),
        ("string", "'a\\000\\001\\031\\n\\r\\t\\b\\f\\\"\\\\/\\255'"),
        ("utf8", "'雪\\226\\130\\172'"), ("false", "false"),
        ("number", "1.2345678901234567"), ("negative_zero", "-1/math.huge"),
        ("sparse_safe", "{[3]='v'}"), ("sparse", "{[100]='v'}"),
        ("mixed", "{[1]='x',key='y'}"), ("bad_key", "{[true]='x'}"),
        ("function", "function() end"), ("nan", "0/0"),
        ("inf", "math.huge"), ("negative_inf", "-math.huge"),
    ):
        add("cjson.encode." + name, "return cjson.encode(" + expression + ")")
    add("cjson.defaults", "return {cjson.encode_max_depth(),cjson.decode_max_depth(),cjson.encode_number_precision(),cjson.encode_keep_buffer(),cjson.encode_invalid_numbers(),cjson.decode_invalid_numbers(),cjson.encode_sparse_array()}")
    for text in ('null', 'true', 'false', '123.5', '[]', '{}', '[1,null,false,"x"]',
                 '{"a":1}', 'NaN', 'Infinity', '-Infinity', '1e999', '0x10',
                 '"\\u0000\\u96ea\\ud834\\udd1e"', '"\\ud800"', '"\\udc00"',
                 '', '[1,]', '{', 'true false', '01', '"x\\q"', '"a\x00b"'):
        literal = json.dumps(text, ensure_ascii=False).replace('\\u0000', '\\000')
        # JSON escapes in the input itself must survive the Lua source parser.
        add("cjson.decode." + repr(text), f"local v=cjson.decode({literal}); return {{type(v),cjson.encode(v)}}")
    add("cjson.sparse_convert", "local j=cjson.new(); j.encode_sparse_array(true,2,10); return j.encode({[100]='v'})")
    add("cjson.new_mutable", "local j=cjson.new(); j.extra=17; j.encode_keep_buffer(false); return {j.extra,j.encode({}),j.encode_keep_buffer()}")
    for precision in (0, 1, 7, 14, 15):
        add(f"cjson.precision.{precision}", f"local j=cjson.new(); j.encode_number_precision({precision}); return j.encode(1/3)")
    for setting in ('true', 'false', "'null'"):
        add("cjson.invalid_encode." + setting, f"local j=cjson.new(); j.encode_invalid_numbers({setting}); return {{j.encode(0/0),j.encode(math.huge),j.encode(-math.huge)}}")
    add("cjson.invalid_decode.off", "local j=cjson.new(); j.decode_invalid_numbers(false); return j.decode('NaN')")
    for depth in (999, 1000, 1001):
        add(f"cjson.decode_depth.{depth}", f"local t=cjson.decode(string.rep('[',{depth})..'0'..string.rep(']',{depth})); return type(t)")
        add(f"cjson.encode_depth.{depth}", f"local t=0; for i=1,{depth} do t={{t}} end; return #cjson.encode(t)")
    add("cjson.depth_config", "local j=cjson.new(); j.encode_max_depth(2); return j.encode({{{0}}})")
    add("cjson.decode_depth_config", "local j=cjson.new(); j.decode_max_depth(2); return j.decode('[[[0]]]')")
    add("cjson.cycle", "local t={}; t[1]=t; return cjson.encode(t)")

    for name, expr in (
        ("nil", "nil"), ("booleans", "true,false"), ("empty", "{}"),
        ("array", "{1,2,'x'}"), ("map", "{key='value'}"),
        ("binary", "'a\\000\\255z'"), ("multi", "1,nil,true,'x',{5}"),
        ("integers", "0,127,128,255,256,65535,65536,4294967295,4294967296,9007199254740991,-1,-32,-33,-128,-129,-32768,-32769,-2147483648,-2147483649"),
        ("float", "0.5,1/3,-0.5,math.huge,-math.huge,0/0"),
        ("function", "function() end"), ("userdata", "cjson.null"),
    ):
        add("cmsgpack.pack." + name, f"return cmsgpack.pack({expr})")
    add("cmsgpack.pack.noargs", "return cmsgpack.pack()")
    add("cmsgpack.unpack.multi", "return {cmsgpack.unpack(cmsgpack.pack(1,'x',true,false))}")
    add("cmsgpack.unpack.nil_count", "return select('#',cmsgpack.unpack(cmsgpack.pack(nil,1,nil)))")
    add("cmsgpack.unpack.types", "local a,b,c,d,e,f=cmsgpack.unpack(cmsgpack.pack(nil,true,42,'a\\000b',{1,2},{k='v'})); return {type(a),b,c,d,e,f.k}")
    for length in (31, 32, 255, 256, 65535, 65536):
        add(f"cmsgpack.string.{length}", f"local s=string.rep('x',{length}); local p=cmsgpack.pack(s); return {{#p,string.sub(p,1,8),cmsgpack.unpack(p)==s}}")
    for depth in (15, 16, 17):
        add(f"cmsgpack.depth.{depth}", f"local t=0; for i=1,{depth} do t={{t}} end; return cmsgpack.pack(t)")
    add("cmsgpack.cycle", "local t={}; t[1]=t; return cmsgpack.pack(t)")
    for data in ("''", "'\\193'", "'\\217'", "'\\218\\000'", "'\\129'", "'\\145'", "'\\203\\000'", "'\\192\\192'"):
        add("cmsgpack.malformed." + data, f"return {{cmsgpack.unpack({data})}}")
    for offset in (-1, 0, 1, 2, 3, 4):
        add(f"cmsgpack.unpack_one.{offset}", f"return {{cmsgpack.unpack_one(cmsgpack.pack(11,22,33),{offset})}}")
    for limit in (-1, 0, 1, 2, 4):
        add(f"cmsgpack.unpack_limit.{limit}", f"return {{cmsgpack.unpack_limit(cmsgpack.pack(11,22,33),{limit},1)}}")
    for length in (15, 16):
        add(f"cmsgpack.array.{length}", f"local t={{}}; for i=1,{length} do t[i]=i end; return cmsgpack.pack(t)")
        # Map iteration order is unspecified; compare the decoded cardinality
        # and the format header, while the one-key map above compares all bytes.
        add(f"cmsgpack.map.{length}", f"local t={{}}; for i=1,{length} do t['k'..i]=i end; local p=cmsgpack.pack(t); local n=0; for k,v in pairs(cmsgpack.unpack(p)) do n=n+1 end; return {{string.byte(p,1),n}}")
    add("cmsgpack.return_limit", "return select('#',cmsgpack.unpack(string.rep(string.char(192),8001)))")
    add("cmsgpack.bounded_unpack", "return {cmsgpack.unpack_limit(string.rep(string.char(1),8001),3)}")

    for op in ('band', 'bor', 'bxor'):
        add("bit." + op, f"return {{bit.{op}(0xff,0x0f,3),bit.{op}(-1,0x80000000),bit.{op}(42)}}")
        add("bit." + op + ".noargs", f"return bit.{op}()")
    for op in ('lshift', 'rshift', 'arshift', 'rol', 'ror'):
        add("bit." + op, f"return {{bit.{op}(-8,1),bit.{op}(1,31),bit.{op}(1,32),bit.{op}(1,-1)}}")
    add("bit.tobit", "return {bit.tobit(4294967295),bit.tobit(4294967296),bit.tobit(2147483648),bit.tobit(1.5),bit.tobit('17')}")
    add("bit.tohex", "return {bit.tohex(-1),bit.tohex(0xabcdef,4),bit.tohex(0xabcdef,-8),bit.tohex(1,0),bit.tohex(1,20)}")
    add("bit.bnot_bswap", "return {bit.bnot(0),bit.bnot(-1),bit.bswap(0x12345678)}")
    add("bit.bad_argument", "return bit.band({})")

    for fmt, values in (("<bBhHi4I4", "-8,250,-1234,60000,-1234567,4000000000"),
                        (">i8I8", "-4294967297,9007199254740991"),
                        ("<fd", "1.5,1/3"), (">fd", "-2.5,1/7"),
                        ("!4bxi4", "1,1234"), ("c4s", "'abcdef','xy'"),
                        ("<Bc0", "3,'abc'")):
        add("struct.pack." + fmt, f"return struct.pack('{fmt}',{values})")
        add("struct.unpack." + fmt, f"return {{struct.unpack('{fmt}',struct.pack('{fmt}',{values}))}}")
    for fmt in ('bBhHi4I4', '<i8I8', '!4bxi4', 'fd', 'c4', 's', 'c0', 'i0', 'i17', 'Q', '!3i4'):
        add("struct.size." + fmt, f"return struct.size('{fmt}')")
    add("struct.offset", "return {struct.unpack('B','abc',2)}")
    add("struct.short", "return struct.unpack('i4','x')")
    add("struct.unterminated", "return struct.unpack('s','abc')")
    add("struct.missing_value", "return struct.pack('i4')")
    add("struct.binary", "return struct.pack('c4','a\\000b\\255')")
    for offset in (-1, 0, 4):
        add(f"struct.offset.{offset}", f"return struct.unpack('B','abc',{offset})")

    for name, value in (("empty", "''"), ("abc", "'abc'"), ("binary", "'a\\000b\\255'"),
                        ("long", "string.rep('a',4096)"), ("number", "123.5"),
                        ("nil", "nil"), ("bool", "true"), ("table", "{}"), ("function", "function() end")):
        add("sha1hex." + name, f"return redis.sha1hex({value})")
    add("sha1hex.noargs", "return redis.sha1hex()")
    add("sha1hex.extraargs", "return redis.sha1hex('a','b')")
    for lib, field in (("cjson", "encode"), ("cmsgpack", "pack"), ("bit", "band"), ("struct", "pack"), ("redis", "sha1hex")):
        for op, statement in (("existing", f"{lib}.{field}=0"), ("new", f"{lib}.added=0"),
                              ("rawset", f"rawset({lib},'{field}',0)"),
                              ("metatable", f"setmetatable({lib},{{}})"),
                              ("insert", f"table.insert({lib},1)")):
            add("readonly." + lib + "." + op, statement + "; return 'MUTATED'")
    return result


SMOKE = "return {cjson.encode({}),cmsgpack.pack(1),bit.tohex(-1),struct.pack('>I2',258),redis.sha1hex('abc')}"
LOOPS = ('cjson.encode({1})', 'cmsgpack.pack(1)', 'bit.band(7,3)',
         "struct.pack('I2',12)", "redis.sha1hex('abc')")


def protected(body):
    # Wrap errors in an array so Redis's Lua-to-RESP conversion cannot interpret
    # the caught table as a top-level error reply. No trimming or rewriting.
    return ("local ok,v=pcall(function() " + body + " end); "
            "if not ok and type(v)=='table' then v=v.err end; "
            "return {ok and 'ok' or 'error',v}")


def describe(frame):
    return {"size": len(frame), "sha256": hashlib.sha256(frame).hexdigest(),
            "wire_hex": frame.hex() if len(frame) <= 512 else frame[:160].hex()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('host'); p.add_argument('port', type=int)
    p.add_argument('--oracle', nargs=2, required=True)
    p.add_argument('--case', choices=('all',), required=True)
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--engine', choices=('epoll', 'uring'), required=True)
    p.add_argument('--atomic', type=int, required=True)
    p.add_argument('--read-local', type=int, required=True)
    args = p.parse_args()
    target = Wire(args.host, args.port, timeout=15)
    oracle = Wire(args.oracle[0], int(args.oracle[1]), timeout=15)
    failures = []
    compared = 0
    try:
        version = info(oracle, 'server')['redis_version']
        assert version.startswith('7.4.'), version
        observed = info(target, 'server')
        for key, want in dict(thread_mode=args.mode, net_io=args.engine, atomic=str(args.atomic),
                              read_local=str(args.read_local), shards='16').items():
            assert observed[key] == want, (key, observed[key], want)
        topo = topology(target)
        assert len(topo.roles) == 8
        assert len(topo.owners) == (8 if args.mode == '1s' else 2), topo
        keys = owner_buckets(target, 'lualibs:owner:', len(topo.owners), topo=topo)
        assert set(keys) == set(topo.owners)
        key = keys[topo.owners[0]][0]
        print('GEOMETRY ' + json.dumps(vars(args), sort_keys=True), flush=True)
        print('ORACLE ' + version, flush=True)

        def check(label, left, right):
            nonlocal compared
            compared += 1
            print(json.dumps(dict(case=label, oracle=describe(right), target=describe(left),
                                  equal=left == right), sort_keys=True), flush=True)
            if left != right:
                failures.append(label)

        def owner_smoke(owner):
            c = Wire(args.host, args.port, timeout=15)
            try:
                return owner, c.command('EVAL', protected(SMOKE), 1, keys[owner][0])
            finally:
                c.close()

        expected = oracle.command('EVAL', protected(SMOKE), 1, key)
        assert b'$2\r\nok\r\n' in expected, expected
        # Fresh executor states are initialized concurrently, exercising fpconv.
        with ThreadPoolExecutor(max_workers=len(topo.owners)) as pool:
            for owner, reply in pool.map(owner_smoke, topo.owners):
                check('owner-init:' + str(owner), reply, expected)

        matrix = cases()
        source = '#!lua name=lualibs\n' + '\n'.join(
            f"redis.register_function('lualib_{i}',function(keys,args) {protected(body)} end)"
            for i, (_, body) in enumerate(matrix))
        source += '\n' + '\n'.join(
            f"redis.register_function('lualibs_spin_{i}',function() while true do {body} end end)"
            for i, body in enumerate(LOOPS))
        for c in (oracle, target):
            assert c.command('FUNCTION', 'FLUSH') == b'+OK\r\n'
        check('FUNCTION LOAD callbacks', target.command('FUNCTION', 'LOAD', source),
              oracle.command('FUNCTION', 'LOAD', source))
        for i, (name, body) in enumerate(matrix):
            for surface, argv in (('EVAL', ('EVAL', protected(body), 1, key)),
                                  ('FCALL', ('FCALL', 'lualib_' + str(i), 1, key))):
                check(surface + ':' + name, target.command(*argv), oracle.command(*argv))
        for helper in ('cjson', 'cmsgpack', 'bit', 'struct', 'redis.sha1hex'):
            load_source = ("#!lua name=lualibs_load\nlocal v=" + helper +
                           "; redis.register_function('lualibs_load_probe',function() return v end)")
            expected = oracle.command('FUNCTION', 'LOAD', load_source)
            assert expected.startswith(b'-ERR '), expected
            check('FUNCTION LOAD forbids ' + helper, target.command('FUNCTION', 'LOAD', load_source), expected)
        for owner in topo.owners:
            argv = ('FCALL', 'lualib_0', 1, keys[owner][0])
            check('FUNCTION callback helper globals owner:' + str(owner),
                  target.command(*argv), oracle.command(*argv))
        for c in (target, oracle):
            assert c.command('SCRIPT', 'FLUSH') == b'+OK\r\n'
        for owner in topo.owners:
            argv = ('FCALL', 'lualib_0', 1, keys[owner][0])
            check('FUNCTION helpers after SCRIPT FLUSH owner:' + str(owner),
                  target.command(*argv), oracle.command(*argv))
        # The main singleton cjson table remains frozen; C-backed configuration
        # methods are intentionally legal, as in Redis. Restore it before leaving.
        body = "local old=cjson.encode_number_precision(); cjson.encode_number_precision(3); local v=cjson.encode(1/3); cjson.encode_number_precision(old); return v"
        check('cjson singleton configuration', target.command('EVAL', protected(body), 1, key),
              oracle.command('EVAL', protected(body), 1, key))
        check('SCRIPT KILL idle', target.command('SCRIPT', 'KILL'), oracle.command('SCRIPT', 'KILL'))
        # TomoKV deliberately retains its pre-existing instruction budget, while
        # Redis admits a time-limited busy window and then accepts explicit KILL.
        # Prove both behaviours with every helper and both invocation surfaces;
        # do not claim byte equivalence for this documented execution-policy gap.
        old_limit = oracle.cmd('CONFIG', 'GET', 'lua-time-limit')[1]
        assert oracle.cmd('CONFIG', 'SET', 'lua-time-limit', 1) == b'OK'
        try:
            for i, body in enumerate(LOOPS):
                for surface, argv, kill in (
                    ('EVAL', ('EVAL', 'while true do ' + body + ' end', 1, key), ('SCRIPT', 'KILL')),
                    ('FCALL', ('FCALL', 'lualibs_spin_' + str(i), 1, key), ('FUNCTION', 'KILL')),
                ):
                    got = target.command(*argv)
                    bounded = got.startswith(b'-BUSY ') and b'instruction limit' in got
                    if not bounded:
                        failures.append(surface + ':instruction-budget:' + body)
                    running = Wire(args.oracle[0], int(args.oracle[1]), timeout=15)
                    try:
                        running.send(*argv)
                        busy = oracle.command('PING')
                        # If PING won the socket race, retry after the invocation
                        # is definitely sent. Bound attempts; never skip the arm.
                        for _ in range(100):
                            if busy.startswith(b'-BUSY '):
                                break
                            busy = oracle.command('PING')
                        assert busy.startswith(b'-BUSY '), busy
                        killed = oracle.command(*kill)
                        assert killed == b'+OK\r\n', killed
                        reply = running.frame()
                        assert b'killed' in reply.lower(), reply
                        print(json.dumps(dict(control=surface + ':' + body, target=describe(got),
                            target_instruction_budget=bounded, oracle_busy=describe(busy),
                            oracle_kill=describe(killed), oracle_reply=describe(reply))), flush=True)
                    finally:
                        oracle.command(*kill)
                        running.close()
        finally:
            assert oracle.cmd('CONFIG', 'SET', 'lua-time-limit', old_limit) == b'OK'
        assert compared >= 300, compared
        print(json.dumps(dict(compared=compared, failed=len(failures), failures=failures)), flush=True)
        assert not failures, f'{len(failures)}/{compared} exact-frame comparisons failed'
    finally:
        oracle.close(); target.close()


if __name__ == '__main__':
    main()
