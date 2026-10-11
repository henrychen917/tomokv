#!/usr/bin/env python3
"""Run the read-only round-4 PRE venues at this lane's assigned geometry.

Only paths, CPU/port assignments and the explicit gate geometry are adapted.
The venue assertions are unchanged; these are PRE reproduction tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = Path("/home/user/Projects/round4-read/tests/read-local")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    copies = output / "source"
    copies.mkdir(exist_ok=True)
    helper = (source / "rl4lib.py").read_text()
    helper = helper.replace('TOMO = "/home/user/Projects/bench-bins/tomokv-headline-6b50f447f"',
                            "TOMO = " + repr(str(args.binary.resolve())))
    helper = helper.replace('REDIS = "/tmp/claude-1000/redis74/src/redis-server"',
                            'REDIS = "/home/user/Projects/redis74/src/redis-server"')
    helper = helper.replace('CORES = "96-111"', 'CORES = "48-55"')
    helper = helper.replace("PORT_LO, PORT_HI = 22300, 22399", "PORT_LO, PORT_HI = 25600, 25699")
    helper = helper.replace("set(range(96, 112))", "set(range(57, 64))")
    helper = "\n".join("LOGDIR = " + repr(str(output)) if line.startswith("LOGDIR = ")
                       else line for line in helper.splitlines()) + "\n"
    helper = helper.replace('["taskset", "-c", CORES, self.binary,',
                            '["taskset", "-c", "56" if self.kind == "redis" else CORES, self.binary,')
    helper = helper.replace("return base + self.args", """if self.kind == "tomo":
            base += ["--shards", "16"]
            if "1s" not in self.args:
                base += ["--ratio", "6:2"]
        return base + self.args""")
    (copies / "rl4lib.py").write_text(helper)
    receipt = {"binary": str(args.binary.resolve()), "sources": {}, "runs": []}
    for name in ("rl4lib.py", "t02_miss_type_expiry.py", "t04b_write_precision_matrix.py",
                 "t04c_del_demotes_older_reads.py"):
        original = (source / name).read_bytes()
        receipt["sources"][name] = hashlib.sha256(original).hexdigest()
        if name == "rl4lib.py":
            continue
        text = original.decode().replace("PORT = 22302", "PORT = 25602")
        text = text.replace("PORT = 22305", "PORT = 25605").replace("PORT = 22306", "PORT = 25606")
        script = copies / name
        script.write_text(text)
        command = ["taskset", "-c", "57-63", sys.executable, str(script)]
        with (output / (script.stem + ".log")).open("w") as log:
            run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        receipt["runs"].append(dict(command=command, exit_code=run.returncode))
        print(name, run.returncode, flush=True)
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return any(row["exit_code"] for row in receipt["runs"])


if __name__ == "__main__":
    raise SystemExit(main())
