#!/usr/bin/env python3
"""Read-only gate inventory; never execute shell declarations or a battery."""
from collections import Counter
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import gate_ledger_fixture as fixture


def rows():
    gate = (ROOT / "tests/gate.sh").read_text()
    lines = gate.splitlines()
    annotated = []
    for number, line in enumerate(lines, 1):
        if re.match(r"\s*row_begin\s", line) and not 1190 <= number <= 1200:
            annotated.append("_audit_line=" + str(number))
        annotated.append(line)
    records, jobs = [], []

    def evaluate(nodes, values, collect):
        labels = []
        for kind, *args in nodes:
            if kind == "for":
                name, words, children = args
                if fixture.emits(children):
                    for word in shlex.split(fixture.expand(words, values)):
                        labels += evaluate(children, dict(values, **{name: word}), collect)
            elif kind == "assign":
                try:
                    values[args[0]] = fixture.expand(args[1], values)
                except ValueError:
                    values[args[0]] = None
            elif kind == "split":
                names, expression = args
                values.update(zip(names, fixture.expand(expression, values).split("-", len(names) - 1)))
            elif kind == "collect_job":
                name = fixture.expand(args[0], values)
                jobs.append(name)
                start = len(records)
                result = collect(name)
                if len(records) == start:
                    site = 865 if name.startswith("differ-") else 882 if name.startswith("evict-") else 890
                    for label in result:
                        records.append(dict(name=label, job=name, gate_line=site, values={}))
                jobs.pop()
                labels += result
            elif kind == "row_begin":
                label = re.sub(r"suppressed=\$TLS_ZC\b", "suppressed=N", args[0])
                label = fixture.canonical_label(fixture.expand(label, values))
                labels.append(label)
                records.append(dict(name=label, job=jobs[-1] if jobs else "coordinator",
                                    gate_line=int(values.get("_audit_line") or 1191), values=dict(values)))
        return labels

    original = fixture.evaluate
    try:
        fixture.evaluate = evaluate
        labels = fixture.source_labels("\n".join(annotated))
    finally:
        fixture.evaluate = original
    expected = fixture.source_labels(gate)
    assert labels == expected == [r["name"] for r in records]
    fixture.check(gate, labels)
    for row in records:
        number = row["gate_line"]
        end = next((i for i in range(number, len(lines)) if re.match(r"\s*row_begin\s", lines[i])), len(lines))
        body = "\n".join(lines[number:end])
        paths = re.findall(r"tests/[\w$./{}-]+\.(?:py|sh|cc)", body)
        resolved = []
        for path in paths:
            try:
                path = fixture.expand(path, row["values"])
            except ValueError:
                continue
            if (ROOT / path).is_file() and path not in resolved:
                resolved.append(path)
        row["scripts"] = resolved
        del row["values"]
    return records


if __name__ == "__main__":
    result = rows()
    (ROOT / "docs/flakeaudit/rows.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Gate rows:", len(result), "jobs:", len(set(r["job"] for r in result)))
    print("\n".join(sorted(set(p for r in result for p in r["scripts"]))))
