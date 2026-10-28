#!/usr/bin/env python3
"""Falsify atomic-label, owner-geometry and fresh-placement rearming contracts."""
import ast
import contextlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _lib
import atomicwindow
import feature_atomic


def script_helpers():
    tree = ast.parse(Path(__file__).with_name("scriptatomic.py").read_text())
    names = {"owners_of", "find_pair", "unavailable", "vacuous"}
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = dict(TAG="fixture", RespError=_lib.RespError, strict_mode=_lib.strict_mode, FAIL=0, VACUOUS=0)
    exec(compile(tree, "scriptatomic.py", "exec"), ns)
    return ns


class Contracts(unittest.TestCase):
    def test_battery_restores_both_arms_even_on_failure(self):
        for atomic in (0, 1):
            for rc in (0, 7):
                class Connection:
                    value = 1 - atomic
                    file = SimpleNamespace(read=lambda count: b"")
                    def must(self, *args):
                        if args == ("QUIT",): return b"OK"
                        if args[1] == "SET":
                            self.value = int(args[3]); return b"OK"
                        return [b"atomic", str(self.value).encode()]
                    def close(self): pass
                conn = Connection()
                def battery(command, **kwargs):
                    self.assertEqual(conn.value, atomic, "stale atomic label at entry")
                    conn.value = 1 - atomic
                    return SimpleNamespace(returncode=rc)
                with patch.object(feature_atomic, "Conn", return_value=conn), \
                     patch.object(feature_atomic.subprocess, "run", side_effect=battery):
                    self.assertEqual(feature_atomic.run("fixture", 0, atomic, ["battery"]), rc)
                self.assertEqual(conn.value, atomic, "stale atomic label at exit")
        print("PASS TM4.1: mutating battery and failing battery both restore 0/1")

    def test_original_missing_restore_is_rejected(self):
        class Connection:
            value = 0
            file = SimpleNamespace(read=lambda count: b"")
            def must(self, *args):
                if args == ("QUIT",): return b"OK"
                if args[1] == "SET":
                    self.value = int(args[3]); return b"OK"
                return [b"atomic", str(self.value).encode()]
            def close(self): pass
        conn = Connection()
        def battery(command, **kwargs):
            assert conn.value == 1, "stale advertised atomic arm"
            return SimpleNamespace(returncode=0)
        with patch.object(feature_atomic, "Conn", return_value=conn), \
             patch.object(feature_atomic, "restore", return_value=None), \
             patch.object(feature_atomic.subprocess, "run", side_effect=battery):
            with self.assertRaisesRegex(AssertionError, "stale advertised atomic arm"):
                feature_atomic.run("fixture", 0, 1, ["battery"])
        print("CONTROL FAIL TM4.1: original missing restore exposes the stale arm")

    def test_ignored_restore_is_rejected(self):
        conn = SimpleNamespace(must=lambda *args: b"OK" if args[1] == "SET" else [b"atomic", b"0"])
        with self.assertRaisesRegex(AssertionError, "boundary mismatch"):
            feature_atomic.restore(conn, 1)
        print("CONTROL FAIL TM4.1: ignored restore -> atomic boundary mismatch")

    def test_debug_denial_is_a_strict_failure(self):
        ns = script_helpers()
        with patch.dict(os.environ, TOMO_GATE_STRICT="1"):
            ns["unavailable"]("DEBUG disabled")
        self.assertEqual((ns["FAIL"], ns["VACUOUS"]), (1, 1))
        with patch.dict(os.environ, TOMO_GATE_STRICT="0"):
            ns["unavailable"]("DEBUG disabled")
        self.assertEqual(ns["FAIL"], 1)
        print("CONTROL FAIL TM4.2: denied DEBUG increments FAIL and VACUOUS")

    def test_shards_are_not_owners(self):
        ns = script_helpers()
        class Connection:
            def cmd(self, *args):
                rows = []
                for key in args[2:]:
                    n = 0 if key.endswith("anchor") else int(key.rsplit(":", 1)[1]) + 1
                    rows.append([n, 6 if n < 3 else 7])
                return rows
        conn = Connection()
        pair = ns["find_pair"](conn, False)
        self.assertEqual(ns["owners_of"](conn, pair), [6, 7])
        old_pair = ("fixture:pair:anchor", "fixture:pair:0")
        with self.assertRaisesRegex(AssertionError, "same owner"):
            owners = ns["owners_of"](conn, old_pair)
            assert owners[0] != owners[1], "different shards, same owner"
        print("CONTROL FAIL TM4.3: original distinct-shard pair has same owner")

    def test_placement_changes_reroll_bounded_fresh_state(self):
        for moves in (1, atomicwindow.ARM_ATTEMPTS):
            created, prefixes = [], []
            class Connection:
                def __init__(self, *args, **kwargs): created.append(self)
                def close(self): pass
            def info(conn, section):
                if section == "server": return {"shards": "16"}
                return {"atomic_" + key: str(value) for key, value in
                        dict(groups=0, inflight=0, window_stalls=0, credit_debt=0, credit_pool=256).items()}
            class ReachedFreshArm(Exception): pass
            def discover(conn, prefix, **kwargs):
                prefixes.append((conn, prefix))
                if len(prefixes) <= moves:
                    raise _lib.PlacementChanged("placement moved")
                raise ReachedFreshArm()
            with patch.object(_lib, "Conn", Connection), patch.object(_lib, "info", info), \
                 patch.object(_lib, "owner_buckets", side_effect=discover):
                if moves == 1:
                    with self.assertRaises(ReachedFreshArm):
                        atomicwindow.held_burst("fixture", 0, whole_window=True)
                else:
                    with self.assertRaisesRegex(AssertionError, "window never observed"):
                        atomicwindow.held_burst("fixture", 0, whole_window=True)
            self.assertEqual(len(created), len(prefixes))
            self.assertEqual(len(set(prefix for _, prefix in prefixes)), len(prefixes))
            self.assertEqual(len({id(conn) for conn, _ in prefixes}), len(prefixes))
        print("CONTROL FAIL HX-LB-PROBE: perpetual migration exhausts four fresh attempts")

    def test_real_probe_distinguishes_moved_placement_from_bad_evidence(self):
        topo = SimpleNamespace(shard_owner={3: 6})
        with patch.object(_lib, "shards_of", return_value=[(3, 7)]), \
             patch.object(_lib, "topology", return_value=topo):
            with self.assertRaises(_lib.PlacementChanged):
                next(_lib.probe_keys(None, "fresh", topo, limit=1))
        with patch.object(_lib, "shards_of", return_value=[(99, 7)]):
            with self.assertRaises(AssertionError) as failure:
                next(_lib.probe_keys(None, "fresh", topo, limit=1))
            self.assertNotIsInstance(failure.exception, _lib.PlacementChanged)

    def test_stable_probe_repeats_whole_discovery_before_yielding(self):
        old = _lib.Topology({6: 'ex', 7: 'ex'}, {3: 6}, [6], '2s')
        moved = _lib.Topology({6: 'ex', 7: 'ex'}, {3: 7}, [7], '2s')
        with patch.object(_lib, 'shards_of', side_effect=[[(3, 7)], [(3, 7)]]) as probe, \
             patch.object(_lib, 'topology', return_value=moved):
            rows = list(_lib.probe_keys(None, 'fresh', old, limit=1))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(rows, [('fresh:0000', 3, 7)])
        self.assertEqual(old.shard_owner, {3: 7})

    def test_nonplacement_probe_error_is_never_retried(self):
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def close(self): pass
        def info(conn, section):
            if section == "server": return {"shards": "16"}
            return {"atomic_" + key: str(value) for key, value in
                    dict(groups=0, inflight=0, window_stalls=0, credit_debt=0, credit_pool=256).items()}
        with patch.object(_lib, "Conn", Connection), patch.object(_lib, "info", info), \
             patch.object(_lib, "owner_buckets", side_effect=AssertionError("malformed")) as discover:
            with self.assertRaisesRegex(AssertionError, "malformed"):
                atomicwindow.held_burst("fixture", 0, whole_window=True)
            self.assertEqual(discover.call_count, 1)


if __name__ == "__main__":
    unittest.main()
