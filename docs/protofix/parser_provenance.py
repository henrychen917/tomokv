#!/usr/bin/env python3
"""Bind each counted out-of-line parser/helper body to the production binary."""
import json
import os
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/protofix"
os.sched_setaffinity(0, set(range(8, 16)))
scope = runpy.run_path(str(ROOT / "docs/wave8/identity.py"), run_name="parser_provenance")
scope["inventory"].__globals__["OUT"] = ROOT / "build/protofix/linked-identity"
result = {}
for arm, production in (("pre", ROOT / "build/protofix/pre-source/build/tomokv"),
                        ("post", ROOT / "build/tomokv")):
    probe = ROOT / "build/protofix/parser-commands" / (arm + "-normal/probe")
    names = {scope["audit"].canonical(name)
             for path in (DOC / "parser-instructions").glob(arm + "-normal-*.json")
             for name in json.loads(path.read_text())["functions"]
             if "protofix_parse_scope" not in name}
    assert names
    actual = scope["inventory"](production)
    # This standalone parser has no executor policies. Require every entered
    # parser/helper instead; retain the complete strict instruction normalizer.
    def require_parser_inventory(defined):
        present = {scope["audit"].canonical(name) for name in defined}
        assert names <= present, ("missing counted parser body", names - present)
    try:
        require_parser_inventory(())
    except AssertionError:
        pass
    else:
        raise AssertionError("missing-body control passed")
    original = scope["audit"].require_policies
    scope["audit"].require_policies = require_parser_inventory
    try:
        fixture = scope["inventory"](probe)
    finally:
        scope["audit"].require_policies = original
    rows = []
    for name in sorted(names):
        before, after = actual["groups"].get(name), fixture["groups"].get(name)
        equal = bool(before and after) and scope["signature"](before) == scope["signature"](after)
        rows.append(dict(name=name, production=before, fixture=after, equal=equal))
    result[arm] = dict(production_sha256=actual["sha256"], fixture_sha256=fixture["sha256"],
                       inventory="All counted parser/helpers required; standalone fixture has no executor policies",
                       missing_body_control="rejected", bodies=rows)
(DOC / "parser-provenance.json").write_text(json.dumps(result, indent=2) + "\n")
assert all(row["equal"] for arm in result.values() for row in arm["bodies"]), result
print("PASS every counted out-of-line parser/helper body equals its production body")
