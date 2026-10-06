#!/usr/bin/env python3
"""CD13b wire properties, shared by differ and the serverless/oracle driver.

Callbacks consume argument lists and return complete RESP frames. Geometry comes ONLY from
the target's hash/router and live shard ownership; Redis has no TomoKV shard map.
"""
import io
import re
from _lib import Conn


def decoded(raw):
    reader = object.__new__(Conn)
    reader.file = io.BytesIO(raw)
    value = reader.read()
    assert not reader.file.read(), "trailing RESP bytes"
    return value


def integer(call, args):
    raw = call(args)
    assert re.fullmatch(rb":[0-9]+\r\n", raw), (args, raw)
    return int(raw[1:-2])


def ownership(call, keys):
    # DEBUG SHARD calls FlatStore::hash_key with this boot's random seed. LBSIGNALS supplies
    # current owners and migration counters; sid modulo executor count is not an owner proof.
    shards = [integer(call, ["DEBUG", "SHARD", key]) for key in keys]
    frame = call(["DEBUG", "LBSIGNALS"])
    raw = decoded(frame)
    if frame.startswith(b"="):
        assert raw.startswith(b"txt:"), raw
        raw = raw[4:]
    assert isinstance(raw, bytes) and raw.startswith(b"lbver 1"), raw
    rows = {}
    for line in raw.splitlines():
        fields = line.split()
        if fields and fields[0] == b"shard":
            rows[int(fields[1])] = (int(fields[2]), int(fields[6]))
    assert len(rows) >= 2 and len({row[0] for row in rows.values()}) >= 2, rows
    return tuple((sid, *rows[sid]) for sid in shards)


def aclcat_property(sides):
    failures = 0
    for label, call in sides:
        try:
            unknown = call(["COMMAND", "LIST", "FILTERBY", "ACLCAT", "cd13b-no-such-category"])
            assert unknown == b"*0\r\n", unknown
            canonical = decoded(call(["COMMAND", "LIST", "FILTERBY", "ACLCAT", "string"]))
            assert isinstance(canonical, list) and b"get" in canonical, canonical
            for spelling in ("STRING", "StRiNg"):
                raw = call(["COMMAND", "LIST", "FILTERBY", "ACLCAT", spelling])
                value = decoded(raw)
                assert raw.startswith(b"*") and isinstance(value, list), raw
                assert sorted(value) == sorted(canonical), (spelling, value)
            print("  CD13b ACLCAT %s: unknown=%r STRING/StRiNg=%d commands" %
                  (label, unknown, len(canonical)))
        except AssertionError as error:
            failures += 1
            print("  CD13b ACLCAT FAIL %s: %r" % (label, error))
    return failures


def geo_store_property(sides, route):
    failures = 0
    verbs = ("STORE", "STOREDIST", "GEOSEARCHSTORE")
    for label, call in sides:
        settings = []
        try:
            for name, value in (("maxmemory", "1073741824"),
                                ("maxmemory-policy", "allkeys-lfu")):
                old = decoded(call(["CONFIG", "GET", name]))
                assert isinstance(old, list) and len(old) == 2 and old[0] == name.encode(), old
                settings.append((name, old[1]))
                assert call(["CONFIG", "SET", name, value]) == b"+OK\r\n"
            for verb in verbs:
                source = destination = None
                try:
                    armed = False
                    for attempt in range(3):
                        source = "cd13b:%s:%s:%d:source" % (label, verb, attempt)
                        for suffix in range(4096):
                            candidate = source + ":destination:%d" % suffix
                            witness = route([source, candidate])
                            if witness[0][0] != witness[1][0] and witness[0][1] != witness[1][1]:
                                destination = candidate
                                break
                        else:
                            raise AssertionError("bounded search found no cross-owner pair")
                        integer(call, ["DEL", source])
                        integer(call, ["DEL", destination])
                        assert call(["GEOADD", source, "13", "38", "a", "13.01", "38.01", "b"]) == b":2\r\n"
                        assert call(["ZADD", destination, "0", "m0"]) == b":1\r\n"
                        initial = integer(call, ["OBJECT", "FREQ", destination])
                        args = ["ZADD", destination]
                        for member in range(1, 160):
                            args += [str(member), "m%d" % member]
                        assert call(args) == b":159\r\n"
                        assert call(["ZREM", destination] + ["m%d" % i for i in range(2, 160)]) == b":158\r\n"
                        assert call(["OBJECT", "ENCODING", destination]) == b"$8\r\nskiplist\r\n"
                        for _ in range(4096):
                            assert call(["ZCARD", destination]) == b":2\r\n"
                        before = integer(call, ["OBJECT", "FREQ", destination])
                        if before >= initial + 3:
                            armed = True
                            break
                        integer(call, ["DEL", source])
                        integer(call, ["DEL", destination])
                    assert armed, "LFU counter never armed on three fresh destinations"
                    witness = route([source, destination])
                    assert witness[0][0] != witness[1][0] and witness[0][1] != witness[1][1], witness
                    if verb == "GEOSEARCHSTORE":
                        args = [verb, destination, source, "FROMLONLAT", "13", "38", "BYRADIUS", "10", "km"]
                    else:
                        args = ["GEORADIUS", source, "13", "38", "10", "km", verb, destination]
                    stored = call(args)
                    after_witness = route([source, destination])
                    assert after_witness == witness, ("owner/migration changed during STORE", witness, after_witness)
                    assert stored == b":2\r\n", stored
                    after_raw = call(["OBJECT", "FREQ", destination])
                    assert re.fullmatch(rb":[0-9]+\r\n", after_raw), after_raw
                    after = int(after_raw[1:-2])
                    encoding = call(["OBJECT", "ENCODING", destination])
                    # Redis geo.c creates a new result and may compact it. Only GEOADD has the
                    # no-demotion rule. Preserve the landed local STORE behavior here as well.
                    assert encoding == b"$8\r\nlistpack\r\n", encoding
                    print("  CD13b GEO %s %s keys=%r route(sid,owner,migrations)=%r "
                          "initial=%d before=%d after=%d store=%r freq=%r encoding=%r" %
                          (label, verb, (source, destination), witness, initial, before, after,
                           stored, after_raw, encoding))
                    assert after > initial, ("destination LFU reset", initial, before, after)
                except AssertionError as error:
                    failures += 1
                    print("  CD13b GEO FAIL %s %s: %r" % (label, verb, error))
                finally:
                    if source and destination:
                        integer(call, ["DEL", source])
                        integer(call, ["DEL", destination])
        finally:
            for name, value in reversed(settings):
                assert call(["CONFIG", "SET", name, value]) == b"+OK\r\n", (label, name)
    return failures
