#!/usr/bin/env python3
"""Torn-read probe for MSET/MGET atomicity.

Writers MSET the SAME 8 keys, all set to one identical tag-value per MSET
("w<id>.<seq>" padded). Readers MGET the same 8 keys; a reply whose 8 values
are not all identical is a TORN read (observed a partial MSET). Redis
(single-threaded) and Dragonfly (transactional) must show 0; TomoKV
atomic=off is EXPECTED to tear (per-key dispatch across workers); TomoKV
atomic=on (epoch MVCC) must show 0.

Raw RESP over sockets, one process per connection (real parallelism, no GIL
coupling), pipelined batches. Usage:
  torn_test.py LABEL HOST PORT DURATION_S WRITERS READERS PIPELINE VSIZE OUT_TSV
"""
import socket, sys, time, multiprocessing as mp

KEYS = [f"torn:{i}" for i in range(8)]

def enc(args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, str): a = a.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)

class Conn:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=10)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
    def send(self, data): self.s.sendall(data)
    def _need(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d: raise ConnectionError("eof")
            self.buf += d
    def _line(self):
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i+2:]
                return line
            d = self.s.recv(65536)
            if not d: raise ConnectionError("eof")
            self.buf += d
    def reply(self):
        line = self._line(); t = line[:1]
        if t in (b"+", b":"): return line[1:]
        if t == b"-": raise RuntimeError(line[1:].decode())
        if t == b"$":
            n = int(line[1:])
            if n < 0: return None
            self._need(n + 2)
            v, self.buf = self.buf[:n], self.buf[n+2:]
            return v
        if t == b"*":
            n = int(line[1:])
            if n < 0: return None
            return [self.reply() for _ in range(n)]
        raise RuntimeError("bad resp: %r" % line)

def writer(host, port, wid, vsize, pipe, stop, msets, errs):
    try:
        c = Conn(host, port); seq = 0; local = 0
        while not stop.value:
            batch = []
            for _ in range(pipe):
                tag = f"w{wid}.{seq}".ljust(vsize, "x"); seq += 1
                args = ["MSET"]
                for k in KEYS: args += [k, tag]
                batch.append(enc(args))
            c.send(b"".join(batch))
            for _ in range(pipe): c.reply()
            local += pipe
            if local >= 256:
                with msets.get_lock(): msets.value += local
                local = 0
        with msets.get_lock(): msets.value += local
    except Exception:
        with errs.get_lock(): errs.value += 1

def reader(host, port, pipe, stop, mgets, torn, miss, errs, exq):
    try:
        c = Conn(host, port); req = enc(["MGET"] + KEYS); lm = lt = lmiss = 0
        while not stop.value:
            c.send(req * pipe)
            for _ in range(pipe):
                vals = c.reply()
                lm += 1
                if vals is None or any(v is None for v in vals):
                    lmiss += 1; continue
                tags = {bytes(v[:24]) for v in vals}
                if len(tags) > 1:
                    lt += 1
                    if lt <= 2:
                        try: exq.put_nowait(b"|".join(sorted(tags))[:120].decode("ascii", "replace"))
                        except Exception: pass
            if lm >= 256:
                with mgets.get_lock(): mgets.value += lm
                with torn.get_lock(): torn.value += lt
                with miss.get_lock(): miss.value += lmiss
                lm = lt = lmiss = 0
        with mgets.get_lock(): mgets.value += lm
        with torn.get_lock(): torn.value += lt
        with miss.get_lock(): miss.value += lmiss
    except Exception:
        with errs.get_lock(): errs.value += 1

def main():
    label, host, port, dur, nw, nr, pipe, vsize, out = sys.argv[1:10]
    port, dur, nw, nr, pipe, vsize = int(port), int(dur), int(nw), int(nr), int(pipe), int(vsize)
    # populate so readers never see nil
    c = Conn(host, port)
    args = ["MSET"]
    for k in KEYS: args += [k, "init".ljust(vsize, "x")]
    c.send(enc(args)); c.reply()
    stop = mp.Value("b", 0)
    msets, mgets, torn, miss, errs = (mp.Value("l", 0) for _ in range(5))
    exq = mp.Queue(8)
    procs = [mp.Process(target=writer, args=(host, port, i, vsize, pipe, stop, msets, errs)) for i in range(nw)] + \
            [mp.Process(target=reader, args=(host, port, pipe, stop, mgets, torn, miss, errs, exq)) for _ in range(nr)]
    for p in procs: p.start()
    time.sleep(dur)
    stop.value = 1
    for p in procs: p.join(timeout=10)
    for p in procs:
        if p.is_alive(): p.terminate()
    ex = []
    while not exq.empty() and len(ex) < 4:
        try: ex.append(exq.get_nowait())
        except Exception: break
    rate = (torn.value / mgets.value) if mgets.value else 0.0
    row = f"{label}\t{mgets.value}\t{torn.value}\t{rate:.6f}\t{miss.value}\t{msets.value}\t{errs.value}\t{';'.join(ex) or '-'}"
    with open(out, "a") as f: f.write(row + "\n")
    print(f"TORN[{label}]: mgets={mgets.value} torn={torn.value} rate={rate:.4%} miss={miss.value} msets={msets.value} errs={errs.value}")

if __name__ == "__main__":
    main()
