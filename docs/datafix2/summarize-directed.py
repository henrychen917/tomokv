#!/usr/bin/env python3
"""Inventory the gate-owned directed legs; never turn a failure into a pass."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
EXPECTED = {
    f"db{db}-{mode}-{engine}-a{atomic}-rl{read_local}"
    for db in (1, 16)
    for atomic in (0, 1)
    for engine in ("epoll", "uring")
    for mode, read_local in (("1s", 1), ("1s", 0), ("2s", 0))
}


def inventory(prefix, feature):
    log = DOC / (prefix + "gate.log")
    paths = re.findall(r"/[^\s:]+/build/gate-run\.[A-Za-z0-9]+", log.read_text())
    run = Path(paths[0])
    legs = []
    for path in sorted((run / "jobs" / ("datafix2_" + feature)).glob(feature + "-db*.log")):
        lines = path.read_text(errors="replace").splitlines()
        leg = dict(
            geometry=path.stem.removeprefix(feature + "-"),
            file=str(path.relative_to(run)),
            sha256=hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
            oracle_completed=any(line.startswith("ORACLE {") for line in lines),
            target_started=any(line.startswith("GEOMETRY ") for line in lines),
            passed=("PASS " + feature) in lines,
            errors=[line[:1200] for line in lines if line.startswith(("AssertionError", "TimeoutError", "ConnectionError"))],
        )
        if feature == "watch":
            cases = [{}, {}]
            coverage = [[], []]
            phase = 0
            for line in lines:
                if line.startswith("GEOMETRY "):
                    phase = 1
                elif line.startswith("COVERAGE "):
                    coverage[phase] = json.loads(line[9:])
                elif line.startswith("CASE "):
                    case = json.loads(line[5:])
                    cases[phase][case["case"]] = case["dirty"]
            differences = [key for key in cases[0] if key in cases[1] and cases[0][key] != cases[1][key]]
            leg.update(
                command_counts=[len(c) for c in coverage],
                table_case_counts=[len(c) for c in cases],
                table_missing_in_target=sorted(cases[0].keys() - cases[1].keys()),
                table_mismatches=len(differences),
                mismatch_examples=[dict(case=key, oracle=cases[0][key], target=cases[1][key]) for key in differences[:4]],
            )
        legs.append(leg)
    return dict(
        log=str(log.relative_to(ROOT)),
        archive=str((DOC / (prefix + "gate-evidence.tar.gz")).relative_to(ROOT)),
        expected_legs=len(EXPECTED),
        present_legs=len(legs),
        missing=sorted(EXPECTED - {leg["geometry"] for leg in legs}),
        oracle_completed=sum(leg["oracle_completed"] for leg in legs),
        target_started=sum(leg["target_started"] for leg in legs),
        passes=sum(leg["passed"] for leg in legs),
        legs=legs,
    )


result = {}
for feature in ("notouch", "encoding", "subkeys", "watch", "idle"):
    pre = "pre-final-v2-" if feature in ("watch", "idle") else "pre-final-directed-"
    result[feature] = {"PRE": inventory(pre, feature), "POST": inventory("post-final-v2-directed-", feature)}
(DOC / "directed-summary.json").write_text(json.dumps(result, indent=2) + "\n")
for feature, arms in result.items():
    print(feature, {arm: dict(legs=data["present_legs"], oracle=data["oracle_completed"], passes=data["passes"])
                    for arm, data in arms.items()})
