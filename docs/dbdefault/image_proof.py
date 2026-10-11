"""Read-only GDB stack names witness the image selected at each correctness boot."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "tests"))
from _gate_process import server, info
from dbdefault import check

out = root / "docs/dbdefault/images"
out.mkdir(parents=True, exist_ok=True)
results = []
for config in (False, True):
    for mode in ("1s", "2s"):
        for count in (None, 1):
            label = f'{"conf" if config else "default"}-{mode}-{count or 16}'
            # The generic helper places argv before its args, whereas a config path
            # must be first. A tiny owned wrapper inserts only that positional path.
            binary = root / "build/tomokv"
            if config:
                wrapper = root / "build/dbdefault/conf-server"
                wrapper.write_text('#!/bin/bash\nexec ' + str(binary) + ' ' + str(root / 'tomokv.conf') + ' "$@"\n')
                wrapper.chmod(0o755)
                binary = wrapper
            flags = ["--thread-mode", mode, "--shards", "16"]
            if mode == "2s":
                flags += ["--ratio", "6:2"]
            with server(binary, "112-119", 25154, out / label, flags, databases=count) as (conn, process):
                row = dict(label=label, **check(conn, count or 16))
                argv = ["gdb", "-nx", "-batch", "-p", str(process.pid), "-ex", "thread apply all bt 8"]
                result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
                (out / label / "stacks.txt").write_text(result.stdout)
                wanted = "tomo_db0::" if count == 1 else "tomo::"
                other = "tomo::" if count == 1 else "tomo_db0::"
                row.update(gdb_exit=result.returncode, image=wanted, namespace_witness=wanted in result.stdout,
                           other_namespace_present=other in result.stdout)
                assert result.returncode == 0 and wanted in result.stdout and other not in result.stdout, row
                results.append(row)
                (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                print(label, wanted, flush=True)
