#!/usr/bin/env python3
# Prototype: deterministic EXEC fan-out straddle via DEBUG ATOMIC-FANOUT-DEFER.
import socket, sys, time

HOST, PORT = sys.argv[1], int(sys.argv[2])
HOLD_US = int(sys.argv[3]) if len(sys.argv) > 3 else 300000
ROUNDS = int(sys.argv[4]) if len(sys.argv) > 4 else 10

def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str): a = a.encode()
        out += [b"$%d\r\n" % len(a), a, b"\r\n"]
    return b"".join(out)

class Resp:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=60)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.s.makefile("rb")
    def send(self, *a): self.s.sendall(enc(*a))
    def cmd(self, *a): self.send(*a); return self.read()
    def read(self):
        p = self.f.read(1)
        if not p: raise EOFError
        line = self.f.readline()[:-2]
        if p == b"+": return line
        if p == b"-": return Exception(line.decode())
        if p == b":": return int(line)
        if p == b"$":
            n = int(line)
            if n == -1: return None
            v = self.f.read(n); self.f.read(2); return v
        if p == b"*":
            n = int(line)
            if n == -1: return None
            return [self.read() for _ in range(n)]
        raise AssertionError(p)
    def close(self):
        try: self.f.close(); self.s.close()
        except Exception: pass

admin = Resp()

# geometry oracle: pick 8 keys that really do land on distinct owners
picked, seen = [], set()
i = 0
while len(picked) < 8 and i < 4000:
    k = "fanout:%d" % i
    sh = admin.cmd("DEBUG", "SHARD", k)
    if sh not in seen:
        seen.add(sh); picked.append(k)
    i += 1
print("keys=%r shards=%r" % (picked, sorted(seen)))
assert len(seen) >= 2, "keys did not span owners"

def info(field):
    txt = admin.cmd("INFO", "stats").decode()
    for line in txt.split("\r\n"):
        if line.startswith(field + ":"): return int(line.split(":", 1)[1])
    return None

torn = 0
for r in range(ROUNDS):
    for k in picked: admin.cmd("SET", k, "0")
    assert admin.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", str(HOLD_US)) == b"OK"
    reader = Resp()
    reader.send("MGET", *picked)
    time.sleep(0.05)                      # lead fragment has answered; the rest are parked
    writer = Resp()
    assert writer.cmd("MULTI") == b"OK"
    for k in picked: assert writer.cmd("SET", k, "1") == b"QUEUED"
    ex = writer.cmd("EXEC")
    assert ex == [b"OK"] * len(picked), ex
    writer.close()
    values = reader.read()
    reader.close()
    admin.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", "0")
    ok = values and all(v == values[0] for v in values[1:])
    if not ok: torn += 1
    print("  round %2d %s %r" % (r, "ok  " if ok else "TORN", values))

print("fanout_cuts=%s read_cuts_held=%s" % (info("atomic_fanout_cuts"), info("atomic_read_cuts_held")))
print("FANOUT PROTO: %d/%d rounds torn" % (torn, ROUNDS))
sys.exit(1 if torn else 0)
