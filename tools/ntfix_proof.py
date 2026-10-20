#!/usr/bin/env python3
"""Lane ntfix correctness receipts. Only CPUs 96-111 and ports 25800-25803.

Boots an explicitly selected candidate and the pinned Redis 7.4 oracle. No gate,
benchmark, or load generator. All children are stopped by their owned PIDs.
"""
import argparse
import contextlib
import gzip
import hashlib
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn, encode
import respresume_limits as limits


def connect(port, tls=False):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(s, server_hostname="localhost")
    return s


def outcome(port, pieces, tls=False):
    received, closed = b"", False
    with connect(port, tls) as s:
        for piece in pieces:
            try:
                s.sendall(piece)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                closed = True
                break
            time.sleep(.02)
        s.settimeout(1)
        while True:
            try:
                data = s.recv(65536)
            except socket.timeout:
                break
            except (ConnectionResetError, ssl.SSLEOFError):
                closed = True
                break
            if not data:
                closed = True
                break
            received += data
    return received, closed


@contextlib.contextmanager
def pair(binary, mode, engine, out, cert):
    out.mkdir(parents=True, exist_ok=True)
    procs = []
    files = []
    tls = ["--tls-cert-file", str(cert / "server.crt"),
           "--tls-key-file", str(cert / "server.key"),
           "--tls-ca-cert-file", str(cert / "ca.crt"), "--tls-auth-clients", "no"]
    shape = (["--thread-mode", "fused", "--read-local", "1"] if mode == "1s"
             else ["--thread-mode", "2s", "--ratio", "6:2"])
    arms = [
        ("candidate", "96-103", binary, 25800, 25801,
         ["--shards", "16", "--net-io", engine, *shape]),
        ("redis", "104", "/home/user/Projects/redis74/src/redis-server",
         25802, None, []),
    ]
    try:
        for label, cores, exe, port, tlsport, extra in arms:
            for p in ([port, tlsport] if tlsport else [port]):
                with socket.socket() as guard:
                    guard.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    guard.bind(("127.0.0.1", p))
            data = out / (label + "-data")
            data.mkdir(exist_ok=True)
            log = (out / (label + ".log")).open("w")
            files.append(log)
            command = ["taskset", "-c", cores, str(exe), "--databases", "1",
                       "--bind", "127.0.0.1", "--port", str(port),
                       "--save", "", "--appendonly", "no", "--dir", str(data),
                       *(["--tls-port", str(tlsport), *tls] if tlsport else []), *extra]
            (out / (label + "-command.json")).write_text(json.dumps(command) + "\n")
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            procs.append(proc)
            deadline = time.monotonic() + 15
            while True:
                assert proc.poll() is None, f"{label} died; see {log.name}"
                try:
                    with connect(port):
                        pass
                    break
                except OSError:
                    assert time.monotonic() < deadline, f"{label} boot timeout"
                    time.sleep(.05)
        yield
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for f in files:
            f.close()


def reproduce(out):
    rows = []
    for label, port in (("candidate", 25800), ("redis", 25802)):
        c = Conn("127.0.0.1", port)
        def net_input():
            body = c.must("INFO", "STATS")
            fields = dict(line.split(b":", 1) for line in body.split(b"\r\n") if b":" in line)
            return int(fields[b"total_net_input_bytes"])
        before = net_input()
        assert c.must("PING") == b"PONG"
        delta = net_input() - before
        rows.append(dict(defect="N1", server=label, delta=delta,
                         expected=len(encode("PING")) + len(encode("INFO", "STATS"))))
        c.close()
        for tls in (False, True):
            # The pinned oracle is built without TLS, as in the inherited corpus:
            # compare the candidate's decrypted RESP stream to Redis over TCP.
            wire_tls = tls and label == "candidate"
            for name, payload in (("protocol error", b"*x\r\n"), ("QUIT", encode("QUIT")),
                                  ("PING control", encode("PING"))):
                reply, closed = outcome(port + wire_tls, [payload], wire_tls)
                rows.append(dict(defect="N2", server=label, tls=tls, case=name,
                                 reply=reply.decode("latin1"), closed=closed))
            admin = Conn("127.0.0.1", port)
            original = admin.must("CONFIG", "GET", "client-query-buffer-limit")[1]
            with gzip.open(out / f"limits-{label}-{'tls' if tls else 'tcp'}.jsonl.gz", "wt") as f:
                for group, name, pieces in limits.cases():
                    field, value, reset = (("client-query-buffer-limit", "1mb", original)
                                          if group == "qbuf" else ("requirepass", "secret", ""))
                    assert admin.must("CONFIG", "SET", field, value) == b"OK"
                    try:
                        reply, closed = outcome(port + wire_tls, pieces, wire_tls)
                    finally:
                        assert admin.must("CONFIG", "SET", field, reset) == b"OK"
                    row = dict(server=label, tls=tls, group=group, case=name,
                               closed=closed, reply=reply.decode("latin1"))
                    f.write(json.dumps(row) + "\n")
                    rows.append(dict(defect="N3" if group == "preauth" else "N4",
                                     **{k: v for k, v in row.items() if k != "reply"},
                                     reply_bytes=len(reply), reply_sha256=hashlib.sha256(reply).hexdigest(),
                                     reply_prefix=reply[:100].decode("latin1")))
            admin.close()
    (out / "reproduction.json").write_text(json.dumps(rows, indent=2) + "\n")
    cand = [r for r in rows if r["server"] == "candidate"]
    oracle = [r for r in rows if r["server"] == "redis"]
    differences = []
    for a, b in zip(cand, oracle, strict=True):
        if {k: v for k, v in a.items() if k != "server"} != {
                k: v for k, v in b.items() if k != "server"}:
            differences.append(dict(candidate=a, redis=b))
    (out / "differences.json").write_text(json.dumps(differences, indent=2) + "\n")
    print(f"{out.name}: {len(differences)} differences", flush=True)
    return len(differences)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--expect-equal", action="store_true")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cert = ROOT / "build/ntfix-certs"
    if not (cert / "server.crt").exists():
        subprocess.run(["taskset", "-c", "105-111", "python3", "tests/tls.py",
                        "--generate", str(cert)], cwd=ROOT, check=True)
    total = 0
    for mode in ("1s", "2s"):
        for engine in ("uring", "epoll"):
            cell = out / f"{mode}-{engine}"
            with pair(args.binary.resolve(), mode, engine, cell, cert):
                total += reproduce(cell)
    if args.expect_equal:
        assert total == 0, f"{total} differences"


if __name__ == "__main__":
    main()
