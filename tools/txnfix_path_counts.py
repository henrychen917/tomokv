#!/usr/bin/env python3
"""Summarize paired production-object instruction traces without accepting a cost bar.

These fixtures count selected functions, not all callees or instructions/op.
Fewer sampled instructions cannot establish universal sequence identity.
All instruction types, including executed NOPs, remain in the counts.
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("receipts", nargs="+", type=Path)
    args = parser.parse_args()
    cases = []
    invalid = []
    for folder in args.receipts:
        rows = json.loads((folder / "runs.json").read_text())
        paired = {}
        for row in rows:
            key = row["namespace"], row["mode"], row["values"]
            arms = paired.setdefault(key, {})
            assert row["arm"] not in arms, (folder, key, row["arm"])
            arms[row["arm"]] = row
        for key, arms in paired.items():
            if set(arms) != {"pre", "post"} or any(r["exit_code"] for r in arms.values()):
                invalid.append(dict(receipt=str(folder), case=key, arms=arms))
                continue
            pre, post = arms["pre"]["counts"], arms["post"]["counts"]
            functions = [dict(name=name, pre=pre.get(name, 0), post=post.get(name, 0),
                              delta=post.get(name, 0) - pre.get(name, 0))
                         for name in sorted(pre.keys() | post.keys())]
            cases.append(dict(receipt=str(folder), namespace=key[0], mode=key[1],
                              shape=key[2], functions=functions,
                              pre=sum(pre.values()), post=sum(post.values()),
                              increases=[r for r in functions if r["delta"] > 0],
                              group_calls=[r for r in functions if r["post"] and
                                           ("txn_group_" in r["name"] or
                                            "ScatterState::group_attempt(" in r["name"])]))
    result = dict(cases=len(cases), invalid=invalid,
                  cases_with_increases=sum(bool(r["increases"]) for r in cases),
                  cases_entering_group_helpers=sum(bool(r["group_calls"]) for r in cases),
                  limits="Sampled named-function counts; neither whole-operation counts "
                         "nor a proof of identical sequences on every ordinary path.",
                  rows=cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "invalid")}))
    if invalid:
        raise SystemExit("invalid or incomplete paired fixtures retained in output")


if __name__ == "__main__":
    main()
