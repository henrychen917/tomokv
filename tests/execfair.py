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
import multiprocessing
import os
import time
import statistics
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


def fifo_child(args, indices, pairs, writer_keys, counts, start, stop, pipe, cpu):
    """Independent protocol readers: an EXEC packet cannot delay a plain send."""
    os.sched_setaffinity(0, {cpu})

    async def work():
        clients = [await Conn.open(args) for _ in indices]
        latencies = []
        first_latencies, latency_peaks = {}, {}
        async def worker(index, conn):
            if index < args.clients:
                a, b = pairs[index]
                packet = (frame("MULTI") + frame("INCR", a) + frame("INCR", b) + frame("EXEC")) * 4
                previous = [0, 0]
                while not stop.is_set():
                    conn.writer.write(packet)
                    await conn.writer.drain()
                    for _ in range(4):
                        assert await conn.read() == b"OK"
                        assert await conn.read() == b"QUEUED"
                        assert await conn.read() == b"QUEUED"
                        reply = await conn.read()
                        assert isinstance(reply, list) and len(reply) == 2, (index, reply)
                        assert all(type(v) is int and v > previous[k] for k, v in enumerate(reply)), (index, reply)
                        previous = reply
                        counts[index] += 1
            else:
                key = writer_keys[index - args.clients]
                ordinal, peak = 0, 0.0
                while not stop.is_set():
                    sent = time.monotonic()
                    value = await conn.cmd("INCR", key)
                    elapsed = time.monotonic() - sent
                    latencies.append(elapsed)
                    if ordinal == 0:
                        first_latencies[index] = elapsed
                    if elapsed > peak:
                        peak = elapsed
                        latency_peaks[index] = dict(ordinal=ordinal, sent=sent, elapsed=elapsed)
                    assert type(value) is int and value > 0, (index, value)
                    counts[index] += 1
                    ordinal += 1
        try:
            # A TCP handshake can precede server-side connection initialization.
            # Require a protocol reply before opening the FIFO timing window.
            for conn in clients:
                assert await conn.cmd("PING", "execfair-ready") == b"execfair-ready"
            pipe.send({"ready": True})
            await asyncio.to_thread(start.wait)
            await asyncio.gather(*(worker(i, c) for i, c in zip(indices, clients)))
            return {"latencies": latencies, "first_latencies": first_latencies,
                    "latency_peaks": latency_peaks}
        finally:
            for conn in clients:
                await conn.close()
    try:
        pipe.send(asyncio.run(work()))
    except BaseException as error:
        pipe.send({"error": repr(error)})
        raise
    finally:
        pipe.close()


async def run_fifo(args):
    assert args.shape == "hot", "FIFO share is defined for the hot shape"
    admin = await Conn.open(args)
    children = []
    context = multiprocessing.get_context("spawn")
    start, stop = context.Event(), context.Event()
    counts = context.RawArray("Q", args.clients + 4)
    evidence = {"shape": args.shape, "seconds": args.seconds, "exec_clients": args.clients,
                "pipeline": 4, "windows": [], "independent_plain_process": True}
    try:
        prefix = "execfair:" + uuid.uuid4().hex + ":"
        names = [prefix + str(i) for i in range(4096)]
        routes = await admin.cmd("DEBUG", "SHARDS", *names)
        assert len(routes) == len(names)
        first = routes[0][1]
        left = [key for key, route in zip(names, routes) if route[1] == first]
        right = [key for key, route in zip(names, routes) if route[1] != first]
        assert left and right, "two owners required"
        pairs = [(left[0], right[0])] * args.clients
        writers = [pairs[0][i % 2] for i in range(4)]
        keys = sorted(set(pairs[0]))
        evidence["routes"] = await admin.cmd("DEBUG", "SHARDS", *keys)
        assert await admin.cmd("MSET", *[part for key in keys for part in (key, 0)]) == b"OK"
        evidence["before"] = await counters(admin)
        cpus = sorted(os.sched_getaffinity(0))
        assert len(cpus) >= 2, "FIFO live check needs independent EXEC/plain driver CPUs"
        groups = min(args.clients, len(cpus) - 1)
        for group in range(groups + 1):
            indices = list(range(group, args.clients, groups)) if group < groups else list(range(args.clients, args.clients + 4))
            parent, child = context.Pipe()
            proc = context.Process(target=fifo_child, args=(args, indices, pairs, writers, counts, start, stop, child, cpus[group]))
            proc.start(); child.close()
            children.append((proc, parent))
        for proc, pipe in children:
            assert await asyncio.to_thread(pipe.poll, 30), "protocol worker did not arm"
            assert pipe.recv() == {"ready": True}, "protocol worker failed during arming"
        evidence["protocol_ready_clients"] = len(counts)
        evidence["start_time"] = time.monotonic()
        start.set()
        began = prior_time = time.monotonic()
        prior = list(counts)
        periods = []
        for window in range(args.seconds):
            await asyncio.sleep(max(0, began + window + 1 - time.monotonic()))
            for proc, pipe in children:
                assert not pipe.poll() and proc.is_alive(), "protocol worker stopped before final window"
            current = list(counts)
            delta = [now - old for now, old in zip(current, prior)]
            observed = time.monotonic()
            if sum(delta[:args.clients]):
                periods.append((observed - prior_time) / sum(delta[:args.clients]))
            prior_time = observed
            evidence["windows"].append({"index": window, "completions": delta})
            assert min(delta) > 0, ("client made no progress in a one-second window", window, delta)
            prior = current
        stop.set()
        latencies = []
        for proc, pipe in children:
            assert await asyncio.to_thread(pipe.poll, 5), "protocol worker did not drain"
            result = pipe.recv()
            assert "error" not in result, result
            latencies.extend(result["latencies"])
            for field in ("first_latencies", "latency_peaks"):
                evidence.setdefault(field, {}).update(result[field])
            await asyncio.to_thread(proc.join, 5)
            assert proc.exitcode == 0, "protocol worker shutdown"
        completed = list(counts)
        expected = {key: sum(completed[:args.clients]) for key in keys}
        for index, key in enumerate(writers, args.clients):
            expected[key] += completed[index]
        actual = dict(zip(keys, map(int, await admin.cmd("MGET", *keys))))
        assert actual == expected, ("final counter mismatch", actual, expected)
        evidence.update(completions=completed, expected=expected, actual=actual)
        evidence["after"] = await counters(admin)
        evidence["deltas"] = {key: value - evidence["before"].get(key, 0) for key, value in evidence["after"].items()}
        d = evidence["deltas"]
        assert d.get("atomic_txn_fast_polls", 0) > 0, "fast lane never fired (PRE control)"
        assert d.get("atomic_txn_order_violations", 0) == 0, d
        assert d.get("atomic_txn_fifo_waits", 0) > 0, "FIFO window never opened"
        plain, executed = sum(completed[args.clients:]), sum(completed[:args.clients])
        assert d.get("atomic_txn_writer_marks", 0) <= 1.1 * plain, "writer re-episodes"
        share, expected_share = plain / executed, 4 / args.clients
        assert expected_share / 2 <= share <= expected_share * 2, ("FIFO share", share, expected_share)
        assert latencies and periods, "FIFO latency witness empty"
        latencies.sort()
        p99 = latencies[min(len(latencies) - 1, int(.99 * len(latencies)))]
        p100 = latencies[-1]
        bound99 = 3 * args.clients * statistics.median(periods)
        evidence["fifo"] = dict(share=share, expected_share=expected_share, plain_p99=p99, plain_p100=p100, bound99=bound99)
        assert p100 <= .020, ("plain p100 exceeds 20 ms", p100)
        assert p99 <= bound99, ("plain p99 exceeds three FIFO cycles", p99, bound99)
        evidence["pass"] = True
    finally:
        stop.set(); start.set()
        for proc, pipe in children:
            if proc.is_alive():proc.terminate()
            await asyncio.to_thread(proc.join, 5)
            if proc.is_alive():proc.kill();proc.join()
            pipe.close()
        await admin.close()
        if args.output:
            Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({key: evidence[key] for key in ("shape", "seconds", "completions", "deltas", "pass")}))


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
        plain_latency = []
        exec_periods = []
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
                    sent = time.monotonic()
                    value = await conn.cmd("INCR", key)
                    if args.fifo:
                        plain_latency.append(time.monotonic() - sent)
                    assert type(value) is int and value > 0, (index, value)
                    counts[index] += 1

        tasks = [asyncio.create_task(worker(i, conn)) for i, conn in enumerate(clients)]
        start.set()
        began = time.monotonic()
        prior = counts.copy()
        prior_time = began
        for window in range(args.seconds):
            await asyncio.sleep(max(0, began + window + 1 - time.monotonic()))
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("client stopped before the final window")
            current = counts.copy()
            delta = [now - old for now, old in zip(current, prior)]
            observed = time.monotonic()
            if sum(delta[:args.clients]):
                exec_periods.append((observed - prior_time) / sum(delta[:args.clients]))
            prior_time = observed
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
        if args.fifo and args.shape == "hot":
            plain = sum(counts[args.clients:])
            executed = sum(counts[:args.clients])
            assert evidence["deltas"].get("atomic_txn_fifo_waits", 0) > 0, "FIFO window never opened"
            assert evidence["deltas"].get("atomic_txn_writer_marks", 0) <= 1.1 * plain, "writer re-episodes"
            share = plain / executed
            expected_share = 4 / args.clients
            assert expected_share / 2 <= share <= expected_share * 2, ("FIFO share", share, expected_share)
            assert plain_latency and exec_periods, "FIFO latency witness empty"
            plain_latency.sort()
            p99 = plain_latency[min(len(plain_latency) - 1, int(.99 * len(plain_latency)))]
            p100 = plain_latency[-1]
            bound99 = 3 * args.clients * statistics.median(exec_periods)
            evidence["fifo"] = dict(share=share, expected_share=expected_share,
                                    plain_p99=p99, plain_p100=p100, bound99=bound99)
            assert p100 <= .020, ("plain p100 exceeds 20 ms", p100)
            assert p99 <= bound99, ("plain p99 exceeds three FIFO cycles", p99, bound99)
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
    parser.add_argument("--fifo", action="store_true", help="FIFO bounded-wait assertions, not a rate measurement")
    parser.add_argument("--output")
    args = parser.parse_args()
    assert args.seconds >= (1 if args.witness else 60), "stress must span at least 60 one-second windows"
    assert 1 <= args.clients <= 64
    asyncio.run(run_fifo(args) if args.fifo else run(args))


if __name__ == "__main__":
    main()
