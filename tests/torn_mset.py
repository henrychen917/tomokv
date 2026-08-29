#!/usr/bin/env python3
"""Is MSET actually atomic on this server?

usage: torn_mset.py HOST PORT [seconds]

Redis defines MSET as atomic: a concurrent reader sees either all of an MSET's writes or none of
them, never a mixture. This drives one writer that MSETs eight keys to a single repeated character
-- 'aaaa...' then 'bbbb...' then 'cccc...' -- and several readers that MGET the same eight keys and
check that every returned value is the SAME character.

A mixture is a torn read and proves the server does not implement MSET atomically.

This exists because a benchmark that compares an atomic MSET against a non-atomic one is not
comparing the same work, and the difference can be several fold. Before quoting any multi-key ratio
between two servers, run this against both.
"""

import socket
import sys
import threading
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
KEYS = ["torn:%d" % i for i in range(8)]
VALSIZE = 32
ALPHABET = "abcdefghijklmnopqrstuvwxyz"

stop = threading.Event()
torn_samples = []
reads_done = [0]
lock = threading.Lock()


def conn():
    s = socket.create_connection((HOST, PORT), timeout=10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


def send(sock, *args):
    enc = [a.encode() if isinstance(a, str) else a for a in args]
    sock.sendall(b"*%d\r\n" % len(enc) +
                 b"".join(b"$%d\r\n" % len(a) + a + b"\r\n" for a in enc))


def read_reply(f):
    prefix = f.read(1)
    line = f.readline()
    if not prefix:
        raise IOError("closed")
    val = line[:-2]
    if prefix in b"+-:":
        return val
    if prefix == b"$":
        n = int(val)
        if n == -1:
            return None
        payload = f.read(n)
        f.read(2)
        return payload
    if prefix == b"*":
        n = int(val)
        return None if n == -1 else [read_reply(f) for _ in range(n)]
    raise IOError("bad prefix %r" % prefix)


def writer():
    sock, f = conn()
    i = 0
    while not stop.is_set():
        ch = ALPHABET[i % len(ALPHABET)]
        args = ["MSET"]
        for k in KEYS:
            args += [k, ch * VALSIZE]
        send(sock, *args)
        read_reply(f)
        i += 1
    sock.close()


def reader():
    sock, f = conn()
    local = 0
    while not stop.is_set():
        send(sock, "MGET", *KEYS)
        vals = read_reply(f)
        local += 1
        if not vals or any(v is None for v in vals):
            continue
        # Every value must be the same repeated character: one MSET wrote them all.
        chars = {v[:1] for v in vals}
        if len(chars) != 1:
            with lock:
                if len(torn_samples) < 5:
                    torn_samples.append(sorted(c.decode() for c in chars))
    with lock:
        reads_done[0] += local
    sock.close()


# Seed so the first reads never see missing keys.
s0, f0 = conn()
args = ["MSET"]
for k in KEYS:
    args += [k, "a" * VALSIZE]
send(s0, *args)
read_reply(f0)
s0.close()

threads = [threading.Thread(target=writer) for _ in range(2)] + \
          [threading.Thread(target=reader) for _ in range(6)]
for t in threads:
    t.start()
time.sleep(SECONDS)
stop.set()
for t in threads:
    t.join()

torn = len(torn_samples)
print("reads: %d   torn reads observed: %s" % (reads_done[0], "YES" if torn else "no"))
if torn:
    print("  MSET is NOT atomic here. Sample mixtures seen in one MGET of 8 keys:")
    for s in torn_samples:
        print("    %r" % s)
    sys.exit(1)
print("  every MGET saw a single writer's values -- consistent with atomic MSET")
sys.exit(0)
