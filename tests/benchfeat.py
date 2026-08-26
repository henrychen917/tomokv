#!/usr/bin/env python3
"""Per-feature throughput cells that redis-benchmark cannot drive:
MULTI/EXEC transactions, BLPOP producer/consumer serves, pub/sub fanout delivery.
Usage: benchfeat.py HOST PORT {exec|blpop|fanout|sfanout} [seconds] [nsubs] [nprocs] [npubs]"""
import socket, sys, threading, time

HOST, PORT, MODE = sys.argv[1], int(sys.argv[2]), sys.argv[3]
SECS = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0
NSUBS = int(sys.argv[5]) if len(sys.argv) > 5 else 10
NPROCS = int(sys.argv[6]) if len(sys.argv) > 6 else 4
NPUBS = int(sys.argv[7]) if len(sys.argv) > 7 else 1


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


PAYLOAD = b"m" * 64
CHAN = b"bf:chan"


def fanout_frame(shard):
    # Every delivery on this bench is byte-identical, so a subscriber can count MESSAGES by
    # counting BYTES.  That is the whole point: the old per-frame readline parser cost ~1.4us of
    # CPython per delivery, so ten subscribers saturated the load generator at ~750k deliveries/s
    # and BOTH servers measured the same number.  A harness ceiling reported as a server result is
    # the wrong-two-quantities trap; byte counting moves the ceiling ~30x out of the way.
    label = b"smessage" if shard else b"message"
    return (b"*3\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n" %
            (len(label), label, len(CHAN), CHAN, len(PAYLOAD), PAYLOAD))


def fanout_sub_proc(shard, nsubs, secs, ready_w, go_r, out_w):
    # One process, `nsubs` byte-counting subscriber threads.  recv() drops the GIL, so threads
    # here cost a syscall each and nothing more.
    import os
    sub_cmd = "ssubscribe" if shard else "subscribe"
    frame = fanout_frame(shard)
    flen = len(frame)
    totals = [0] * nsubs
    checked = [b""] * nsubs
    ready = threading.Barrier(nsubs + 1)
    socks = []

    def subscriber(i):
        s = conn(); f = s.makefile("rb")
        s.sendall(enc(sub_cmd, CHAN))
        f.readline(); f.readline(); f.read(len(sub_cmd) + 2)
        f.readline(); f.read(len(CHAN) + 2); f.readline()
        rest = f.raw._sock if hasattr(f, "raw") else s
        socks.append(s)
        ready.wait()
        n = 0
        first = b""
        s.settimeout(3.0)
        try:
            while True:
                b = s.recv(1 << 18)
                if not b: break
                if len(first) < flen: first += b
                n += len(b)
        except (socket.timeout, OSError):
            pass
        totals[i] = n
        checked[i] = first[:flen]
        del rest

    ts = [threading.Thread(target=subscriber, args=(i,)) for i in range(nsubs)]
    for t in ts: t.start()
    ready.wait()
    os.write(ready_w, b"r")            # this process's subscribers are all subscribed
    os.read(go_r, 1)                   # parent says the publish window is over
    for t in ts: t.join(6)
    bad = sum(1 for c in checked if c != frame)
    os.write(out_w, ("%d %d %d\n" % (sum(totals), flen, bad)).encode())


def run_fanout(shard):
    # NSUBS subscribers on one channel, spread over NPROCS processes; NPUBS pipelined publishers.
    import os
    pub_cmd = "SPUBLISH" if shard else "PUBLISH"
    frame = fanout_frame(shard)
    flen = len(frame)
    nprocs = min(NPROCS, NSUBS) if NSUBS else 0
    per = [NSUBS // nprocs + (1 if i < NSUBS % nprocs else 0) for i in range(nprocs)] if nprocs else []

    kids = []
    for cnt in per:
        rr, rw = os.pipe(); gr, gw = os.pipe(); orr, orw = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(rr); os.close(gw); os.close(orr)
            try: fanout_sub_proc(shard, cnt, SECS, rw, gr, orw)
            finally: os._exit(0)
        os.close(rw); os.close(gr); os.close(orw)
        kids.append((pid, rr, gw, orr))
    for _, rr, _, _ in kids:
        os.read(rr, 1)                 # every child fully subscribed before a byte is published

    published = [0] * NPUBS
    barrier = threading.Barrier(NPUBS)
    t0 = [0.0] * NPUBS
    dt = [0.0] * NPUBS

    def publisher(i):
        s = conn(); f = s.makefile("rb")
        BATCH = 256
        batch = b"".join(enc(pub_cmd, CHAN, PAYLOAD) for _ in range(BATCH))
        n = 0
        barrier.wait()
        a = time.monotonic()
        stop = a + SECS
        while time.monotonic() < stop:
            s.sendall(batch)
            drain_replies(f, BATCH)
            n += BATCH
        dt[i] = time.monotonic() - a
        published[i] = n
        s.close()

    pts = [threading.Thread(target=publisher, args=(i,)) for i in range(NPUBS)]
    for t in pts: t.start()
    for t in pts: t.join()
    span = max(dt) if dt else 1.0
    total_pub = sum(published)

    time.sleep(1.5)                    # let the delivery backlog drain before we stop counting
    delivered = 0
    bad = 0
    for pid, rr, gw, orr in kids:
        os.write(gw, b"g")
    for pid, rr, gw, orr in kids:
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = os.read(orr, 64)
            if not chunk: break
            buf += chunk
        os.waitpid(pid, 0)
        if buf:
            nbytes, fl, nbad = buf.split()
            delivered += int(nbytes) // int(fl)
            bad += int(nbad)
        os.close(rr); os.close(gw); os.close(orr)

    ideal = total_pub * NSUBS
    print("%s subs=%-3d publish/s: %-10.0f delivery/s: %-11.0f delivered %.1f%% of ideal%s"
          % (pub_cmd, NSUBS, total_pub / span, delivered / span,
             100.0 * delivered / ideal if ideal else 0.0,
             "" if bad == 0 else "  FRAME-MISMATCH=%d" % bad))


if MODE == "exec": run_exec()
elif MODE == "blpop": run_blpop()
elif MODE == "fanout": run_fanout(False)
elif MODE == "sfanout": run_fanout(True)
else: sys.exit("unknown mode")
