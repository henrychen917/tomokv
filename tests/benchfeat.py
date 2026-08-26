#!/usr/bin/env python3
"""Per-feature throughput cells that redis-benchmark cannot drive:
MULTI/EXEC transactions, BLPOP producer/consumer serves, pub/sub fanout delivery.
Usage: benchfeat.py HOST PORT {exec|blpop|fanout|sfanout} [seconds] [nsubs]"""
import socket, sys, threading, time

HOST, PORT, MODE = sys.argv[1], int(sys.argv[2]), sys.argv[3]
SECS = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
NSUBS = int(sys.argv[5]) if len(sys.argv) > 5 else 10


def enc(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        b = a if isinstance(a, bytes) else str(a).encode()
        out += b"$%d\r\n%s\r\n" % (len(b), b)
    return out


def conn():
    s = socket.create_connection((HOST, PORT), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def drain_replies(f, n):
    # Counts RESP top-level replies without full parsing: reads lines, tracks nesting via array
    # headers, skips bulk payloads exactly.
    seen = 0
    pending = 0
    while seen < n:
        line = f.readline()
        if not line:
            raise EOFError
        t = line[:1]
        if t == b"*":
            k = int(line[1:])
            pending += max(k, 0)
        elif t == b"$":
            k = int(line[1:])
            if k >= 0:
                f.read(k + 2)
        if pending > 0:
            pending -= 1
            if pending == 0:
                seen += 1
        elif t != b"*":
            seen += 1
    return seen


def run_exec():
    # 10-op transactions (MULTI + 5 SET + 5 GET + EXEC), batched 64 txns per write, 8 threads.
    BATCH, THREADS = 64, 8
    done = []
    stop = time.monotonic() + SECS

    def worker(tid):
        s = conn(); f = s.makefile("rb")
        txns = 0
        one = b""
        for t in range(BATCH):
            one += enc("MULTI")
            for i in range(5):
                one += enc("SET", "bf:x:%d:%d" % (tid, i), "v" * 32)
                one += enc("GET", "bf:x:%d:%d" % (tid, i))
            one += enc("EXEC")
        while time.monotonic() < stop:
            s.sendall(one)
            drain_replies(f, BATCH * 12)
            txns += BATCH
        done.append(txns)
        s.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    t0 = time.monotonic()
    for t in ts: t.start()
    for t in ts: t.join()
    dt = time.monotonic() - t0
    total = sum(done)
    print("EXEC txns/s: %.0f  (ops/s incl MULTI/EXEC frames: %.0f)" % (total / dt, total * 12 / dt))


def run_blpop():
    # 16 parked consumers, 4 producers pushing batches; rate = served pops/s.
    CONS, PRODS, BATCH = 16, 4, 128
    served = []
    pushed = []
    stop = time.monotonic() + SECS

    def consumer(cid):
        s = conn(); f = s.makefile("rb")
        n = 0
        s.settimeout(SECS + 5)
        try:
            while True:
                s.sendall(enc("BLPOP", "bf:q:%d" % (cid % PRODS), 1))
                line = f.readline()
                if line[:1] == b"*":
                    k = int(line[1:])
                    if k == -1:
                        if time.monotonic() > stop: break
                        continue
                    for _ in range(k):
                        l2 = f.readline()
                        if l2[:1] == b"$":
                            f.read(int(l2[1:]) + 2)
                    n += 1
                elif line[:1] == b"$" and int(line[1:]) == -1:
                    if time.monotonic() > stop: break
        except (socket.timeout, EOFError, OSError):
            pass
        served.append(n)

    def producer(pid):
        s = conn(); f = s.makefile("rb")
        n = 0
        batch = b"".join(enc("LPUSH", "bf:q:%d" % pid, "payload-%d" % i) for i in range(BATCH))
        while time.monotonic() < stop:
            s.sendall(batch)
            drain_replies(f, BATCH)
            n += BATCH
        pushed.append(n)
        s.close()

    cs = [threading.Thread(target=consumer, args=(i,)) for i in range(CONS)]
    ps = [threading.Thread(target=producer, args=(i,)) for i in range(PRODS)]
    t0 = time.monotonic()
    for t in cs + ps: t.start()
    for t in ps: t.join()
    for t in cs: t.join(SECS + 6)
    dt = time.monotonic() - t0
    print("BLPOP served/s: %.0f  (pushed/s: %.0f, consumers %d)" %
          (sum(served) / dt, sum(pushed) / dt, CONS))


def run_fanout(shard):
    # NSUBS subscribers on one channel; 1 pipelined publisher; measure publish and delivery rates.
    sub_cmd = "ssubscribe" if shard else "subscribe"
    pub_cmd = "SPUBLISH" if shard else "PUBLISH"
    chan = "bf:chan"
    counts = []
    ready = threading.Barrier(NSUBS + 1)
    stop_flag = threading.Event()

    def subscriber():
        s = conn(); f = s.makefile("rb")
        s.sendall(enc(sub_cmd, chan))
        f.readline(); f.readline(); f.read(len(sub_cmd) + 2)
        f.readline(); f.read(len(chan) + 2); f.readline()
        ready.wait()
        n = 0
        s.settimeout(2.0)
        try:
            while not stop_flag.is_set():
                line = f.readline()
                if not line: break
                if line[:1] == b"*":
                    k = int(line[1:])
                    for _ in range(k):
                        l2 = f.readline()
                        if l2[:1] == b"$":
                            f.read(int(l2[1:]) + 2)
                    n += 1
        except (socket.timeout, OSError):
            pass
        counts.append(n)

    subs = [threading.Thread(target=subscriber) for _ in range(NSUBS)]
    for t in subs: t.start()
    ready.wait()
    s = conn(); f = s.makefile("rb")
    BATCH = 256
    batch = b"".join(enc(pub_cmd, chan, "m" * 64) for _ in range(BATCH))
    published = 0
    t0 = time.monotonic()
    stop = t0 + SECS
    while time.monotonic() < stop:
        s.sendall(batch)
        drain_replies(f, BATCH)
        published += BATCH
    dt = time.monotonic() - t0
    time.sleep(1.5)
    stop_flag.set()
    for t in subs: t.join(4)
    delivered = sum(counts)
    print("%s publish/s: %.0f  delivery/s: %.0f  (subs %d, delivered %.1f%% of ideal)" %
          (pub_cmd, published / dt, delivered / dt, NSUBS,
           100.0 * delivered / (published * NSUBS) if published else 0.0))


if MODE == "exec": run_exec()
elif MODE == "blpop": run_blpop()
elif MODE == "fanout": run_fanout(False)
elif MODE == "sfanout": run_fanout(True)
else: sys.exit("unknown mode")
