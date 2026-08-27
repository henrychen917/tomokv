#!/usr/bin/env python3
# Does a cross-shard read INSIDE a transaction straddle a foreign transaction's ticket?
# Reader: MULTI / MGET k0..k7 / EXEC.  Writer: MULTI / SET k0..k7 seq / EXEC.
import socket, sys, threading, time

HOST, PORT, ROUNDS = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
SECONDS = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0

def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str): a = a.encode()
        out += [b"$%d\r\n" % len(a), a, b"\r\n"]
    return b"".join(out)

class Resp:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=30)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.s.makefile("rb")
    def cmd(self, *a):
        self.s.sendall(enc(*a)); return self.read()
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

keys = ["inexec:%d" % i for i in range(8)]

def one_round():
    init = Resp()
    for k in keys: init.cmd("SET", k, "0")
    init.close()
    stop = threading.Event(); start = threading.Barrier(5); lock = threading.Lock()
    errors = []; state = {"torn": 0, "reads": 0, "commits": 0}
    def writer():
        c = Resp(); seq = 1
        try:
            start.wait()
            while not stop.is_set():
                assert c.cmd("MULTI") == b"OK"
                for k in keys: assert c.cmd("SET", k, str(seq)) == b"QUEUED"
                r = c.cmd("EXEC")
                assert r == [b"OK"] * len(keys), r
                state["commits"] += 1; seq += 1
        except Exception as e:
            with lock: errors.append("writer:%s" % e)
        finally: c.close()
    def reader(rid):
        c = Resp()
        try:
            start.wait()
            while not stop.is_set():
                assert c.cmd("MULTI") == b"OK"
                assert c.cmd("MGET", *keys) == b"QUEUED"
                r = c.cmd("EXEC")
                v = r[0] if isinstance(r, list) and r else None
                with lock:
                    state["reads"] += 1
                    if not v or any(x != v[0] for x in v[1:]):
                        state["torn"] += 1
                        if state["torn"] <= 2: errors.append("TORN %r" % (v,))
        except Exception as e:
            with lock: errors.append("reader%d:%s" % (rid, e))
        finally: c.close()
    th = [threading.Thread(target=writer)] + [threading.Thread(target=reader, args=(i,)) for i in range(4)]
    for t in th: t.start()
    time.sleep(SECONDS); stop.set()
    for t in th: t.join(35)
    return state, errors

bad = 0
for r in range(ROUNDS):
    st, errs = one_round()
    if st["torn"]: bad += 1
    print("  %s round %2d reads=%d commits=%d torn=%d %s" %
          ("TORN" if st["torn"] else "ok  ", r, st["reads"], st["commits"], st["torn"], errs[:2]),
          flush=True)
print("INEXEC PROBE: %d/%d rounds torn" % (bad, ROUNDS))
sys.exit(1 if bad else 0)
