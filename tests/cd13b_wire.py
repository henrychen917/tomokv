#!/usr/bin/env python3
"""CD13b wire properties, shared by differ and the serverless/oracle driver.

Callbacks consume argument lists and return complete RESP frames. Geometry comes ONLY from
the target's hash/router and live shard ownership; Redis has no TomoKV shard map.
"""
import io
import re
import time
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
    # DEBUG SHARD calls FlatStore::hash_key with the current hash seed. LBSIGNALS supplies
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
                    deadline = time.monotonic() + 30
                    attempt = 0
                    witness = None
                    while True:
                        assert time.monotonic() < deadline, (
                            "LFU/cross-owner window never witnessed within 30 s", attempt, witness)
                        if source and destination:
                            integer(call, ["DEL", source])
                            integer(call, ["DEL", destination])
                        source = "cd13b:%s:%s:%d:source" % (label, verb, attempt)
                        destination = None
                        attempt += 1
                        for suffix in range(4096):
                            assert time.monotonic() < deadline, "cross-owner search exhausted window budget"
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
                        for touch in range(4096):
                            if touch % 128 == 0:
                                assert time.monotonic() < deadline, "LFU priming exhausted window budget"
                            assert call(["ZCARD", destination]) == b":2\r\n"
                        before = integer(call, ["OBJECT", "FREQ", destination])
                        # Priming can move the hot destination. Arm both witnesses on
                        # the same fresh state; an earlier placement is not evidence
                        # that STORE will still cross owners after 4096 reads.
                        witness = route([source, destination])
                        cross_owner = (witness[0][0] != witness[1][0] and
                                       witness[0][1] != witness[1][1])
                        if before < initial + 3 or not cross_owner:
                            print("  CD13b GEO rearm %s %s attempt=%d initial=%d before=%d route=%r" %
                                  (label, verb, attempt, initial, before, witness))
                            continue
                        if verb == "GEOSEARCHSTORE":
                            args = [verb, destination, source, "FROMLONLAT", "13", "38", "BYRADIUS", "10", "km"]
                        else:
                            args = ["GEORADIUS", source, "13", "38", "10", "km", verb, destination]
                        stored = call(args)
                        after_witness = route([source, destination])
                        # Migration invalidates only the route witness. Check every result
                        # before considering a fresh arm: a moved shard cannot excuse damage.
                        assert stored == b":2\r\n", stored
                        after_raw = call(["OBJECT", "FREQ", destination])
                        assert re.fullmatch(rb":[0-9]+\r\n", after_raw), after_raw
                        after = int(after_raw[1:-2])
                        encoding = call(["OBJECT", "ENCODING", destination])
                        # STORE may compact its new result; only GEOADD forbids demotion.
                        assert encoding == b"$8\r\nlistpack\r\n", encoding
                        assert after > initial, ("destination LFU reset", initial, before, after)
                        members = decoded(call(["ZRANGE", destination, "0", "-1"]))
                        assert isinstance(members, list) and sorted(members) == [b"a", b"b"], members
                        print("  CD13b GEO %s %s keys=%r route(sid,owner,migrations)=%r after_route=%r "
                              "initial=%d before=%d after=%d store=%r freq=%r encoding=%r members=%r" %
                              (label, verb, (source, destination), witness, after_witness, initial, before, after,
                               stored, after_raw, encoding, members))
                        assert time.monotonic() < deadline, "STORE checks exhausted window budget"
                        if after_witness == witness:
                            break
                        print("  CD13b GEO rearm %s %s attempt=%d: route moved during STORE" %
                              (label, verb, attempt))
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
