#!/usr/bin/env python3
"""IO4.19 / PFDATATY.1 regressions, adapted from audit T16/T16b and shape T5/T13.

Owns its boot and port. Gate callers must stop their pre-booted candidate first.
Each arming condition is mandatory; no absent migration or timing window is skipped.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager, ExitStack, closing
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time

from _lib import Conn, encode, info, wait_ready

FIXTURE = Path(__file__).parent / "fixtures/perfio-stream.json"


def emit(**row):
    print(json.dumps(row, sort_keys=True), flush=True)


@contextmanager
def boot(args, label, extra=()):
    directory = args.output.resolve() / label
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", args.port)) != 0, "owned port already busy"
    argv = ["taskset", "-c", args.cores, str(args.binary.resolve()),
            "--bind", "127.0.0.1", "--port", str(args.port), "--dir", str(directory),
            "--save", "", "--appendonly", "no", "--enable-debug-command", "yes"]
    if not args.oracle:
        argv += ["--thread-mode", args.mode, "--shards", "16",
                 "--net-io", args.net_io, "--flip-auto", "0", "--key-lb", "0",
                 "--client-lb", "0", "--enable-debug-command", "yes", *extra]
        if args.mode == "1s":
            argv += ["--read-local", str(getattr(args, "read_local", 1))]
        else:
            argv += ["--ratio", args.ratio]
    emit(event="boot", argv=argv, affinity=sorted(os.sched_getaffinity(0)))
    with (directory / "server.log").open("w") as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        c = None
        try:
            c = wait_ready("127.0.0.1", args.port, timeout=15, process=p,
                           log_path=None if args.oracle else directory / "server.log")
            yield c, p
        finally:
            if c:
                c.close()
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
            emit(event="stop", pid=p.pid, rc=p.returncode)
    assert p.returncode == 0, (p.returncode, (directory / "server.log").read_text()[-2000:])


def epoll_snapshot(pid):
    fds = {}
    for p in Path(f"/proc/{pid}/fd").iterdir():
        try:
            fds[int(p.name)] = os.readlink(p)
        except FileNotFoundError:
            pass
    sockets = {fd: int(re.fullmatch(r"socket:\[(\d+)\]", target)[1])
               for fd, target in fds.items() if target.startswith("socket:[")}
    registered = defaultdict(list)
    stale = []
    for ep, target in fds.items():
        if target != "anon_inode:[eventpoll]":
            continue
        for line in Path(f"/proc/{pid}/fdinfo/{ep}").read_text().splitlines():
            m = re.search(r"tfd:\s+(\d+).*data:\s*([0-9a-f]+).*ino:\s*([0-9a-f]+)", line)
            if not m or int(m[2], 16) >> 56 != 2:  # UrKind::Recv, excluding listeners
                continue
            fd, inode = int(m[1]), int(m[3], 16)
            # The inode, not just fd existence, detects reuse by a different socket.
            registered[inode].append(ep)
            if sockets.get(fd) != inode:
                stale.append([ep, fd, inode])
    duplicates = {str(k): v for k, v in registered.items() if len(v) > 1}
    return dict(stale=stale, duplicates=duplicates,
                registrations=sum(map(len, registered.values()))), registered


def audit(pid, phase, expected):
    row, registered = epoll_snapshot(pid)
    emit(event="epoll", phase=phase, stale=len(row["stale"]),
         duplicates=len(row["duplicates"]), registrations=row["registrations"])
    assert not row["stale"] and not row["duplicates"], (phase, row)
    assert row["registrations"] == expected, (phase, row, expected)
    return registered


def traffic(peers, rounds=40, batch=1):
    request = encode("PING") * batch
    for _ in range(rounds):
        for c in peers:
            c.raw(request)
        for c in peers:
            for _ in range(batch):
                assert c.read() == b"PONG"


def events(admin, peers, phase):
    traffic(peers, 4)
    before = info(admin, "stats")
    traffic(peers)
    after = info(admin, "stats")
    e = int(after["net_io_epoll_events"]) - int(before["net_io_epoll_events"])
    n = int(after["total_commands_processed"]) - int(before["total_commands_processed"])
    assert n == 40*len(peers)+1, (phase, "unexpected command count", n)
    emit(event="events", phase=phase, events=e, commands=n, per_command=e/n)
    assert e == n, f"{phase}: expected 1.000 epoll event/command, got {e}/{n}"


def epoll_flip(args):
    with boot(args, "epoll-flip") as (admin, p), ExitStack() as stack:
        peers = [stack.enter_context(closing(Conn("127.0.0.1", args.port))) for _ in range(200)]
        traffic(peers, 1)
        shape = dict(zip(*[iter(admin.must("FLIP"))]*2))
        total = shape[b"live_io"] + shape[b"live_ex"]
        audit(p.pid, "initial", len(peers)+1)
        events(admin, peers[:64], "initial")
        failures = []
        for i, nio in enumerate([total//4, total//2, total*3//4, total//2]*3):
            reply = admin.cmd("FLIP", nio, total-nio)
            if reply != b"OK":
                failures.append(f"FLIP {i}: {reply}")
                break
            traffic(peers, 2)
            # Retain both T16's growth and T16b's event amplification on a broken arm.
            # Every failed assertion is retained and fails the row after collection.
            for check in (lambda: audit(p.pid, f"flip-{i}", len(peers)+1),
                          lambda: events(admin, peers[:64], f"flip-{i}")):
                try: check()
                except AssertionError as error: failures.append(str(error))
        assert not failures, failures


def epoll_lb(args):
    # Natural skew: select several sockets registered with the same actual epoll owner.
    # Unlike a single elephant, moving one of these clients strictly improves the spread.
    with boot(args, "epoll-lb", ["--client-lb", "1"]) as (admin, p), ExitStack() as stack:
        peers = [stack.enter_context(closing(Conn("127.0.0.1", args.port))) for _ in range(96)]
        traffic(peers, 1)
        assert admin.must("SET", "perfio-lb", "v") == b"OK"
        registered = audit(p.pid, "lb-initial", len(peers)+1)
        events(admin, peers, "lb-initial")
        ports = {}
        for line in Path(f"/proc/{p.pid}/net/tcp").read_text().splitlines()[1:]:
            columns = line.split()
            if int(columns[1].split(":")[1], 16) == args.port:
                ports[int(columns[2].split(":")[1], 16)] = int(columns[9])
        owners = defaultdict(list)
        for c in peers:
            inode = ports[c.sock.getsockname()[1]]
            assert len(registered[inode]) == 1
            owners[registered[inode][0]].append(c)
        hot = max(owners.values(), key=len)
        assert len(hot) >= 4, "failed to arm multiple clients on one IO owner"
        before = int(info(admin, "LB")["tomokv_clientlb_moves"])
        request = encode("GET", "perfio-lb") * 32
        deadline, rounds = time.monotonic() + 35, 0
        after = before
        while time.monotonic() < deadline and after == before:
            for c in hot:
                c.raw(request)
            for c in hot:
                for _ in range(32):
                    assert c.read() == b"v"
            rounds += 1
            if rounds % 32 == 0:
                after = int(info(admin, "LB")["tomokv_clientlb_moves"])
            time.sleep(.001)
        emit(event="lb-witness", hot_clients=len(hot), rounds=rounds, before=before, after=after)
        assert after > before, "client-lb move never armed within 35 seconds"
        time.sleep(.05)  # let the already witnessed transfer finish before the fd snapshot
        audit(p.pid, "lb-moved", len(peers)+1)
        events(admin, peers, "lb-moved")


def populate(c, n, key="x"):
    for start in range(0, n, 256):
        count = min(256, n-start)
        c.raw(b"".join(encode("XADD", key, f"{i+1}-0", "f", "v")
                        for i in range(start, start+count)))
        for i in range(start, start+count):
            assert c.read() == f"{i+1}-0".encode()


def stream_latency(c):
    samples = {}
    for n in (1000, 100000):
        c.must("DEL", "x", "plain")
        populate(c, n)
        c.must("SET", "plain", "ok")
        c.must("XGROUP", "CREATE", "x", "g", "0")
        for label, first in [("xlen", encode("XLEN", "x")),
                             ("xreadgroup", encode("XREADGROUP", "GROUP", "g", "c",
                                                  "COUNT", 1, "STREAMS", "x", ">"))]:
            times = []
            for _ in range(33):
                start = time.perf_counter_ns()
                c.raw(first + encode("GET", "plain"))
                one, two = c.read(), c.read()
                times.append(time.perf_counter_ns()-start)
                assert two == b"ok"
                assert one == n if label == "xlen" else len(one[0][1]) == 1
            samples[n, label] = times
            emit(event="latency", entries=n, prefix=label, samples_ns=times,
                 median_ns=statistics.median(times), p99_ns=sorted(times)[-1])
    # A fixed 3 ms ceiling is far below the audited 12 ms stall. No baseline-dependent
    # tolerance that could let two equally slow arms pass. Retain all raw samples.
    assert max(samples[100000, "xreadgroup"]) < 3_000_000, "GET after XREADGROUP exceeds 3 ms"


def metadata(c):
    records = []
    def snapshot(label):
        g = dict(zip(*[iter(c.must("XINFO", "GROUPS", "x")[0])]*2))
        full = dict(zip(*[iter(c.must("XINFO", "STREAM", "x", "FULL", "COUNT", 1))]*2))
        f = dict(zip(*[iter(full[b"groups"][0])]*2))
        fields = (b"last-delivered-id", b"entries-read", b"lag")
        project = lambda v: [v[x].decode() if isinstance(v[x], bytes) else v[x] for x in fields]
        assert project(g) == project(f), (label, g, f)
        records.append([label, project(g)])
    def read(count=1):
        return c.must("XREADGROUP", "GROUP", "g", "c", "COUNT", count, "STREAMS", "x", ">")
    cases = ("plain", "xdel-ahead", "xdel-cursor", "xtrim", "xsetid", "xclaim",
             "xautoclaim", "entriesread", "arbitrary", "tail", "reload", "trim-empty")
    for case in cases:
        c.must("DEL", "x")
        populate(c, 8)
        cursor = "4-0" if case == "arbitrary" else "$" if case == "tail" else "0"
        suffix = ["ENTRIESREAD", 40] if case == "entriesread" else []
        c.must("XGROUP", "CREATE", "x", "g", cursor, *suffix)
        snapshot(case+":created")
        read(2)
        snapshot(case+":delivered")
        if case == "xdel-ahead": c.must("XDEL", "x", "5-0")
        elif case == "xdel-cursor": c.must("XDEL", "x", "2-0")
        elif case == "xtrim": c.must("XTRIM", "x", "MAXLEN", 4)
        elif case == "xsetid": c.must("XSETID", "x", "9-0", "ENTRIESADDED", 20, "MAXDELETEDID", "4-0")
        elif case == "xclaim": c.must("XCLAIM", "x", "g", "other", 0, "1-0", "LASTID", "4-0")
        elif case == "xautoclaim":
            c.must("XDEL", "x", "1-0")
            c.must("XAUTOCLAIM", "x", "g", "other", 0, "0-0", "COUNT", 2)
        elif case == "entriesread": c.must("XGROUP", "SETID", "x", "g", "2-0", "ENTRIESREAD", 40)
        elif case == "tail": c.must("XADD", "x", "9-0", "f", "v")
        elif case == "reload": c.must("DEBUG", "RELOAD")
        elif case == "trim-empty": c.must("XTRIM", "x", "MAXLEN", 0)
        snapshot(case+":changed")
        for i in range(7):
            read()
            snapshot(case+f":next-{i}")
    return records


def main():
    started = time.monotonic()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case", choices=["epoll-flip", "epoll-lb", "stream", "metadata"])
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--cores", required=True)
    ap.add_argument("--ratio", default="6:2")
    ap.add_argument("--mode", choices=["1s", "2s"], default="2s")
    ap.add_argument("--net-io", default="epoll")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--record-oracle", action="store_true")
    args = ap.parse_args()
    if args.case == "epoll-flip": epoll_flip(args)
    elif args.case == "epoll-lb": epoll_lb(args)
    else:
        with boot(args, args.case) as (c, _):
            actual = metadata(c)
            (args.output / "metadata.json").write_text(json.dumps(actual, indent=2)+"\n")
            if args.record_oracle:
                assert args.oracle, "fixtures may only be recorded from the oracle"
                FIXTURE.write_text(json.dumps(actual, indent=2)+"\n")
            else:
                expected = json.loads(FIXTURE.read_text())
                differences = [(a, b) for a, b in zip(actual, expected) if a != b]
                emit(event="metadata", cases=len(actual), differences=differences)
                if args.case == "stream": stream_latency(c)
                assert actual == expected, "entries-read/lag differ from Redis 7.4 oracle"
    emit(result="PASS", case=args.case, elapsed_s=time.monotonic()-started)


if __name__ == "__main__":
    main()
