"""Serverless before/after: stop the real Runner at the population boundary."""
import contextlib
import difflib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import abbagate as post
from _lib import RespError


def module_at(commit):
    source = subprocess.check_output(["git", "show", commit + ":tests/abbagate.py"], cwd=ROOT, text=True)
    module = ModuleType("dbdefault_pre_abba")
    module.__file__ = str(ROOT / "tests/abbagate.py")
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def receipt(abba, cell, arm, legacy=False, bad=False):
    folder = ROOT / "build/dbdefault/dry-receipt"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir()
    child = SimpleNamespace(pid=123, poll=lambda: None)
    children = SimpleNamespace(start=mock.Mock(return_value=child), stop=mock.Mock())
    args = SimpleNamespace(server_cores="112-119", server_smt="", load_cores="121-127",
                           load_smt="", port=25150)
    runner = abba.Runner(args, folder, {arm: Path("binary-" + arm)}, children)
    runner.legacy_reorder_control = mock.Mock(return_value=None)
    runner.read_local_reorder_control = mock.Mock(return_value=None)
    runner.database_support = {arm: not legacy}
    runner.populate = mock.Mock(side_effect=RuntimeError("serverless population boundary"))
    conn = mock.Mock()
    requested = abba.server_databases(abba.server_arguments(cell.server_flags)) or 1
    def reply(*words):
        if words == ("CONFIG", "GET", "databases"):
            return [] if legacy else [b"databases", str(16 if bad else requested).encode()]
        if words == ("SELECT", 0):
            return b"OK"
        return [words[-1].encode(), str(cell.atomic).encode()]
    conn.must.side_effect = reply
    conn.cmd.return_value = RespError("ERR DB index is out of range")
    with mock.patch.multiple(abba, require_unbound_port=mock.Mock(), Conn=mock.Mock(return_value=conn),
            info=mock.Mock(return_value=dict(process_id="123", read_local=str(cell.read_local))),
            measured_ratio=mock.Mock(return_value="6:2")), \
            mock.patch.object(abba.time, "monotonic", return_value=100.), \
            contextlib.redirect_stdout(io.StringIO()):
        try:
            runner.measure(cell, arm, 1, 1, {})
        except RuntimeError as error:
            assert str(error) == ("boot did not apply databases=1: [b'databases', b'16']" if bad
                                  else "serverless population boundary"), str(error)
        else:
            raise AssertionError("dry runner crossed population boundary")
    assert runner.populate.call_count == (0 if bad else 1)
    assert children.start.call_count == 1  # No generator or real child ever runs.
    return json.loads(next(folder.glob("*/n1-1-*/measurement.json")).read_text())


def main():
    out = ROOT / "docs/dbdefault"
    pre = module_at((out / "pre-commit.txt").read_text().strip())
    records = []
    for name, source, index in (("implicit", "tests/headline_cells.txt", 0),
                                ("ttl", "tests/ttl_cells.txt", 0),
                                ("explicit16", "docs/lbplanner/multidb-cells.txt", 1)):
        for arm in ("A", "B"):
            before = receipt(pre, pre.read_cells(ROOT / source)[index], arm)
            after = receipt(post, post.read_cells(ROOT / source)[index], arm)
            normalized = dict(after)
            if name != "explicit16":
                assert normalized.pop("configured_databases") == 1
                normalized["server_argv"] = normalized["server_argv"][:-2]
                assert after["server_argv"][-2:] == ["--databases", "1"]
            assert before == normalized, (name, arm, before, normalized)
            records.append(dict(cell=name, arm=arm, before=before, after=after))
    cell = post.read_cells(ROOT / "tests/headline_cells.txt")[0]
    legacy = receipt(post, cell, "A", legacy=True)
    assert legacy["configured_databases"] == 1 and "--databases" not in legacy["server_argv"]
    for arm in ("A", "B"):
        receipt(post, cell, arm, bad=True)
    (out / "receipts.json").write_text(json.dumps(dict(comparisons=records, legacy=legacy), indent=2) + "\n")
    before = json.dumps([r["before"] for r in records], indent=2).splitlines(True)
    after = json.dumps([r["after"] for r in records], indent=2).splitlines(True)
    (out / "receipts.diff").write_text("".join(difflib.unified_diff(before, after, "PRE", "POST")))
    print("6 real-Runner dry receipts: only --databases 1/configured_databases added; explicit16 identical")
    print("Legacy reference omitted unsupported flag and proved DB0; both modern arms reject default16 before population")


if __name__ == "__main__":
    main()
