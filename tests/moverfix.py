#!/usr/bin/env python3
"""D2 donor conservation assertions, isolated from the unlanded EXEC branch.

G5 moves() and txn_movers.py assertions come from f7f3ce7a5. The original
T05 checks below retain N=2000/W=4 and both original conservation assertions.
Only endpoint/connection plumbing is adapted to an externally owned server.
"""
import argparse
import concurrent.futures
import threading
import time
import _lib


class Battery:
    def __init__(self, args):
        self.args = args
        self.connections = []
        self.admin = self.conn()
        self.serial = 0

    def conn(self, timeout=10, buffering=1 << 20):
        c = _lib.Conn(self.args.host, self.args.port, timeout=timeout, buffering=buffering)
        self.connections.append(c)
        return c

    def close(self):
        for c in self.connections:
            c.close()

    def atomic(self):
        return int(self.admin.must("CONFIG", "GET", "atomic")[1])

    def counter(self, name):
        # G5's atomic-1 diagnostics do not exist on the headline. They are read
        # but never asserted/used by this atomic-0-only extraction.
        return _lib.info(self.admin, "stats").get(name)

    def pair(self):
        self.serial += 1
        names = [f"moverfix:{time.time_ns()}:{self.serial}:{i}" for i in range(256)]
        geometry = self.admin.must("DEBUG", "SHARDS", *names)
        other = next((i for i in range(1, len(names))
                      if geometry[i][1] != geometry[0][1]), None)
        assert other is not None, "DEBUG SHARDS did not prove two owners"
        keys = [names[0], names[other]]
        assert self.admin.must("DEBUG", "SHARDS", *keys) == [geometry[0], geometry[other]]
        return keys

    @staticmethod
    def wait(predicate, label, timeout=.25):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(.001)
        raise AssertionError(label)

    def moves(self, kind, adders=False):
        src, dst = self.pair()
        count = 4000 if adders else 2000
        members = [f"m{i}".encode() for i in range(count)]
        for start in range(0, count, 500):
            self.admin.must("SADD" if kind == "smove" else "RPUSH", src,
                            *members[start:start + 500])
        before = {name: self.counter(name) for name in (
            "atomic_group_dooms", "atomic_group_retries", "atomic_group_wounds",
            "atomic_txn_blind_restarts", "atomic_txn_writer_waits")}
        deadline = time.monotonic() + 30

        def worker(index, add):
            c = self.conn(timeout=10)
            replies = []
            for i in range(index * (count // 4), (index + 1) * (count // 4)):
                assert time.monotonic() < deadline, "mover conservation deadline"
                if add:
                    reply = c.must("SADD", dst, f"z{i}")
                elif kind == "smove":
                    reply = c.must("SMOVE", src, dst, members[i])
                else:
                    reply = c.must("RPOPLPUSH", src, dst)
                valid = reply == 1 if add or kind == "smove" else isinstance(reply, bytes)
                assert valid, reply
                replies.append(reply)
            return replies

        with concurrent.futures.ThreadPoolExecutor(8 if adders else 4) as pool:
            moved = [pool.submit(worker, i, False) for i in range(4)]
            added = [pool.submit(worker, i, True) for i in range(4)] if adders else []
            deliveries = [value for future in moved for value in future.result(timeout=35)]
            for future in added:
                assert len(future.result(timeout=35)) == count // 4
        if kind == "smove":
            source = self.admin.must("SMEMBERS", src)
            destination = self.admin.must("SMEMBERS", dst)
        else:
            source = self.admin.must("LRANGE", src, 0, -1)
            destination = self.admin.must("LRANGE", dst, 0, -1)
            assert len(deliveries) == len(set(deliveries)) == count, "duplicate delivery"
        expected = set(members)
        if adders:
            expected.update(f"z{i}".encode() for i in range(count))
        assert not source and len(destination) == len(expected) and set(destination) == expected, (
            kind, len(source), len(destination), len(expected))
        if self.atomic():
            delta = {name: self.counter(name) - value for name, value in before.items()}
            assert delta["atomic_group_dooms"] == 0, delta
            assert delta["atomic_group_retries"] == (delta["atomic_group_wounds"] +
                                                     delta["atomic_txn_blind_restarts"]), delta
            assert self.counter("atomic_txn_order_violations") == 0
            print("group placement counters", delta, flush=True)
        print("conservation", kind, "atomic", self.atomic(), "members", len(expected), flush=True)


def t05(b, kind="rpoplpush", N=2000, W=4):
    c = b.admin
    src, dst = b.pair()
    which, atomic, mode = "tomo", "0", _lib.thread_mode(c)
    c.cmd("DEL", src, dst)
    for i in range(0, N, 500):
        batch = ["e%d" % j for j in range(i, min(N, i + 500))]
        c.cmd("SADD" if kind == "smove" else "RPUSH", src, *batch)
    acked = [0]; errs = []; popped = []
    lock = threading.Lock()
    def mover(lo, hi):
        x = b.conn(timeout=60)
        n = 0
        for j in range(lo, hi):
            r = x.cmd("SMOVE", src, dst, "e%d" % j) if kind == "smove" else x.cmd("RPOPLPUSH", src, dst)
            if (kind == "smove" and r == 1) or (kind != "smove" and isinstance(r, bytes)): n += 1
            elif isinstance(r, _lib.RespError): errs.append(r)
            if kind != "smove" and isinstance(r, bytes): popped.append(r)
        with lock: acked[0] += n
        x.close()
    step = N // W
    ts = [threading.Thread(target=mover, args=(w * step, (w + 1) * step)) for w in range(W)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    if kind == "smove":
        a, b = c.cmd("SCARD", src), c.cmd("SCARD", dst)
    else:
        a, b = c.cmd("LLEN", src), c.cmd("LLEN", dst)
    print("%s atomic=%s mode=%s %s N=%d W=%d: acked=%d  src=%d dst=%d  src+dst=%d (must be %d)  dst-vs-acked=%d  errors=%d %.1fs"
          % (which, atomic, mode, kind, N, W, acked[0], a, b, a + b, N, b - acked[0], len(errs), time.time() - t0))
    assert not errs and a + b == N and b == acked[0], "members lost or duplicated"
    assert len(popped) == len(set(popped)), "RPOPLPUSH duplicated a delivery"


def exec_moves(b):
    # Headline EXEC forces atomic children even at CONFIG atomic=0. Exercise
    # both the parent's own writes and simultaneous children from four clients.
    src, dst = b.pair()
    c = b.conn()
    c.must("MULTI")
    for command in (("RPUSH", src, "own1", "own2"),
                    ("LMOVE", src, dst, "LEFT", "RIGHT"),
                    ("LMPOP", 2, src, dst, "RIGHT", "COUNT", 3)):
        assert c.must(*command) == b"QUEUED"
    assert c.must("EXEC") == [2, b"own1", [src.encode(), [b"own2"]]]
    assert c.must("LRANGE", dst, 0, -1) == [b"own1"]
    for verb in ("RPOPLPUSH", "LMOVE", "LMPOP", "ZMPOP"):
        src, dst = b.pair()
        count = 2000
        expected = {str(i).encode() for i in range(count)}
        pop = verb in ("LMPOP", "ZMPOP")
        if verb == "ZMPOP":
            b.admin.must("ZADD", src, *[v for i in range(count) for v in (i, str(i))])
        else:
            b.admin.must("RPUSH", src, *sorted(expected))
        command = (verb, src, dst)
        if verb == "LMOVE":
            command += ("RIGHT", "LEFT")
        if pop:
            command = (verb, 2, src, dst, "MIN" if verb == "ZMPOP" else "LEFT", "COUNT", 3)
        clients = [b.conn(timeout=30) for _ in range(4)]
        start = threading.Barrier(4)
        def worker(client):
            start.wait()
            result = []
            for _ in range(count):
                assert client.must("MULTI") == b"OK"
                assert client.must(*command) == b"QUEUED"
                reply = client.must("EXEC")
                assert isinstance(reply, list) and len(reply) == 1, reply
                value = reply[0]
                if value is None:
                    return result
                if pop:
                    result.extend(value[1] if verb == "LMPOP" else [v[0] for v in value[1]])
                else:
                    assert isinstance(value, bytes), value
                    result.append(value)
            raise AssertionError("EXEC mover did not drain within bounded attempts")
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            delivered = [v for values in pool.map(worker, clients) for v in values]
        print("EXEC receipt", verb, "delivered", len(delivered), "unique", len(set(delivered)),
              "expected", count, "missing", len(expected - set(delivered)), flush=True)
        assert len(delivered) == len(set(delivered)) == count and set(delivered) == expected, (verb, "EXEC duplicate/loss")
        assert b.admin.must("EXISTS", src) == 0
        if not pop:
            destination = b.admin.must("LRANGE", dst, 0, -1)
            assert len(destination) == count and set(destination) == expected
        print("PASS EXEC", verb, "exact claimed deliveries", count, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("--only", choices=("T05", "G5", "EXEC"), required=True)
    args = p.parse_args()
    b = Battery(args)
    try:
        assert b.atomic() == 0, "D2 requires atomic 0"
        if args.only == "T05":
            t05(b)
        elif args.only == "EXEC":
            exec_moves(b)
        else:
            b.moves("smove", adders=True)
            b.moves("smove")
            b.moves("rpoplpush")
    finally:
        b.close()


if __name__ == "__main__":
    main()
