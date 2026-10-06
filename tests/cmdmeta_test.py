#!/usr/bin/env python3
"""Serverless controls for the generator and the cmdmeta differential's surface assertions.

The scripted peers below test the TEST, not Redis or TomoKV wire behavior. Live differential
results must still come from the maintainer's harness and pinned vanilla oracle.
"""
import ast
import contextlib
import copy
import io
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import gen_cmdmeta as generator
import cmdmeta_coverage as coverage_check

REDIS = Path(os.environ.get("REDIS74_ROOT", "/tmp/claude-1000/redis74"))


def surface_fixture():
    """Independent oracle inventory from pinned JSON, plus registry-based target membership."""
    rows = {}
    for parent in generator.redis_json_commands(REDIS):
        rows[parent[0]] = parent
        rows.update((child[0], child) for child in parent[9])
    registry = {name.lower().encode() for name in coverage_check.registered_commands()}
    target = {name: row for name, row in rows.items() if name.split(b"|", 1)[0] in registry}
    target[b"flip"] = generator.local_commands()[0]
    return target, rows


class Peer:
    def __init__(self, rows, target, fault=None):
        self.rows, self.target, self.fault = rows, target, fault
        self.pending = None

    def sendall(self, argv):
        self.pending = [value.encode() if isinstance(value, str) else value for value in argv]

    def close(self):
        pass

    def read(self):
        from fnmatch import fnmatchcase
        argv = self.pending
        verb = argv[0].upper()
        if verb == b"INFO":
            return b"redis_version:7.4.10\r\n"
        if verb == b"ACL":
            if len(argv) == 2:
                return [name.encode() for name in generator.ACL_CATEGORIES]
            return [name for name, row in self.rows.items() if b"@" + argv[2].lower() in row[6]]
        assert verb == b"COMMAND", argv
        sub = argv[1].upper()
        if sub == b"COUNT":
            count = len(self.rows) if self.fault == "count-subcommands" else sum(b"|" not in n for n in self.rows)
            return b":%d" % count
        if sub == b"LIST":
            if len(argv) == 2:
                return list(self.rows)
            kind, value = argv[3].upper(), argv[4].lower()
            if kind == b"PATTERN":
                if self.fault == "empty-oracle-family" and value in (b"cluster*", b"module*"):
                    return []
                return [n for n in self.rows if fnmatchcase(n.decode(), value.decode())]
            if kind == b"ACLCAT":
                if self.fault == "empty-acl-filter" and value == b"read":
                    return []
                return [n for n, row in self.rows.items() if b"@" + value in row[6]]
            if kind == b"MODULE":
                return [b"get"] if self.fault == "module-leak" else []
        name = argv[2].lower()
        if sub == b"INFO":
            return [self.rows.get(name)]
        if sub == b"DOCS":
            if name == b"config|get":
                return (b"tomokv compatible config|get command" if self.target else b"Returns the effective values")
            if name not in self.rows:
                return None if self.fault == "nil-docs" else []
            return [name, [b"summary", b"fixture"]]
        if sub == b"GETKEYSANDFLAGS":
            return b"key-intent-fixture"  # Only the surface assertions are under test here.
        raise AssertionError(argv)


def run_surface(target, oracle, target_fault=None, oracle_fault=None):
    # Compile ONLY the property function; importing differ.py would attempt live connections.
    tree = ast.parse((ROOT / "tests/differ.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_cmdmeta_suite")
    peers = {"target": Peer(target, True, target_fault), "oracle": Peer(oracle, False, oracle_fault)}
    class Coverage:
        @staticmethod
        def note(_argv):
            pass
    scope = dict(TH="target", TP=0, OH="oracle", OP=0, coverage=Coverage(),
                 conn=lambda host, _port: (peers[host], peers[host]), enc=lambda argv: argv,
                 read_reply=lambda peer: peer.read(), parse_reply=lambda value: value)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "differ.py:cmdmeta", "exec"), scope)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        diffs = scope["run_cmdmeta_suite"](random.Random(7))
    return diffs, output.getvalue()


class CmdmetaTests(unittest.TestCase):
    def test_regenerate(self):
        self.assertEqual(generator.generated_text(ROOT, redis_root=REDIS),
                         coverage_check.GENERATED.read_text())

    def test_drift_checker_rejects_corruption(self):
        (ROOT / "build/cmdmeta").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build/cmdmeta") as directory:
            mutated = Path(directory) / "metadata.inc"
            original = coverage_check.GENERATED.read_text()
            # Real retained field corruption, unrelated to orphan-name matching.
            mutated.write_text(original.replace('{"get", 2,', '{"get", 3,', 1))
            self.assertNotEqual(mutated.read_text(), original)
            with patch.object(coverage_check, "GENERATED", mutated), \
                    patch.object(sys, "argv", ["coverage", "--redis-root", str(REDIS)]), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(coverage_check.main(), 1)

    def test_surface_accepts_contract(self):
        target, oracle = surface_fixture()
        diffs, output = run_surface(target, oracle)
        self.assertEqual(diffs, 0, output)

    def test_surface_rejects_each_orphan(self):
        target, oracle = surface_fixture()
        removed = [name for name in oracle if name.startswith((b"cluster|", b"module|"))]
        self.assertEqual(len(removed), 33)
        for name in removed:
            with self.subTest(name=name):
                broken = {**target, name: oracle[name]}
                diffs, output = run_surface(broken, oracle)
                self.assertGreater(diffs, 0, output)

    def test_surface_controls(self):
        target, oracle = surface_fixture()
        for fault in ("count-subcommands", "empty-acl-filter", "module-leak", "nil-docs"):
            with self.subTest(fault=fault):
                self.assertGreater(run_surface(target, oracle, target_fault=fault)[0], 0)
        self.assertGreater(run_surface(target, oracle, oracle_fault="empty-oracle-family")[0], 0)
        missing_get = {name: row for name, row in target.items() if name != b"get"}
        self.assertGreater(run_surface(missing_get, oracle)[0], 0)
        extra = {**target, b"cmdmeta-phantom": target[b"get"]}
        self.assertGreater(run_surface(extra, oracle)[0], 0)
        wrong_category = copy.deepcopy(target)
        wrong_category[b"get"][6].remove(b"@read")
        self.assertGreater(run_surface(wrong_category, oracle)[0], 0)

    def test_directed_absence_assertions(self):
        target, oracle = surface_fixture()
        removed = {name for name in oracle if name.startswith((b"cluster|", b"module|"))}
        tree = ast.parse((ROOT / "tests/cmdmeta.py").read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "absent_families")
        class Connection:
            def __init__(self, rows):
                self.peer = Peer(rows, True)
            def cmd(self, *argv):
                self.peer.sendall(argv)
                return self.peer.read()
        def check(rows):
            failures = []
            def expect(label, got, want):
                if not (want(got) if callable(want) else got == want):
                    failures.append(label)
            scope = dict(ABSENT_PIPES={name.decode() for name in removed}, expect=expect)
            exec(compile(ast.Module(body=[function], type_ignores=[]), "cmdmeta.py:absence", "exec"), scope)
            scope["absent_families"](Connection(rows), "scripted protocol")
            return failures
        self.assertEqual(check(target), [])
        for name in removed:
            with self.subTest(name=name):
                self.assertTrue(check({**target, name: oracle[name]}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
