#!/usr/bin/env python3
"""T12b: consequence of T12 on a neighbour. One io thread (TomoKV `--thread-mode 2s --ratio 1:1`; Redis is
single-threaded anyway). Connection A trickles one `PING a a ... a` frame of N = 2,000,000 arguments (14 MB, under
the default 1 GB client-query-buffer-limit) in 64 KiB chunks; connection B pings in a loop. Reported: server CPU
seconds for A's frame, B's max/median PING round trip, number of B pings, and A's final reply. Behaviour evidence
for an O(N^2) re-parse (a stall that grows with N), not a latency benchmark."""
import os, socket, statistics, sys, threading, time
sys.path.insert(0, "/home/user/Projects/round4-read/tests/net")
import netlib
from netlib import enc
HZ = os.sysconf("SC_CLK_TCK")
def cpu(pid):
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / HZ

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000_000
payload = b"*%d\r\n$4\r\nPING\r\n" % N + b"$1\r\na\r\n" * (N - 1)
for kind, port, args in (("redis", 22538, []), ("tomo", 22539, ["--thread-mode", "2s", "--ratio", "1:1"])):
    srv = netlib.Server(kind, port, args)
    try:
        stop = threading.Event(); rtts = []
        def pinger():
            b = netlib.connect(port)
            while not stop.is_set():
                t0 = time.perf_counter(); b.sendall(enc("PING")); b.recv(16); rtts.append(time.perf_counter() - t0)
                time.sleep(0.001)
            b.close()
        th = threading.Thread(target=pinger); th.start(); time.sleep(0.3)
        base = list(rtts)
        a = netlib.connect(port, timeout=300)
        c0 = cpu(srv.pid); t0 = time.time()
        for i in range(0, len(payload), 65536):
            a.sendall(payload[i:i + 65536]); time.sleep(0.002)
        t_sent = time.time() - t0
        a.settimeout(300); reply = a.recv(128); t_reply = time.time() - t0
        c1 = cpu(srv.pid); stop.set(); th.join(); a.close()
        during = rtts[len(base):]
        print(f"{kind:5} N={N}: frame cpu={c1-c0:6.2f}s sent_in={t_sent:5.2f}s reply_at={t_reply:6.2f}s reply={reply[:40]!r}")
        print(f"      neighbour PING: n={len(during)} median={statistics.median(during)*1e3:7.2f}ms max={max(during)*1e3:8.2f}ms "
              f"(idle baseline max {max(base)*1e3:.2f}ms)")
    finally:
        srv.stop()
