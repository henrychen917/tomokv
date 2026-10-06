#!/usr/bin/env python3
"""Build/run the serverless CD13b wire fixture; optionally compare a harness-owned Redis.

Run on CPUs 112-127. This script never boots a server or runs a measurement.
"""
import argparse
import concurrent.futures
from pathlib import Path
import socket
import subprocess
import sys
from _lib import encode
from cd13b_wire import aclcat_property, geo_store_property, ownership

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/cd13b/unit"


def build_one(arm, namespace):
    source = ROOT / "build/cd13b/PRE-src" if arm == "PRE" else ROOT
    objects = ROOT / ("build/cd13b/" + arm)
    flags = ["g++", "-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-march=native",
             "-pthread", "-DTOMO_JEMALLOC", "-I" + str(source), "-I" + str(ROOT)]
    unit = OUT / (arm + "-" + namespace + ".o")
    links = sorted(p for p in (objects / "src").rglob("*.o") if p.name not in ("main.o", "xshard.o"))
    if namespace == "db0":
        flags += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
        links = sorted(p for p in (objects / "db0/src").rglob("*.o")
                       if p.name not in ("main.o", "xshard.o")) + links
    with (OUT / (arm + "-" + namespace + "-build.log")).open("w") as log:
        subprocess.run(flags + ["-c", str(ROOT / "tests/cd13b_unit.cc"), "-o", str(unit)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(flags + [str(unit)] + list(map(str, links)) +
                       ["-ljemalloc", "-luring", "-lssl", "-lcrypto", "-lm", "-o",
                        str(OUT / (arm + "-" + namespace))],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Built", arm, namespace, flush=True)


def read_reply(file):
    line = file.readline()
    if not line:
        raise EOFError("fixture/oracle closed before completing a reply")
    marker = line[:1]
    if marker in (b"*", b"~", b"%"):
        count = max(0, int(line[1:-2])) * (2 if marker == b"%" else 1)
        return line + b"".join(read_reply(file) for _ in range(count))
    if marker in (b"$", b"="):
        count = int(line[1:-2])
        return line + (file.read(count + 2) if count >= 0 else b"")
    assert marker in b"+-:,_#", line
    return line


def run(args):
    stem = "%s-%s-%s-a%d-r%d-n%d-l%d" % (
        args.arm, args.namespace, args.mode, args.atomic, args.resp3, args.notify, args.late)
    with (OUT / (stem + ".stderr")).open("w") as log:
        proc = subprocess.Popen([str(OUT / (args.arm + "-" + args.namespace)),
                                 str(int(args.mode == "fused")), str(args.atomic),
                                 str(args.resp3), str(args.notify), str(args.late)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        sock = file = None
        try:
            def target(argv):
                proc.stdin.write(encode(*argv)); proc.stdin.flush()
                return read_reply(proc.stdout)
            sides = [(stem, target)]
            if args.oracle_port:
                sock = socket.create_connection(("127.0.0.1", args.oracle_port), timeout=30)
                file = sock.makefile("rb")
                def oracle(argv):
                    sock.sendall(encode(*argv))
                    return read_reply(file)
                if args.resp3:
                    assert oracle(["HELLO", "3"]).startswith(b"%7\r\n")
                sides.append(("redis74", oracle))
            failures = aclcat_property(sides)
            failures += geo_store_property(sides, lambda keys: ownership(target, keys))
            proc.stdin.close()
            assert proc.wait(timeout=10) == 0, "serverless fixture failed"
        finally:
            if file: file.close()
            if sock: sock.close()
            if proc.poll() is None:
                proc.terminate(); proc.wait(timeout=10)
    print("CD13b %s: %d failures" % (stem, failures))
    return bool(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "run"))
    parser.add_argument("--arm", choices=("PRE", "POST"), default="POST")
    parser.add_argument("--namespace", choices=("multi", "db0"), default="multi")
    parser.add_argument("--mode", choices=("split", "fused"), default="split")
    parser.add_argument("--atomic", type=int, choices=(0, 1), default=1)
    parser.add_argument("--resp3", type=int, choices=(0, 1), default=0)
    parser.add_argument("--notify", type=int, choices=(0, 1), default=0)
    parser.add_argument("--late", type=int, choices=(0, 1), default=0)
    parser.add_argument("--oracle-port", type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == "build":
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(build_one, arm, ns)
                       for arm in ("PRE", "POST") for ns in ("multi", "db0")]
            for future in futures: future.result()
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
