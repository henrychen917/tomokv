#!/usr/bin/env python3
"""T12: is an incomplete MULTIBULK frame re-parsed from its first argument on every arrival?
resp.h:250-299 is stateless across Incomplete (`pos = start`), unlike the inline arm (Client::inline_scanned,
conn.h:307-308) and unlike Redis (multibulklen/bulklen kept in the client). A trickled `PING a a a ... a` with N
arguments therefore costs O(N^2) argument parses on the io thread. Observable: server CPU seconds
(/proc/PID/stat utime+stime) spent receiving the SAME bytes trickled in 2 KiB chunks vs sent in one write,
for N = 50k / 100k / 200k, plus the reply (arity error) proving the frame completed. Not a throughput claim:
the evidence is the growth law of CPU per frame (linear vs quadratic)."""
import os, socket, sys, time
sys.path.insert(0, "/home/user/Projects/round4-read/tests/net")
import netlib
HZ = os.sysconf("SC_CLK_TCK")

def cpu(pid):
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / HZ

def frame(n):
    return b"*%d\r\n$4\r\nPING\r\n" % n + b"$1\r\na\r\n" * (n - 1)

def send(port, payload, chunk, gap):
    s = netlib.connect(port, timeout=120)
    t0 = time.time()
    if chunk:
        for i in range(0, len(payload), chunk):
            s.sendall(payload[i:i + chunk]); time.sleep(gap)
    else:
        s.sendall(payload)
    s.settimeout(120)
    reply = s.recv(256)
    dt = time.time() - t0
    s.close()
    return reply, dt

for kind, port in (("redis", 22536), ("tomo", 22537)):
    srv = netlib.Server(kind, port)
    try:
        for n in (50_000, 100_000, 200_000):
            payload = frame(n)
            c0 = cpu(srv.pid); r1, d1 = send(port, payload, 0, 0); c1 = cpu(srv.pid)
            r2, d2 = send(port, payload, 2048, 0.0005); c2 = cpu(srv.pid)
            print(f"{kind:5} N={n:7} bytes={len(payload):8}: one-write cpu={c1-c0:6.2f}s | trickled 2KiB cpu={c2-c1:6.2f}s "
                  f"wall={d2:5.2f}s reply={r2[:48]!r}")
    finally:
        srv.stop()
