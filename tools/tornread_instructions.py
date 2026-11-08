#!/usr/bin/env python3
"""Finite-work instruction accounting. No throughput result or performance verdict.

perf attaches to the server, with counters disabled during boot, population and warmup.
Its control pipe acknowledges both boundaries. Each cell checks every reply and the
exact commandstats delta. Results include each repeat, binary digest and perf evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from tornread import Conn, info_fields

VALUE = b"v" * 64
CLIENT = ROOT / "build/tornread/instr-client"


def receive(worker, timeout=120):
    if not select.select([worker.stdout], [], [], timeout)[0]:
        raise TimeoutError("finite workload worker did not finish")
    return worker.stdout.readline().strip()


def send(worker, message):
    worker.stdin.write(message + "\n")
    worker.stdin.flush()


def cell(binary, folder, seed, mode, atomic, verb, depth, count, clients, place_io):
    folder.mkdir(parents=True)
    if seed.exists():
        shutil.copy2(seed, folder / "workload.tomo")
    port = 26095
    guard = socket.socket()
    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    guard.bind(("127.0.0.1", port))
    guard.close()
    env = dict(os.environ, LC_ALL="C")
    argv = ["taskset", "-c", "0-7", str(binary), "--port", str(port), "--bind", "127.0.0.1",
            "--thread-mode", mode, "--shards", "16", "--atomic", str(atomic),
            "--read-local", "0", "--key-lb", "0", "--client-lb", "0", "--flip-auto", "0",
            "--save", "", "--databases", "1", "--dir", str(folder),
            "--dbfilename", "workload.tomo"]
    if mode == "2s":
        argv += ["--ratio", "6:2"]
    if place_io:
        argv += ["--enable-debug-command", "yes"]
    workers, worker_logs = [], []
    placed = []
    perf = None
    server = None
    fds = []
    with (folder / "server.log").open("w") as log, (folder / "perf.log").open("w") as perf_log:
        try:
            server = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("server boot failed")
                try:
                    admin = Conn("127.0.0.1", port)
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise TimeoutError("server readiness")
            listeners = subprocess.check_output(["ss", "-H", "-ltnp", f"sport = :{port}"], text=True)
            assert set(re.findall(r"pid=(\d+)", listeners)) == {str(server.pid)}, listeners
            for worker in range(clients):
                for i in range(0, 512, 32):
                    args = [item for k in range(i, i + 32) for item in (f"instr:{worker}:{k}", VALUE)]
                    assert admin.call("MSET", *args) == b"OK"
            if not seed.exists():
                assert admin.call("SAVE") == b"OK"
                shutil.copy2(folder / "workload.tomo", seed)
            for worker in range(clients):
                extra, inherited = [], ()
                if place_io:
                    target = worker % (6 if mode == "2s" else 8)
                    for _ in range(128):
                        conn = Conn("127.0.0.1", port)
                        if conn.call("DEBUG", "IO-THREAD") == target:
                            conn.sock.settimeout(None)
                            placed.append((conn, target))
                            inherited = (conn.sock.fileno(),)
                            extra = [str(inherited[0])]
                            break
                        conn.close()
                    else:
                        raise RuntimeError(f"could not place worker {worker} on IO {target}")
                worker_log = (folder / f"worker-{worker}.log").open("w")
                worker_logs.append(worker_log)
                proc = subprocess.Popen(["taskset", "-c", str(8 + worker % 4), str(CLIENT),
                                         str(port), verb, str(depth), str(count), str(worker), *extra],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=worker_log, text=True, env=env, pass_fds=inherited)
                workers.append(proc)
            for worker in workers:
                assert receive(worker) == "ready"
            before = info_fields(admin)
            ctl_r, ctl_w = os.pipe()
            ack_r, ack_w = os.pipe()
            fds = [ctl_r, ctl_w, ack_r, ack_w]
            perf_argv = ["perf", "stat", "-D", "-1", "--control", f"fd:{ctl_r},{ack_w}",
                         "-e", "instructions:u", "-p", str(server.pid), "-x", ";", "-o",
                         str(folder / "perf.csv")]
            perf = subprocess.Popen(perf_argv, pass_fds=(ctl_r, ack_w), env=env,
                                    stdout=perf_log, stderr=subprocess.STDOUT)

            def control(command):
                os.write(ctl_w, command.encode() + b"\n")
                if (not select.select([ack_r], [], [], 10)[0] or
                        os.read(ack_r, 64) not in (b"ack\n", b"ack\n\0")):
                    raise RuntimeError("perf control acknowledgement missing")

            control("enable")
            for worker in workers:
                send(worker, "run")
            for worker in workers:
                assert receive(worker) == str(count)
            control("disable")
            perf.send_signal(signal.SIGINT)
            assert perf.wait(timeout=10) in (0, -signal.SIGINT)
            after = info_fields(admin)
            key = "cmdstat_" + verb.lower()
            calls = lambda row: int(row[key].split(",")[0].split("=")[1])
            completed = calls(after) - calls(before)
            assert completed == clients * count, (completed, clients * count)
            for conn, target in placed:
                assert conn.call("DEBUG", "IO-THREAD") == target
            for worker in workers:
                send(worker, "close")
            for worker in workers:
                assert worker.wait(timeout=10) == 0
            row = next(line.split(";") for line in (folder / "perf.csv").read_text().splitlines()
                       if ";instructions:u;" in line)
            instructions = int(row[0])
            running_percent = float(row[4])
            assert instructions > 0 and running_percent >= 99.9, row
            result = dict(binary=str(binary), mode=mode, atomic=atomic, command=verb,
                          pipeline=depth, clients=clients, commands=completed,
                          instructions=instructions, instructions_per_op=instructions / completed,
                          io_placement=[target for _, target in placed],
                          seed_sha256=hashlib.sha256(seed.read_bytes()).hexdigest(),
                          counter_running_percent=running_percent, server_argv=argv, perf_argv=perf_argv)
            (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            admin.close()
            return result
        finally:
            if perf is not None and perf.poll() is None:
                perf.send_signal(signal.SIGINT)
                perf.wait(timeout=10)
            for worker in workers:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait(timeout=10)
            for worker_log in worker_logs:
                worker_log.close()
            for conn, _ in placed:
                conn.close()
            for fd in fds:
                os.close(fd)
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--count", type=int, default=65536, help="commands per connection")
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--modes", nargs="+", default=["2s", "1s"])
    parser.add_argument("--arms", nargs="+", default=["pre", "part1", "part2"])
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--place-io", action="store_true",
                        help="hold each worker on a DEBUG-witnessed IO thread across all arms")
    args = parser.parse_args()
    out = ROOT / "build/tornread" / time.strftime("instructions-%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra",
                    str(ROOT / "tools/tornread_instr_client.cc"), "-o", str(CLIENT)], check=True)
    arms = {arm: ROOT / f"build/tornread/tomokv-{arm}" for arm in args.arms}
    (out / "binaries.json").write_text(json.dumps({arm: hashlib.sha256(path.read_bytes()).hexdigest()
                                                  for arm, path in arms.items()}, indent=2) + "\n")
    cells = [(verb, depth, atomic) for atomic in (0, 1)
             for verb, depth in (("GET", 1), ("GET", 32), ("SET", 32), ("MGET", 8), ("MSET", 8))]
    if args.smoke:
        cells = cells[:1]
    print(out, flush=True)
    results = []
    for mode in args.modes:
        for verb, depth, atomic in cells:
            for rep in range(args.repeats):
                order = args.arms if rep % 2 == 0 else list(reversed(args.arms))
                for arm in order:
                    name = f"{mode}-a{atomic}-{verb}-p{depth}-r{rep}-{arm}"
                    row = cell(arms[arm], out / name, out / "seed.tomo", mode, atomic, verb, depth,
                               args.count, args.clients, args.place_io)
                    row.update(arm=arm, repeat=rep)
                    results.append(row)
                    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                    print(name, f"{row['instructions_per_op']:.2f} instructions/op", flush=True)


if __name__ == "__main__":
    main()
