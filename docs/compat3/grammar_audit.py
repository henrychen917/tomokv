#!/usr/bin/env python3
"""Inventory only: numeric stream option acceptance/errors, on fresh state per input.
Consumes already-owned endpoints; never changes production or expected gate assertions.
"""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn, RespError
from compat3_lib import wire

VALUES = ("-9223372036854775809", "-9223372036854775808", "-2", "-1", "-0", "0", "00", "01", "+1", "1", "2", " 1", "1 ", "1\x00", "1.0", "", "9223372036854775807", "9223372036854775808", "18446744073709551615")
OPTIONS = {
    "XADD MAXLEN": lambda x: ["XADD","s","MAXLEN",x,"4-0","f","v"],
    "XADD LIMIT": lambda x: ["XADD","s","MAXLEN","~",1,"LIMIT",x,"4-0","f","v"],
    "XTRIM MAXLEN": lambda x: ["XTRIM","s","MAXLEN",x],
    "XTRIM LIMIT": lambda x: ["XTRIM","s","MAXLEN","~",1,"LIMIT",x],
    "XRANGE COUNT": lambda x: ["XRANGE","s","-","+","COUNT",x],
    "XREVRANGE COUNT": lambda x: ["XREVRANGE","s","+","-","COUNT",x],
    "XREAD COUNT": lambda x: ["XREAD","COUNT",x,"STREAMS","s",0],
    "XREAD BLOCK": lambda x: ["XREAD","BLOCK",x,"STREAMS","s",0],
    "XREADGROUP COUNT": lambda x: ["XREADGROUP","GROUP","g","c","COUNT",x,"STREAMS","s",0],
    "XREADGROUP BLOCK": lambda x: ["XREADGROUP","GROUP","g","c","BLOCK",x,"STREAMS","s",0],
    "XPENDING IDLE": lambda x: ["XPENDING","s","g","IDLE",x,"-","+",10],
    "XPENDING COUNT": lambda x: ["XPENDING","s","g","-","+",x],
    "XCLAIM min-idle": lambda x: ["XCLAIM","s","g","c2",x,"1-0","JUSTID"],
    "XCLAIM IDLE": lambda x: ["XCLAIM","s","g","c2",0,"1-0","IDLE",x,"JUSTID"],
    "XCLAIM TIME": lambda x: ["XCLAIM","s","g","c2",0,"1-0","TIME",x,"JUSTID"],
    "XCLAIM RETRYCOUNT": lambda x: ["XCLAIM","s","g","c2",0,"1-0","RETRYCOUNT",x,"JUSTID"],
    "XAUTOCLAIM min-idle": lambda x: ["XAUTOCLAIM","s","g","c2",x,0,"JUSTID"],
    "XAUTOCLAIM COUNT": lambda x: ["XAUTOCLAIM","s","g","c2",0,0,"COUNT",x,"JUSTID"],
    "XGROUP CREATE ENTRIESREAD": lambda x: ["XGROUP","CREATE","s","g2",0,"ENTRIESREAD",x],
    "XGROUP SETID ENTRIESREAD": lambda x: ["XGROUP","SETID","s","g",0,"ENTRIESREAD",x],
    "XSETID ENTRIESADDED": lambda x: ["XSETID","s","3-0","ENTRIESADDED",x],
    "XINFO FULL COUNT": lambda x: ["XINFO","STREAM","s","FULL","COUNT",x],
}
REPEATS = [
    ["XADD","s","MAXLEN",10,"MAXLEN",2,"4-0","f","v"],
    ["XTRIM","s","MAXLEN",10,"MAXLEN",2],
    ["XRANGE","s","-","+","COUNT",1,"COUNT",2],
    ["XREAD","COUNT",1,"COUNT",2,"STREAMS","s",0],
    ["XREAD","BLOCK",0,"BLOCK",1,"STREAMS","s",0],
    ["XREADGROUP","GROUP","g","c","COUNT",1,"COUNT",2,"STREAMS","s",0],
    ["XREADGROUP","GROUP","g","c","BLOCK",0,"BLOCK",1,"STREAMS","s",0],
    ["XCLAIM","s","g","c2",0,"1-0","IDLE",0,"IDLE",1,"JUSTID"],
    ["XCLAIM","s","g","c2",0,"1-0","TIME",0,"TIME",1,"JUSTID"],
    ["XCLAIM","s","g","c2",0,"1-0","RETRYCOUNT",1,"RETRYCOUNT",2,"JUSTID"],
    ["XAUTOCLAIM","s","g","c2",0,0,"COUNT",1,"COUNT",2,"JUSTID"],
    ["XGROUP","CREATE","s","g2",0,"ENTRIESREAD",1,"ENTRIESREAD",2],
    ["XGROUP","SETID","s","g",0,"ENTRIESREAD",1,"ENTRIESREAD",2],
    ["XSETID","s","3-0","ENTRIESADDED",4,"ENTRIESADDED",5],
    ["XINFO","STREAM","s","FULL","COUNT",1,"COUNT",2],
    ["XADD","s","NOMKSTREAM","NOMKSTREAM","4-0","f","v"],
    ["XGROUP","CREATE","s","g2",0,"MKSTREAM","MKSTREAM"],
    ["XCLAIM","s","g","c2",0,"1-0","FORCE","FORCE","JUSTID"],
    ["XCLAIM","s","g","c2",0,"1-0","JUSTID","JUSTID"],
    ["XAUTOCLAIM","s","g","c2",0,0,"JUSTID","JUSTID"],
    ["XREADGROUP","GROUP","g","c","NOACK","NOACK","STREAMS","s",0],
    ["XREADGROUP","GROUP","g","c","GROUP","g","c","STREAMS","s",0],
]

ID_VALUES = ("0", "+0", "00", "-0", "1", "01", "1-0", "1-01", "1-+1", "1--1", "1-", "-", "+", "(1-0", "18446744073709551615-18446744073709551615", "18446744073709551616-0", "1\x00")
ID_OPTIONS = {
    "XADD MINID": lambda x: ["XADD","s","MINID",x,"4-0","f","v"],
    "XTRIM MINID": lambda x: ["XTRIM","s","MINID",x],
    "XCLAIM LASTID": lambda x: ["XCLAIM","s","g","c2",0,"1-0","LASTID",x,"JUSTID"],
    "XSETID MAXDELETEDID": lambda x: ["XSETID","s","3-0","MAXDELETEDID",x],
}


def setup(c):
    assert c.cmd("FLUSHALL") == b"OK"
    for i in range(1,4):
        assert c.cmd("XADD","s",f"{i}-0","f","v") == f"{i}-0".encode()
    assert c.cmd("XGROUP","CREATE","s","g",0) == b"OK"
    assert len(c.cmd("XREADGROUP","GROUP","g","c","STREAMS","s",">")[0][1]) == 3


def main():
    oracle, target = [Conn("127.0.0.1", p, timeout=5) for p in sys.argv[1:3]]
    results=[]
    try:
        for name, value, cmd in [(n,x,f(x)) for n,f in OPTIONS.items() for x in VALUES] + [(n,x,f(x)) for n,f in ID_OPTIONS.items() for x in ID_VALUES] + [("duplicate",str(i),cmd) for i,cmd in enumerate(REPEATS)]:
            replies=[]
            for c in (oracle,target):
                setup(c); replies.append(c.cmd(*cmd))
            outcomes=[r.message.decode() if isinstance(r,RespError) else "accepted" for r in replies]
            results.append(dict(option=name,value=value,command=cmd,oracle=wire(replies[0]),target=wire(replies[1]),outcomes=outcomes,difference=outcomes[0]!=outcomes[1]))
        Path(sys.argv[3]).write_text(json.dumps(results,indent=2)+"\n")
        for row in results:
            if row["difference"]:
                print(row["option"],repr(row["value"]),row["outcomes"])
        print("checked",len(results),"differences",sum(r["difference"] for r in results))
    finally:
        oracle.close();target.close()


if __name__ == "__main__": main()
