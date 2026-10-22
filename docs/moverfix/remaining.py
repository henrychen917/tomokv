#!/usr/bin/env python3
"""Serial correctness work; retain every result, including expected PRE failures."""
import json
import os
from pathlib import Path
import subprocess
import time

root = Path.cwd()
out = root / "docs/moverfix"
deadline = time.monotonic() + 1800
while not (out / "final-gate.rc").exists():
    assert time.monotonic() < deadline, "final POST gate did not finish"
    time.sleep(1)

rows = []
env = dict(os.environ, GATE_TEST_PORT="23879",
           PYTHONPATH=str(out / "port-scope"))

def run(name, command, environment=env):
    print("START", name, flush=True)
    with (out / (name + ".log")).open("w") as log:
        rc = subprocess.run(command, env=environment, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    (out / (name + ".rc")).write_text(str(rc) + "\n")
    rows.append(dict(name=name, argv=command, rc=rc))
    (out / "remaining-runs.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("DONE", name, rc, flush=True)

jobs = ("moverfix abba_selftest debug-0 debug-1 fused-0 fused-1 "
        "config_unit flip_unit filter_unit ring_unit storage_units atomic_units "
        "netcmd_units core_units flipfix_units lbplanner_units exbatch_units "
        "wb_rule_units wbland_units splitlocal_units wait_units perfex_units "
        "persistfix_units acl_metadata cmd_metadata reorder_sync "
        "reorder_engagement reorder_identity")
run("pre-gate", ["tests/gate.sh", "quick", "--server-cores", "80-88",
                 "--server-smt", "", "--load-cores", "89-95", "--load-smt", "",
                 "--ports", "23800-23877", "--candidate-binary",
                 str(root / "build/moverfix/pre/tomokv")],
    dict(env, GATE_ONLY_JOBS=jobs))
run("final-supplement", ["python3", "docs/moverfix/supplement.py"])
run("final-differ", ["python3", "docs/moverfix/differ.py"])
# Run after every compiler and live battery has ended; keep the original
# scheduler deadlines and assertions. The first busy-run failure is retained.
run("gates-test-quiet", ["taskset", "-c", "89-95", "python3", "tests/gates_test.py"])
# The unchanged count guard stops the ABBA job early. Execute its remaining
# serverless checks too, without bypassing that guard or calling this a green job.
checks = [("abba_instrument", ["--self-test"]),
          ("background_environment_test", []), ("gate_history", ["self-test"]),
          ("gate_process_test", []), ("gate_subset_test", []),
          ("wb_policy", ["--self-test"]), ("lb_stationary", ["--self-test"]),
          ("netio", ["--self-test"]), ("gateprod", ["--self-test"]),
          ("tailgen_stall", ["--self-test"])]
for name, args in checks:
    run("abba-tail-" + name,
        ["taskset", "-c", "89-95", "python3", "tests/" + name + ".py", *args])
