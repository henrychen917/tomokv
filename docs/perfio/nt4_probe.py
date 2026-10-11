#!/usr/bin/env python3
"""NT4.2 incidence only, using paper frame generators. Never compare rates of this observer build."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import info, encode
from perfio import boot


def snapshot(c, command):
    fields = info(c, "stats")
    cs = info(c, "commandstats")["cmdstat_" + command.lower()]
    calls = int(dict(item.split("=", 1) for item in cs.split(","))["calls"])
    return [int(fields["perfio_incomplete"]), int(fields["perfio_reparsed_arguments"]), calls]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--port", type=int, default=25127)
    ap.add_argument("--only", default="", help="optional exact generated cell name")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cert, key = args.output.resolve()/"cert.pem", args.output.resolve()/"key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                    "-nodes", "-days", "2", "-subj", "/CN=localhost", "-keyout", str(key),
                    "-out", str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    for mode in ("1s", "2s"):
        for command, size, depth, conns, tls in [("SET",1024,32,512,False), ("MSET",64,8,512,False),
                ("GET",4096,32,1,True), ("GET",16384,32,1,True),
                ("GET",4096,32,512,True), ("GET",16384,32,512,True)]:
            name = f"{mode}-{command}-{size}-p{depth}-c{conns}" + ("-tls" if tls else "")
            if args.only and args.only != name:
                continue
            opts = SimpleNamespace(binary=args.binary, output=args.output, port=args.port,
                cores="112-119", mode=mode, ratio="6:2", net_io="uring", oracle=False, read_local=0)
            extra = ["--key-lb", "1", "--client-lb", "1"]
            # boot() defaults to armed-fused for correctness. Incidence uses the paper rl=0.
            opts.mode = mode
            tlsflags = ["--tls-port", str(args.port+1), "--tls-auth-clients", "no",
                "--tls-protocols", "TLSv1.3", "--tls-cert-file", str(cert), "--tls-key-file", str(key)] if tls else []
            with boot(opts, name, extra + tlsflags) as (c,p):
                # Establish valid GET payloads; every setup reply is consumed before the baseline.
                if command == "GET":
                    for start in range(1,1025,64):
                        c.raw(b"".join(encode("SET", f"memtier-{i}", b"v"*size) for i in range(start,start+64)))
                        for _ in range(64): assert c.read() == b"OK"
                if command == "MSET": c.must("MSET", "memtier-1", "v")
                if command == "SET": c.must("SET", "memtier-1", "v")
                if command == "MSET":
                    # A directed split proves the observer can see the claimed path.
                    armed = info(c, "stats")
                    frame = encode("MSET", *[x for i in range(8) for x in (f"arm-{i}", "v")])
                    c.raw(frame[:-9])
                    time.sleep(.02)
                    c.raw(frame[-9:])
                    assert c.read() == b"OK"
                    fired = info(c, "stats")
                    assert int(fired["perfio_incomplete"]) > int(armed["perfio_incomplete"])
                    assert int(fired["perfio_reparsed_arguments"]) > int(armed["perfio_reparsed_arguments"])
                    print(json.dumps(dict(observer_control="PASS", mode=mode)), flush=True)
                before = snapshot(c, command)
                threads = 1 if conns == 1 else 4
                clients = conns//threads
                requests = (1_000_000+conns-1)//conns
                argv = ["taskset", "-c", "121-127", "memtier_benchmark", "-s", "127.0.0.1",
                    "-p", str(args.port+int(tls)), "--protocol=redis", "-t", str(threads), "-c", str(clients),
                    "--key-minimum=1", f"--key-maximum={1024 if tls else 2000000}",
                    f"--data-size={size}", f"--pipeline={depth}", f"--requests={requests}",
                    "--distinct-client-seed", "--hide-histogram", f"--json-out-file={args.output/name}.json"]
                if command == "MSET":
                    argv += ["--command=MSET " + " ".join(["__key__ __data__"]*8), "--command-key-pattern=P"]
                else: argv += ["--ratio=" + ("0:1" if command=="GET" else "1:0"), "--key-pattern=P:P"]
                if tls: argv += ["--tls", "--tls-protocols=TLSv1.3", "--tls-skip-verify"]
                with (args.output/(name+".load.log")).open("w") as log:
                    subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=100, check=True)
                after = snapshot(c,command)
                delta = [a-b for a,b in zip(after,before)]
                assert delta[2] >= 1_000_000, delta
                row = dict(name=name, argv=argv, before=before, after=after,
                    commands=delta[2], incomplete=delta[0], reparsed_arguments=delta[1],
                    incomplete_per_million=delta[0]*1e6/delta[2], arguments_per_million=delta[1]*1e6/delta[2])
                results.append(row)
                print(json.dumps(row), flush=True)
                (args.output/"results.json").write_text(json.dumps(results,indent=2)+"\n")
    (args.output/"binary.sha256").write_text(hashlib.sha256(args.binary.read_bytes()).hexdigest()+"\n")

if __name__ == "__main__": main()
