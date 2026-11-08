#!/usr/bin/env python3
"""Build serverless negative controls for the exclusive admission/drain proof.

Only copies below this worktree's build directory are modified. The real unit
drives the production IO fence consumer and exclusive readiness predicate.
"""
import argparse
from pathlib import Path
import shlex
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control", choices=("unfenced", "undrained"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "build/txnfix2/admission-controls" / args.control
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "src", out / "src", dirs_exist_ok=True)
    source = out / "src/cmd/multi.inc"
    text = source.read_text()
    anchor = "if (fenced && server.atomic_apply_inflight() == 0) return true;"
    assert text.count(anchor) == 1, "review the changed exclusive readiness predicate"
    replacement = ("if (server.atomic_apply_inflight() == 0) return true;"
                   if args.control == "unfenced" else "if (fenced) return true;")
    source.write_text(text.replace(anchor, replacement))
    recipe = subprocess.check_output(
        ["make", "--no-print-directory", "-n", "-W", "tests/atomic_survivors_unit.cc",
         "build/atomic-survivors-unit"], cwd=root, text=True).replace("\\\n", " ")
    commands = [line for line in recipe.splitlines()
                if "tests/atomic_survivors_unit.cc" in line and " -o " in line]
    assert len(commands) == 1, "review the changed unit compile recipe"
    command = shlex.split(commands[0])
    command[command.index("-I.")] = "-I" + str(out)
    command += ["-I.", "-O0", "-g0"]
    command[command.index("-o") + 1] = str(out / "unit")
    print(shlex.join(command), flush=True)
    subprocess.run(command, cwd=root, check=True)
    return subprocess.run([str(out / "unit"), "txn_admission"], cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
