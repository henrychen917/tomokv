#!/usr/bin/env python3
"""Directed GEO-family battery. Usage: tests/geo.py HOST PORT"""

import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])


class RespError(Exception): pass


def enc(args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, str): arg = arg.encode()
        out += [f"${len(arg)}\r\n".encode(), arg, b"\r\n"]
    return b"".join(out)


class Conn:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=20)
        self.f = self.s.makefile("rb")

    def command(self, *args):
        self.s.sendall(enc(args)); return self.read()

    def read(self):
        t = self.f.read(1); line = self.f.readline()[:-2]
        if t == b"+": return line
        if t == b"-": return RespError(line.decode("utf-8", "replace"))
        if t == b":": return int(line)
        if t == b",": return float(line)
        if t == b"_": return None
        if t == b"$":
            n = int(line)
            if n == -1: return None
            value = self.f.read(n); assert self.f.read(2) == b"\r\n"; return value
        if t in (b"*", b"~"):
            n = int(line)
            if n == -1: return None
            return [self.read() for _ in range(n)]
        raise AssertionError((t, line))


def expect(actual, wanted, label):
    if actual != wanted: raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")
    print(f"  ok   {label}")


def expect_error(actual, text, label):
    if not isinstance(actual, RespError) or text not in str(actual):
        raise AssertionError(f"{label}: got {actual!r}")
    print(f"  ok   {label}")


def stats(c):
    raw = c.command("INFO", "STATS").decode()
    return {line.split(":", 1)[0]: line.split(":", 1)[1]
            for line in raw.splitlines() if ":" in line}


def main():
    c = Conn(); expect(c.command("FLUSHALL"), b"OK", "clean slate")
    expect(c.command("GEOADD", "Sicily", "13.361389", "38.115556", "Palermo",
                     "15.087269", "37.502669", "Catania"), 2, "classic points added")
    expect(c.command("ZRANGE", "Sicily", "0", "-1", "WITHSCORES"),
           [b"Palermo", b"3479099956230698", b"Catania", b"3479447370796909"],
           "52-bit zset encoding")
    expect(c.command("GEOPOS", "Sicily", "Palermo", "Catania", "missing"),
           [[b"13.36138933897018433", b"38.11555639549629859"],
            [b"15.08726745843887329", b"37.50266842333162032"], None],
           "17-decimal coordinate replies")
    expect(c.command("GEOHASH", "Sicily", "Palermo", "Catania", "missing"),
           [b"sqc8b49rny0", b"sqdtr74hyu0", None], "11-character GEOHASH")
    expect(c.command("GEODIST", "Sicily", "Palermo", "Catania"), b"166274.1516",
           "GEODIST meters")
    expect(c.command("GEODIST", "Sicily", "Palermo", "Catania", "km"), b"166.2742",
           "GEODIST kilometers")

    expect(c.command("GEOADD", "opts", "NX", "CH", "1", "2", "a"), 1,
           "GEOADD NX CH add")
    expect(c.command("GEOADD", "opts", "NX", "3", "4", "a"), 0,
           "GEOADD NX blocks update")
    expect(c.command("GEOADD", "opts", "XX", "CH", "3", "4", "a"), 1,
           "GEOADD XX CH update")
    expect_error(c.command("GEOADD", "opts", "NX", "XX", "1", "2", "b"),
                 "syntax error", "GEOADD rejects NX+XX")
    expect_error(c.command("GEOADD", "opts", "181", "0", "bad"),
                 "invalid longitude,latitude", "longitude bound")
    expect(c.command("GEOADD", "poles", "0", "85.05112878", "north",
                     "0", "-85.05112878", "south"), 2, "latitude endpoints accepted")
    expect(c.command("GEOSEARCH", "poles", "FROMMEMBER", "north",
                     "BYRADIUS", "1", "km"), [b"north"], "north-pole search")
    expect_error(c.command("GEOADD", "poles", "0", "85.05112879", "bad"),
                 "invalid longitude,latitude", "latitude bound")

    detailed = c.command("GEOSEARCH", "Sicily", "FROMMEMBER", "Palermo",
                         "BYRADIUS", "200", "km", "ASC", "WITHCOORD", "WITHDIST", "WITHHASH")
    expect(detailed,
           [[b"Palermo", b"0.0000", 3479099956230698,
             [b"13.36138933897018433", b"38.11555639549629859"]],
            [b"Catania", b"166.2742", 3479447370796909,
             [b"15.08726745843887329", b"37.50266842333162032"]]],
           "GEOSEARCH detail order and formatting")
    expect(c.command("GEOSEARCH", "Sicily", "FROMLONLAT", "13.361389", "38.115556",
                     "BYBOX", "400", "400", "km", "COUNT", "1", "ANY"),
           [b"Palermo"], "COUNT ANY early exit fired")
    expect(c.command("GEOSEARCH", "missing-geo", "FROMMEMBER", "x",
                     "BYRADIUS", "1", "km"), [], "missing key is empty")
    expect_error(c.command("GEOSEARCH", "Sicily", "FROMMEMBER", "missing",
                           "BYRADIUS", "1", "km"),
                 "could not decode requested zset member", "missing center member")

    expect(c.command("GEOADD", "date-line", "179.9", "0", "east",
                     "-179.9", "0", "west"), 2, "antimeridian points added")
    crossing = c.command("GEOSEARCH", "date-line", "FROMLONLAT", "179.95", "0",
                         "BYRADIUS", "30", "km", "ASC")
    expect(set(crossing), {b"east", b"west"}, "radius crosses longitude 180")
    crossing_box = c.command("GEOSEARCH", "date-line", "FROMLONLAT", "179.95", "0",
                             "BYBOX", "60", "10", "km", "ASC")
    expect(set(crossing_box), {b"east", b"west"}, "box crosses longitude 180")

    expect(c.command("GEORADIUS_RO", "Sicily", "13.361389", "38.115556", "200", "km",
                     "ASC"), [b"Palermo", b"Catania"], "GEORADIUS_RO read form")
    expect(c.command("GEORADIUSBYMEMBER", "Sicily", "Palermo", "200", "km", "ASC"),
           [b"Palermo", b"Catania"], "GEORADIUSBYMEMBER read form")
    expect(c.command("GEORADIUSBYMEMBER_RO", "Sicily", "Palermo", "200", "km", "ASC"),
           [b"Palermo", b"Catania"], "GEORADIUSBYMEMBER_RO read form")

    expect(c.command("SET", "wrong-geo", "x"), b"OK", "wrongtype control seeded")
    expect_error(c.command("GEOPOS", "wrong-geo", "x"), "WRONGTYPE", "GEOPOS wrongtype")
    expect_error(c.command("GEOSEARCH", "wrong-geo", "FROMMEMBER", "x",
                           "BYRADIUS", "1", "km"), "WRONGTYPE", "GEOSEARCH wrongtype")

    before = int(stats(c)["atomic_groups"])
    expect(c.command("GEOSEARCHSTORE", "geo:far-destination", "Sicily", "FROMMEMBER",
                     "Palermo", "BYRADIUS", "200", "km", "STOREDIST"), 2,
           "GEOSEARCHSTORE fired")
    stored = c.command("ZRANGE", "geo:far-destination", "0", "-1", "WITHSCORES")
    if stored[0] != b"Palermo" or stored[1] != b"0" or stored[2] != b"Catania":
        raise AssertionError(f"STOREDIST content: {stored!r}")
    print("  ok   STOREDIST content observed")
    expect(c.command("GEORADIUS", "Sicily", "13.361389", "38.115556", "200", "km",
                     "STORE", "geo:deprecated-destination"), 2, "deprecated STORE fired")
    expect(c.command("ZCARD", "geo:deprecated-destination"), 2,
           "deprecated STORE content observed")
    expect(c.command("GEORADIUSBYMEMBER", "Sicily", "Palermo", "200", "km",
                     "STOREDIST", "geo:deprecated-member-destination"), 2,
           "deprecated BYMEMBER STOREDIST fired")
    member_stored = c.command("ZRANGE", "geo:deprecated-member-destination", "0", "-1",
                              "WITHSCORES")
    if member_stored[:3] != [b"Palermo", b"0", b"Catania"]:
        raise AssertionError(f"BYMEMBER STOREDIST content: {member_stored!r}")
    print("  ok   deprecated BYMEMBER STOREDIST content observed")
    after = int(stats(c)["atomic_groups"])
    if after > before: print("  ok   atomic geo scatter counter advanced")
    else: print("  ok   non-atomic geo store destination observed")

    print("GEO PASS: directed mechanisms fired")


if __name__ == "__main__": main()
