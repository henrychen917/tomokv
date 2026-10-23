#!/usr/bin/env python3
"""CC4.13/14/16 directed stream regression checks against the live 7.4 oracle."""
from compat3_lib import equal, run
from _lib import RespError


def setup(c):
    for i in range(1, 4):
        equal(c.cmd("XADD", "s", f"{i}-0", "f", f"v{i}"), f"{i}-0".encode(), "XADD")
    equal(c.cmd("XGROUP", "CREATE", "s", "g", "0"), b"OK", "group")


def pending(c, *args):
    rows = c.cmd("XPENDING", "s", "g", *args)
    if isinstance(rows, RespError):
        return rows
    for row in rows:
        assert isinstance(row[2], int) and row[2] >= 0, row
    # Idle is the only time-dependent field; owner, ID and deliveries remain exact.
    return [[row[0], row[1], row[3]] for row in rows]


def probe(c, case):
    setup(c)
    if case == "pending":
        for consumer in (b"", b"c", b"c\x00tail"):
            reply = c.cmd("XREADGROUP", "GROUP", "g", consumer, "COUNT", 1, "STREAMS", "s", ">")
            assert isinstance(reply, list) and len(reply[0][1]) == 1, reply
        return {"all": pending(c, "-", "+", 10),
                "empty": pending(c, "-", "+", 10, b""),
                "named": pending(c, "-", "+", 10, "c"),
                "binary": pending(c, "-", "+", 10, b"c\x00tail"),
                "absent": pending(c, "-", "+", 10, "missing"),
                "idle-empty": pending(c, "IDLE", 0, "-", "+", 10, b"")}
    if case == "history":
        new = c.cmd("XREADGROUP", "GROUP", "g", "c", "COUNT", 0, "STREAMS", "s", ">")
        equal(len(new[0][1]), 3, "COUNT 0 new entries")
        equal(c.cmd("XDEL", "s", "2-0"), 1, "pending tombstone")
        out = {"new": new}
        for count in (None, 0, 1, 2, 100):
            command = ["XREADGROUP", "GROUP", "g", "c"]
            if count is not None:
                command += ["COUNT", count]
            out[str(count)] = c.cmd(*command, "STREAMS", "s", "0")
        out["other"] = c.cmd("XREADGROUP", "GROUP", "g", "other", "COUNT", 0, "STREAMS", "s", "0")
        return out
    # The two audited option sites: signed/clamped min-idle and canonical ENTRIESREAD.
    c.cmd("XREADGROUP", "GROUP", "g", "c", "STREAMS", "s", ">")
    out = {}
    values = ("-9223372036854775808", "-1", "0", "1", "9223372036854775807",
              "01", "-0", "+1", " 1", "1 ", "", "1\x00", "9223372036854775808",
              "-9223372036854775809")
    for value in values:
        out["claim:" + value] = c.cmd("XCLAIM", "s", "g", "c2", value, "1-0" if value.startswith("-") or value == "0" else "999-0", "JUSTID")
        out["setid:" + value] = c.cmd("XGROUP", "SETID", "s", "g", "0", "ENTRIESREAD", value)
        group = "create" + str(len(out))
        out["create:" + value] = c.cmd("XGROUP", "CREATE", "s", group, "0", "ENTRIESREAD", value)
    return out


if __name__ == "__main__":
    run(probe, ("pending", "history", "grammar"))
