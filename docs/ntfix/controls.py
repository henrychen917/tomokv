#!/usr/bin/env python3
"""Observe out-of-scope TLS-gauge and AUTH/arity findings on frozen PRE and POST."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ntfix_proof import Conn, encode, outcome, pair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gauges", action="store_true",
                        help="five fresh fused boots per arm, with unchanged TLS assertions")
    args = parser.parse_args()
    out = ROOT / ("docs/ntfix/ntfix2/controls-gauges" if args.gauges else
                  "docs/ntfix/ntfix2/controls")
    cert = ROOT / "build/ntfix-certs"
    rows = []
    for arm, binary in (("pre", ROOT / "build/ntfix-pre/tomokv"),
                        ("post", ROOT / "build/tomokv")):
        jobs = [("1s", n) for n in range(1, 6)] if args.gauges else [("1s", 1), ("2s", 1)]
        for mode, repeat in jobs:
            label = f"{arm}-{mode}-epoll" + (f"-r{repeat}" if args.gauges else "")
            directory = out / label
            with pair(binary, mode, "epoll", directory, cert):
                command = ["taskset", "-c", "105-111", "python3", "tests/tls.py",
                           "127.0.0.1", "25801", str(cert), "no",
                           "--plain-port", "25800", "--full"]
                if args.gauges:
                    command = ["taskset", "-c", "105-111", "python3",
                               "docs/ntfix/tls_gauges.py", str(directory / "gauges.json")]
                with (directory / "tls-default.log").open("w") as log:
                    result = subprocess.run(command, cwd=ROOT, stdout=log,
                                            stderr=subprocess.STDOUT)
                row = dict(arm=arm, mode=mode, repeat=repeat, command=command,
                           binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                           returncode=result.returncode)
                rows.append(row)
                print(f"{label} default-cipher epoll TLS: rc={result.returncode}", flush=True)
                if args.gauges:
                    (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
                    continue
                arity = []
                for label, port in (("candidate", 25800), ("oracle", 25802)):
                    admin = Conn("127.0.0.1", port)
                    try:
                        assert admin.must("CONFIG", "SET", "requirepass", "secret") == b"OK"
                        reply, closed = outcome(port, [encode("PING", *(["x"] * 9))])
                        arity.append(dict(server=label, reply=reply.decode("latin1"), closed=closed))
                    finally:
                        assert admin.must("CONFIG", "SET", "requirepass", "") == b"OK"
                        admin.close()
                (directory / "auth-arity.json").write_text(json.dumps(arity, indent=2) + "\n")
            (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    # These observations are not passing-test assertions or acceptance waivers.


if __name__ == "__main__":
    main()
