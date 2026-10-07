#!/usr/bin/env python3
"""Archive completed partial gates; never turn missing or failed evidence into a pass."""
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "build/flakeaudit/proof"
DEST = ROOT / "docs/flakeaudit/evidence/proof"


def main():
    changed = json.loads((ROOT / "docs/flakeaudit/changed-rows.json").read_text())
    required = Counter(row["name"] for row in changed)
    jobs = {row["job"] for row in changed}
    results = []
    DEST.mkdir(parents=True, exist_ok=True)
    for run in range(1, 7):
        logfile = SOURCE / f"run-{run}.log"
        if not logfile.exists():
            continue
        log = logfile.read_text()
        summary = re.search(r"GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL", log)
        if not summary:
            continue
        artifact = Path(re.search(r"  artifacts: (\S+)", log)[1])
        ledger = SOURCE / f"run-{run}-ledger.partial"
        rows = [line.split("\t", 2) for line in ledger.read_text().splitlines()
                if not line.startswith("PARTIAL\t")]
        passed = Counter(label for verdict, _, label in rows if verdict == "ok")
        assert (int(summary[1]), int(summary[2])) == (
            sum(verdict == "ok" for verdict, _, _ in rows),
            sum(verdict == "FAIL" for verdict, _, _ in rows)), "summary/ledger mismatch"
        missing = required - passed
        revision = (SOURCE / f"run-{run}.revision").read_text().strip()
        # Documentation commits during the campaign must not change tested executable sources.
        test_diff = subprocess.check_output(
            ["git", "diff", revision, "HEAD", "--", "tests", "src", "Makefile"], cwd=ROOT)
        assert not test_diff, f"tested sources changed since run {run}"
        out = DEST / f"run-{run}"
        out.mkdir(exist_ok=True)
        for path in SOURCE.glob(f"run-{run}*"):
            shutil.copy2(path, out / path.name)
        for name in ("plan.sh", "phases.tsv"):
            shutil.copy2(artifact / name, out / name)
        patterns = ["output.log", "ledger", "gate-limits-*.txt", "gate-climon2-*.txt",
                    "gate-tracking-*.txt", "gate-netio*.txt", "gate-debug.txt",
                    "gate-snap-typed.txt", "gate-snapshot-cut-*.txt", "gate-aof*.txt",
                    "multidb.log"]
        for job in sorted(jobs):
            directory = artifact / "jobs" / job
            assert directory.is_dir(), f"missing selected job {job}"
            target = out / "jobs" / job
            target.mkdir(parents=True, exist_ok=True)
            for pattern in patterns:
                for path in directory.glob(pattern):
                    if path.is_file():
                        shutil.copy2(path, target / path.name)
        times = {}
        for line in (artifact / "phases.tsv").read_text().splitlines():
            name, stamp = line.split("\t")
            times[name] = float(stamp)
        results.append(dict(run=run, artifact=artifact.name, revision=revision,
                            origin=(SOURCE / f"run-{run}.origin").read_text().strip(),
                            ok=int(summary[1]), failed=int(summary[2]),
                            changed_passed=sum(required.values()) - sum(missing.values()),
                            missing=dict(missing), phases=times,
                            sha256=(SOURCE / f"run-{run}.server.sha256").read_text().split()[0]))
    (DEST / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
