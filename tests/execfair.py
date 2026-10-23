#!/usr/bin/env python3
"""EXEC scheduling witness and bounded hot/private-key correctness stress.

No rates or latency claims: retain per-client completions in each one-second
window, exact final counters, every EXEC reply, and atomic_txn_* INFO deltas.
The gate owns boots. --witness is a short, non-vacuous fast-poll counter check;
the directed stress requires at least 60 seconds per boot and shape.
"""
import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path


def frame(*args):
    parts = [str(arg).encode() for arg in args]
    return b"*%d\r\n" % len(parts) + b"".join(
        b"$%d\r\n" % len(part) + part + b"\r\n" for part in parts)


class Conn:
    @classmethod
    async def open(cls, args):
        conn = cls()
        conn.reader, conn.writer = await asyncio.wait_for(
            asyncio.open_connection(args.host, args.port), 5)
        return conn

    async def read(self):
        line = await self.reader.readline()
        assert line.endswith(b"\r\n"), ("invalid/closed RESP stream", line)
        kind, value = line[:1], line[1:-2]
        if kind == b"+":
            return value
        if kind == b":":
            return int(value)
        if kind == b"$":
            size = int(value)
            if size == -1:
                return None
            data = await self.reader.readexactly(size + 2)
            assert data[-2:] == b"\r\n"
            return data[:-2]
        if kind == b"*":
            return [await self.read() for _ in range(int(value))] if int(value) >= 0 else None
        raise AssertionError(("unexpected reply", line))

    async def cmd(self, *args):
        self.writer.write(frame(*args))
        await self.writer.drain()
        return await asyncio.wait_for(self.read(), 5)

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


async def counters(admin):
    info = await admin.cmd("INFO", "stats")
    return {key: int(value) for line in info.decode().splitlines() if ":" in line
            for key, value in [line.split(":", 1)] if key.startswith("atomic_txn_")}


async def run(args):
    admin = await Conn.open(args)
    clients = []
    tasks = []
    prefix = "execfair:" + uuid.uuid4().hex + ":"
    evidence = {"shape": args.shape, "seconds": args.seconds, "exec_clients": args.clients,
                "pipeline": 4, "windows": []}
    try:
        names = [prefix + str(i) for i in range(4096)]
        routes = await admin.cmd("DEBUG", "SHARDS", *names)
        assert len(routes) == len(names)
        first = routes[0][1]
        left = [key for key, route in zip(names, routes) if route[1] == first]
        right = [key for key, route in zip(names, routes) if route[1] != first]
        assert len(left) >= args.clients and len(right) >= args.clients, "two owners required"
        pairs = [(left[0], right[0])] * args.clients if args.shape == "hot" else list(
            zip(left[:args.clients], right[:args.clients]))
        writers = [pairs[0][i % 2] for i in range(4)] if args.shape == "hot" else []
        keys = sorted({key for pair in pairs for key in pair})
        evidence["routes"] = await admin.cmd("DEBUG", "SHARDS", *keys)
        assert await admin.cmd("MSET", *[part for key in keys for part in (key, 0)]) == b"OK"
        evidence["before"] = await counters(admin)
        clients = [await Conn.open(args) for _ in range(args.clients + len(writers))]
        counts = [0] * len(clients)
        start = asyncio.Event()
        stopping = False

        async def worker(index, conn):
            await start.wait()
            if index < args.clients:
                a, b = pairs[index]
                packet = (frame("MULTI") + frame("INCR", a) + frame("INCR", b) + frame("EXEC")) * 4
                previous = [0, 0]
                while not stopping:
                    conn.writer.write(packet)
                    await conn.writer.drain()
                    for _ in range(4):
                        assert await conn.read() == b"OK"
                        assert await conn.read() == b"QUEUED"
                        assert await conn.read() == b"QUEUED"
                        reply = await conn.read()
                        assert isinstance(reply, list) and len(reply) == 2, (index, reply)
                        assert all(type(v) is int and v > previous[k] for k, v in enumerate(reply)), (index, reply)
                        if args.shape == "private":
                            assert reply == [counts[index] + 1] * 2, (index, reply, counts[index])
                        previous = reply
                        counts[index] += 1
            else:
                key = writers[index - args.clients]
                while not stopping:
                    value = await conn.cmd("INCR", key)
                    assert type(value) is int and value > 0, (index, value)
                    counts[index] += 1

        tasks = [asyncio.create_task(worker(i, conn)) for i, conn in enumerate(clients)]
        start.set()
        began = time.monotonic()
        prior = counts.copy()
        for window in range(args.seconds):
            await asyncio.sleep(max(0, began + window + 1 - time.monotonic()))
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("client stopped before the final window")
            current = counts.copy()
            delta = [now - old for now, old in zip(current, prior)]
            evidence["windows"].append({"index": window, "completions": delta})
            assert min(delta) > 0, ("client made no progress in a one-second window", window, delta)
            prior = current
        stopping = True
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        expected = {key: 0 for key in keys}
        for index, pair in enumerate(pairs):
            for key in pair:
                expected[key] += counts[index]
        for index, key in enumerate(writers, args.clients):
            expected[key] += counts[index]
        actual = dict(zip(keys, map(int, await admin.cmd("MGET", *keys))))
        assert actual == expected, ("final counter mismatch", actual, expected)
        evidence["completions"] = counts
        evidence["expected"] = expected
        evidence["actual"] = actual
        evidence["after"] = await counters(admin)
        evidence["deltas"] = {key: value - evidence["before"].get(key, 0)
                              for key, value in evidence["after"].items()}
        assert evidence["deltas"].get("atomic_txn_fast_polls", 0) > 0, "fast lane never fired (PRE control)"
        assert evidence["deltas"].get("atomic_txn_order_violations", 0) == 0, evidence["deltas"]
        evidence["pass"] = True
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for conn in clients + [admin]:
            await conn.close()
        if args.output:
            Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({key: evidence[key] for key in ("shape", "seconds", "completions", "deltas", "pass")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--shape", choices=("hot", "private"), default="hot")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--clients", type=int, default=64)
    parser.add_argument("--witness", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    assert args.seconds >= (1 if args.witness else 60), "stress must span at least 60 one-second windows"
    assert 1 <= args.clients <= 64
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
