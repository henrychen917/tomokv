#!/usr/bin/env python3
"""Crossed WATCH reservations: a bounded PRE deadlock probe (design 3.12).

Usage: t19_crossed_watch.py --binary PATH --port PORT --cores CORES [--mode 1s|2s]
DEBUG SLEEP parks both transactions after their WATCH phase, before either write.
The server is terminated even when the clients reach their deadline.
"""
from concurrent.futures import ThreadPoolExecutor
from resp import Conn, Server

port = int(__import__("sys").argv[1])
with Server(port, ["--enable-debug-command", "yes"]) as server:
    admin = server.conn()
    keys = ["txnfix:cross-watch:%d" % i for i in range(400)]
    geometry = admin.cmd("DEBUG", "SHARDS", *keys)
    first = 0
    second = next(i for i in range(1, len(keys)) if geometry[i][1] != geometry[0][1])
    a, b = keys[first], keys[second]
    print("geometry", a, geometry[first], b, geometry[second], flush=True)
    assert admin.cmd("MSET", a, "0", b, "0") == "OK"
    one, two = server.conn(timeout=20), server.conn(timeout=20)
    assert one.cmd("WATCH", a) == two.cmd("WATCH", b) == "OK"
    commands = lambda key: [["MULTI"], ["DEBUG", "SLEEP", ".2"], ["SET", key, "1"], ["EXEC"]]
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(client.pipeline, commands(key))
                   for client, key in ((one, b), (two, a))]
        replies = []
        for future in futures:
            try:
                replies.append(future.result())
            except TimeoutError:
                replies.append("TIMEOUT")
    print("crossed WATCH", replies, flush=True)
    one.close()
    two.close()
    admin.close()
    assert "TIMEOUT" not in replies, "crossed WATCH did not decide within 20 s"
