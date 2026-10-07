#!/usr/bin/env python3
"""Archive completed partial gates; never turn missing or failed evidence into a pass."""
from collections import Counter
from datetime import datetime, timezone, timedelta
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
    campaign = (ROOT / "build/flakeaudit/resume-campaign.log").read_text()
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
        plan = set((artifact / "plan.sh").read_text().splitlines())
        required_geometry = {"GATE_SERVER_CORES=112-119", "GATE_LOAD_CORES=120-127",
                             "GATE_SERVER_SMT=''", "GATE_LOAD_SMT=''", "GATE_RATIO=6:2",
                             "GATE_SLOTS=1", "GATE_PORT_FIRST=18340", "GATE_PORT_LAST=18342"}
        assert required_geometry <= plan, f"wrong proof geometry: {required_geometry - plan}"
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
                    "gate-tracking-*.txt", "gate-fusedarmed-limits-*.txt",
                    "gate-fusedarmed-climon2-*.txt", "gate-fusedarmed-tracking-*.txt",
                    "epoll.log", "uring.log", "gate-debug.txt",
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
                            completed=f"Completed repetition {run} at " in campaign,
                            sha256=(SOURCE / f"run-{run}.server.sha256").read_text().split()[0]))
    (DEST / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (DEST / "campaign.log").write_text(campaign)
    clean = [r for r in results if r["failed"] == 0 and not r["missing"] and r["completed"]]
    complete = len(clean) == 6 and [r["run"] for r in clean] == list(range(1, 7))
    if complete:
        assert len({r["sha256"] for r in results}) == 1, "server changed during proof"
    text = [f"Six-run live campaign: **{'6/6 PASS' if complete else str(len(clean)) + '/6 complete; IN PROGRESS'}**.", "",
            "Every completed clean selection includes all 34 changed row occurrences. "
            "The table counts complete selected jobs and prerequisites; it is not a full-gate receipt.", "",
            "| Run | Gate artifact | Start–end (Asia/Taipei) | Rows ok / FAIL | Changed rows passed |",
            "|---:|---|---|---:|---:|"]
    zone = timezone(timedelta(hours=8))
    for result in results:
        start = datetime.fromtimestamp(result["phases"]["begin"], zone).strftime("%H:%M:%S")
        end = datetime.fromtimestamp(result["phases"]["end"], zone).strftime("%H:%M:%S")
        text.append(f"| {result['run']} | `{result['artifact']}` | {start}–{end} | "
                    f"{result['ok']} / {result['failed']} | {result['changed_passed']} / 34 |")
    text += ["", "Tracked [results and provenance](docs/flakeaudit/evidence/proof/results.json) "
             "link each run to its revision, unchanged server hash, ledger, phase timestamps and geometry. "
             "The adjacent run directories retain the complete gate log and the relevant battery logs. "
             "`archive_proof.py` refuses changed executable sources and cross-checks every changed row's multiplicity."]
    report = ROOT / "MEASURE-REQUEST-flakeaudit.md"
    source = report.read_text()
    source, count = re.subn(r"(?<=<!-- PROOF_RESULTS_BEGIN -->\n).*?(?=\n<!-- PROOF_RESULTS_END -->)",
                            lambda _: "\n".join(text), source, flags=re.S)
    assert count == 1
    report.write_text(source)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
