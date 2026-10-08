#!/usr/bin/env python3
"""Run the real wire property against directed responses and in-memory controls.

No listener, production binary, or server source is changed. Each removed guard
must be caught by its specific test, not an unrelated import/fixture failure.
"""
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import cd13b_window_test as controls

POST = (ROOT / "tests/cd13b_wire.py").read_text()
PRE = subprocess.check_output(["git", "show", "origin/cpp:tests/cd13b_wire.py"], cwd=ROOT, text=True)


def run(source, method=None):
    namespace = {"__name__": "cd13b_in_memory_control"}
    exec(compile(source, "<cd13b-in-memory-control>", "exec"), namespace)
    controls.geo_store_property = namespace["geo_store_property"]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(controls.PlacementWindow) if method is None else \
        unittest.TestSuite([controls.PlacementWindow(method)])
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result, stream.getvalue()


def main():
    results = []
    result, log = run(POST)
    print("POST\n" + log)
    assert result.wasSuccessful(), "POST controls failed"
    results.append(dict(arm="POST", tests=result.testsRun, passed=True))
    methods = {
        "route": "test_perpetual_post_store_migration_never_passes",
        "deadline": "test_deadline_cannot_accept_an_otherwise_valid_store",
        "semantic": "test_bad_store_is_never_retried_even_when_route_moved",
    }
    arms = [
        ("PRE route-stability assertion", PRE,
         "test_source_moves_during_store_require_fresh_stable_cross_owner_arm"),
        ("accept changed route", POST.replace("if after_witness == witness:", "if True:"), methods["route"]),
        ("remove completion deadline", POST.replace(
            'assert time.monotonic() < deadline, "STORE checks exhausted window budget"', 'pass'), methods["deadline"]),
    ]
    for name, statement in (
        ("store count", 'assert stored == b":2\\r\\n", stored'),
        ("destination LFU", 'assert after > initial, ("destination LFU reset", initial, before, after)'),
        ("destination encoding", 'assert encoding == b"$8\\r\\nlistpack\\r\\n", encoding'),
        ("destination members", 'assert isinstance(members, list) and sorted(members) == [b"a", b"b"], members'),
    ):
        assert POST.count(statement) == 1, (name, "control target absent/ambiguous")
        arms.append(("remove " + name, POST.replace(statement, 'pass'), methods["semantic"]))
    for name, source, method in arms:
        assert source != POST, (name, "control did not alter source")
        result, log = run(source, method)
        print(name + "\n" + log)
        assert result.failures and not result.errors, (name, "did not fail the intended assertion", log)
        results.append(dict(arm=name, method=method, tests=result.testsRun,
                            expected_assertion_failures=len(result.failures), unexpected_errors=0))
    (ROOT / "docs/flakeaudit3/evidence/control-results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
