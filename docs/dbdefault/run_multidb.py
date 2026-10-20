"""Run the gate's eight multidb geometries as a focused correctness proof."""
from pathlib import Path
import json
import gzip
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "tests"))
from _gate_process import server, install_signals
install_signals()
out = root / "docs/dbdefault"
work = root / "build/dbdefault/multidb-proof"
work.mkdir(parents=True, exist_ok=True)
results = []

def run(name, argv, cpus="121-127"):
    command = ["taskset", "-c", cpus, *map(str, argv)]
    started = time.monotonic()
    with (out / (name + ".log")).open("w") as log:
        rc = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT).returncode
    results.append(dict(name=name, command=command, exit_code=rc, seconds=time.monotonic()-started))
    (out / "multidb-proof.json").write_text(json.dumps(results, indent=2) + "\n")
    print(name, rc, flush=True)
    return rc

for name, argv in [
    ("multidb-unit", ["build/multidb-unit"]),
    ("multidb-boundary-unit", ["build/multidb-boundary-unit"]),
    ("mdbqsbr-unit", ["python3", "tests/mdbqsbr_checks.py", "build/mdbqsbr-unit"]),
    ("multidb-serial-self-test", ["python3", "tests/multidb_serial.py", "--self-test"])]:
    run(name, argv, "112-119")

for mode in ("1s", "2s"):
    for local in (0, 1):
        for atomic in (0, 1):
            label = f"multidb-{mode}-rl{local}-a{atomic}"
            flags = ["--thread-mode", mode, "--shards", "16", "--databases", "16",
                "--read-local", str(local), "--atomic", str(atomic),
                "--appendonly", "yes", "--appendfsync", "no"]
            if mode == "2s":
                flags += ["--ratio", "6:2"]
            with server(root / "build/tomokv", "112-119", 25155, work / label, flags) as (conn, process):
                run(label, ["python3", "tests/multidb.py", "127.0.0.1", "25155",
                            "--read-local", local, "--persistence"])
                run(label + "-serial", ["python3", "tests/multidb_serial.py", "127.0.0.1", "25155",
                    "--output", out / (label + "-epochs.json")])
                epochs = out / (label + "-epochs.json")
                if epochs.exists():
                    epochs.with_suffix(".json.gz").write_bytes(gzip.compress(epochs.read_bytes(), mtime=0))
                    epochs.unlink()
            run(label + "-qsbr", ["python3", "tests/mdbqsbr_live.py", "--binary", root / "build/tomokv",
                "--parked-binary", root / "build/mdbqsbr2-park/tomokv",
                "--no-wake-binary", root / "build/mdbqsbr2-no-wake/tomokv", "--mode", mode,
                "--read-local", local, "--atomic", atomic, "--cores", "112-119", "--port", "25155",
                "--output", work / (label + "-qsbr")])
if any(row["exit_code"] for row in results):
    raise SystemExit(1)
