#!/usr/bin/env python3
"""Cut-window starvation: 16 contended MSET/MGET connections, P16, four seconds.

Python-only translation of stallrepro REPORT section 7. Four independent client
processes keep the one-IO geometry busy without sharing the Python GIL. Every
request is timed from send to complete reply, including the final pipeline drain.
A missing/zero refusal counter is a failure, not an unarmed pass.
"""
import argparse
import asyncio
from collections import deque
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import time

from _gate_process import cpus, fields, server
from _lib import encode

KEYS = [f"memtier-3000000{i}" for i in range(8)]
COUNTER = "atomic_cut_window_refusals"


async def read_reply(reader):
    line = await reader.readuntil(b"\r\n")
    tag, value = line[:1], line[1:-2]
    if tag == b"+":
        return value
    if tag == b"$":
        n = int(value)
        if n == -1:
            return None
        data = await reader.readexactly(n + 2)
        assert data[-2:] == b"\r\n"
        return data[:-2]
    if tag == b"*":
        return [await read_reply(reader) for _ in range(int(value))]
    raise AssertionError(f"unexpected response: {line!r}")


async def load(port, worker, barrier):
    sockets = [await asyncio.open_connection("127.0.0.1", port) for _ in range(4)]
    barrier.wait(timeout=15)
    start = time.monotonic()
    end = start + 4

    async def connection(index, reader, writer):
        rng = random.Random(12345 + worker * 4 + index)
        pending = deque()
        completed, maximum, over_bound = 0, 0.0, 0
        sequence = 0

        def issue():
            nonlocal sequence
            write = rng.getrandbits(1)
            sequence += 1
            if write:
                token = f"{worker}:{index}:{sequence}:".encode().ljust(256, b"x")
                frame = encode("MSET", *[arg for key in KEYS for arg in (key, token)])
            else:
                frame = encode("MGET", *KEYS)
            pending.append((time.monotonic(), write))
            writer.write(frame)

        for _ in range(16):
            issue()
        await writer.drain()
        try:
            while pending:
                reply = await asyncio.wait_for(read_reply(reader), timeout=10)
                sent, write = pending.popleft()
                waited = (time.monotonic() - sent) * 1000
                maximum = max(maximum, waited)
                over_bound += waited > 500
                if write:
                    assert reply == b"OK", repr(reply)
                else:
                    assert isinstance(reply, list) and len(reply) == 8, repr(reply)
                    assert reply[0] is not None and all(v == reply[0] for v in reply), "torn MGET"
                completed += 1
                if time.monotonic() < end:
                    issue()
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
        return dict(client=worker * 4 + index, completed=completed,
                    max_ms=maximum, over_500ms=over_bound)

    return await asyncio.gather(*(connection(i, *pair) for i, pair in enumerate(sockets)))


def worker(port, index, barrier, output):
    try:
        output.send(dict(clients=asyncio.run(load(port, index, barrier))))
    except BaseException as error:
        output.send(dict(error=repr(error)))
    finally:
        output.close()


def exercise(port):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(5)
    children, pipes = [], []
    try:
        for i in range(4):
            read, write = ctx.Pipe(duplex=False)
            child = ctx.Process(target=worker, args=(port, i, barrier, write))
            child.start()
            write.close()
            children.append(child)
            pipes.append(read)
        barrier.wait(timeout=15)
        results = []
        for read in pipes:
            assert read.poll(20), "load worker exceeded bounded completion time"
            result = read.recv()
            assert "error" not in result, result
            results.extend(result["clients"])
        for child in children:
            child.join(timeout=5)
            assert child.exitcode == 0, f"load worker exit {child.exitcode}"
        return results
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join()
        for read in pipes:
            read.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--cores", required=True)
    parser.add_argument("--load-cores", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode", choices=("1s", "2s"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-missing-counter", action="store_true",
                        help="PRE diagnosis only; latency and reply assertions still apply")
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    with binary.open("rb") as image:
        binary_sha256 = hashlib.file_digest(image, "sha256").hexdigest()
    os.environ["LC_ALL"] = "C"
    os.sched_setaffinity(0, cpus(args.load_cores))
    selected = cpus(args.cores)[:1 if args.mode == "1s" else 2]
    assert len(selected) == (1 if args.mode == "1s" else 2)
    assert not set(selected) & set(cpus(args.load_cores))
    args.output.mkdir(parents=True, exist_ok=True)
    argv = ["--thread-mode", args.mode, "--atomic", "1", "--shards", "64",
            "--key-lb", "0", "--client-lb", "0", "--flip-auto", "0", "--read-local", "0"]
    if args.mode == "2s":
        argv += ["--ratio", "1:1"]
    # Fresh boots are bounded re-arming, never a missing-window skip. A latency or
    # reply failure is final; only an unarmed, otherwise clean attempt is rerolled.
    for attempt in range(3):
        with server(args.binary, ",".join(map(str, selected)), args.port,
                    args.output / f"boot-{attempt}", argv) as (conn, process):
            assert conn.must("MSET", *[arg for key in KEYS for arg in (key, b"seed")]) == b"OK"
            before = fields(conn.must("INFO", "ALL"))
            clients = exercise(args.port)
            after = fields(conn.must("INFO", "ALL"))
            refusals = int(after.get(COUNTER, 0)) - int(before.get(COUNTER, 0))
            result = dict(mode=args.mode, attempt=attempt, clients=clients,
                          max_ms=max(c["max_ms"] for c in clients), refusals=refusals,
                          counter_present=COUNTER in after,
                          binary=str(binary), binary_sha256=binary_sha256)
            (args.output / f"result-{attempt}.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result), flush=True)
            assert result["max_ms"] <= 500, f"request waited {result['max_ms']:.3f} ms > 500 ms"
            if refusals > 0 or (args.allow_missing_counter and COUNTER not in after):
                print(f"PASS stallfix cut window ({args.mode}): max={result['max_ms']:.3f} ms refusals={refusals}")
                return
    raise AssertionError("cut window never refused after three fresh boots")


if __name__ == "__main__":
    main()
