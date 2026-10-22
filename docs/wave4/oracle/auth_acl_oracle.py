#!/usr/bin/env python3
"""Replay the exact sequences behind wave 4's three corrected assertions on one server and
write every reply as JSON (evidence only; no assertion here).

  auth_acl_oracle.py auth HOST PORT PASSWORD OUT.json   # server booted with requirepass PASSWORD
  auth_acl_oracle.py acl  HOST PORT OUT.json            # server booted with an empty --aclfile
  auth_acl_oracle.py compare REDIS.json TOMO.json       # byte comparison per probe label
"""
import json
import socket
import sys


def frame(*args):
    values = [a if isinstance(a, bytes) else str(a).encode() for a in args]
    return b"*%d\r\n" % len(values) + b"".join(b"$%d\r\n%s\r\n" % (len(v), v) for v in values)


class Conn:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()

    def read(self):
        kind, line = self.file.read(1), self.file.readline()[:-2]
        if kind == b"+":
            return {"simple": line.decode("latin-1")}
        if kind == b"-":
            return {"error": line.decode("latin-1")}
        if kind == b":":
            return int(line)
        if kind == b"$":
            size = int(line)
            if size < 0:
                return None
            data = self.file.read(size)
            self.file.read(2)
            return data.decode("latin-1")
        if kind == b"*":
            size = int(line)
            return None if size < 0 else [self.read() for _ in range(size)]
        raise ValueError("unexpected RESP prefix %r" % kind)

    def close(self):
        self.file.close()
        self.sock.close()


def server_identity(conn):
    info = conn.command("INFO", "SERVER")
    return {k: v for k, v in (line.split(":", 1) for line in info.split("\r\n") if ":" in line)
            if k in ("redis_version", "redis_git_sha1", "tomokv_version", "executable")}


def auth_sequences(host, port, password):
    admin = Conn(host, port)
    rows = [{"label": "admin AUTH", "argv": ["AUTH", "<password>"], "reply": admin.command("AUTH", password)}]
    identity = server_identity(admin)
    registry = admin.command("COMMAND")
    unauth = Conn(host, port)
    for label, argv in (("unauthenticated PING", ["PING"]),
                        ("XGROUP x (auth.py line 126)", ["XGROUP", "x"]),
                        ("XGROUP CREATE key group (auth.py line 128)", ["XGROUP", "CREATE", "key", "group"]),
                        ("AUTH a b c (auth.py line 131)", ["AUTH", "a", "b", "c"])):
        rows.append({"label": label, "argv": argv, "reply": unauth.command(*argv)})
    unauth.close()
    for info in registry:
        name, arity = info[0], abs(info[1])
        argv = [name] + ["x"] * (arity - 1)
        probe = Conn(host, port)
        rows.append({"label": "pre-auth registry %s" % name, "argv": argv, "reply": probe.command(*argv),
                     "subcommands": len(info[9]) if len(info) > 9 and info[9] else 0})
        probe.close()
    admin.close()
    return identity, rows


def acl_sequences(host, port):
    admin = Conn(host, port)
    identity = server_identity(admin)
    password = b"s3cr\x00et"
    rules = ["on", b">" + password, "resetkeys", "~*", "resetchannels", "&news.*",
             "-@all", "+get", "+set", "+mget", "+mset", "+multi", "+exec",
             "+blpop", "+lpush", "+subscribe", "+unsubscribe", "+psubscribe",
             "+punsubscribe", "+ssubscribe", "+sunsubscribe", "+publish", "+spublish",
             "+eval", "+evalsha"]
    rows = [{"label": "ACL SETUSER alice (acl.py line 175 rules)", "argv": ["ACL", "SETUSER", "alice", "<rules>"],
             "reply": admin.command("ACL", "SETUSER", "alice", *rules)}]
    alice = Conn(host, port)
    rows.append({"label": "alice AUTH", "argv": ["AUTH", "alice", "<password>"],
                 "reply": alice.command("AUTH", "alice", password)})
    rows.append({"label": "alice ACL WHOAMI (acl.py line 208)", "argv": ["ACL", "WHOAMI"],
                 "reply": alice.command("ACL", "WHOAMI")})
    rows.append({"label": "alice ACL LIST (subcommand fullname control)", "argv": ["ACL", "LIST"],
                 "reply": alice.command("ACL", "LIST")})
    rows.append({"label": "alice CONFIG GET maxmemory (subcommand fullname control)",
                 "argv": ["CONFIG", "GET", "maxmemory"], "reply": alice.command("CONFIG", "GET", "maxmemory")})
    rows.append({"label": "alice DBSIZE (top-level name control)", "argv": ["DBSIZE"],
                 "reply": alice.command("DBSIZE")})
    admin.command("ACL", "DELUSER", "alice")
    alice.close()
    admin.close()
    return identity, rows


def main():
    mode = sys.argv[1]
    if mode == "compare":
        redis, tomo = (json.load(open(path)) for path in sys.argv[2:4])
        tomo_rows = {row["label"]: row for row in tomo["rows"]}
        same = differ = 0
        for row in redis["rows"]:
            other = tomo_rows.get(row["label"])
            if other is None:
                print("REDIS-ONLY  %-58s %r" % (row["label"], row["reply"]))
                continue
            if other["reply"] == row["reply"]:
                same += 1
            else:
                differ += 1
                print("DIFFERENT   %-58s redis=%r tomokv=%r" % (row["label"], row["reply"], other["reply"]))
        redis_labels = {row["label"] for row in redis["rows"]}
        for row in tomo["rows"]:
            if row["label"] not in redis_labels:
                print("TOMOKV-ONLY %-58s %r" % (row["label"], row["reply"]))
        print("identical replies: %d, different: %d" % (same, differ))
        return
    host, port = sys.argv[2], int(sys.argv[3])
    if mode == "auth":
        identity, rows = auth_sequences(host, port, sys.argv[4].encode())
        out = sys.argv[5]
    else:
        identity, rows = acl_sequences(host, port)
        out = sys.argv[4]
    with open(out, "w") as handle:
        json.dump({"server": identity, "rows": rows}, handle, indent=1, sort_keys=True)
    print("%s: %d rows" % (out, len(rows)))


if __name__ == "__main__":
    main()
