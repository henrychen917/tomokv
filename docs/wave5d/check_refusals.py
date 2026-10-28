"""Exercise the actual nested script workers without starting a server."""
import ast
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path.cwd() / "tests"))
import _lib

BASE = "9d7b2dd58"
KNOWN = ("TRYAGAIN Cross-shard script conflicted, retry",
         "BUSY Cross-shard script snapshot window is full")
BAD = ["TRYAGAIN unrelated", "BUSY unrelated", "ERR unrelated"]
for message in KNOWN:
    BAD.extend((message + " extra", "prefix " + message, message.lower(), message[:-1]))


def load_worker(source, path, namespace):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "SCRIPT_REFUSALS"
                for target in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "allowlist", "exec"), namespace)
    node = tree
    for name in path:
        node = next(child for child in node.body if isinstance(
            child, (ast.FunctionDef, ast.ClassDef)) and child.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "actual-worker", "exec"), namespace)
    return namespace[path[-1]]


class Connection:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def cmd(self, *args):
        self.calls += 1
        return self.replies.pop(0)

    def close(self):
        pass


def txn(source, messages):
    conn = Connection([_lib.RespError(message) if isinstance(message, str) else message
                       for message in messages])
    recorded = []
    namespace = dict(_lib=_lib, self=SimpleNamespace(conn=lambda **kw: conn),
                     keys=["a", "b"], end=1, lock=threading.Lock(),
                     time=SimpleNamespace(monotonic=lambda: 0 if conn.replies else 2),
                     script_refusals=dict(TRYAGAIN=0, BUSY=0),
                     record=lambda keys: recorded.append(list(keys)))
    fn = load_worker(source, ("OrderBattery", "deadlock", "script"), namespace)
    error = None
    try:
        fn()
    except AssertionError as exc:
        error = exc
    return error, namespace["script_refusals"], recorded


class RespError:
    def __init__(self, message):
        self.message = message


def xscript(source, name, messages):
    target = 40 if name == "worker" else 80
    conn = Connection([RespError(message) for message in messages] + [1] * target)
    counts = dict(TRYAGAIN=0, BUSY=0)
    errors = []
    namespace = dict(Resp=lambda: conn, RespError=RespError, source="", script_source="",
                     keys=["a", "b"], script_writer=conn, successes=[0, 0],
                     refusals=[counts, dict(TRYAGAIN=0, BUSY=0)], race_refusals=counts,
                     errors=errors, race_errors=errors)
    fn = load_worker(source, ("contention_and_deadlock", name), namespace)
    fn(0, namespace["keys"]) if name == "worker" else fn()
    return errors, counts, conn.calls, namespace["successes"][0]


# KNOWN now names forbidden replies, including their exact historical spellings.
current = Path("tests/txnorder.py").read_text()
for message in [*KNOWN, *BAD]:
    error, counts, recorded = txn(current, [message])
    assert isinstance(error, AssertionError) and not recorded and not any(counts.values()), message
error, counts, recorded = txn(current, [2])
assert error is None and recorded == [["a", "b"]] and not any(counts.values())
print("PASS txnorder: every refusal fails; only a success is accounted")
current = Path("tests/xscript.py").read_text()
for name, target in (("worker", 40), ("script_racer", 80)):
    for message in [*KNOWN, *BAD]:
        errors, counts, calls, successes = xscript(current, name, [message])
        assert len(errors) == 1 and calls == 1 and not any(counts.values()) and successes == 0, message
    errors, counts, calls, successes = xscript(current, name, [])
    assert not errors and calls == target and not any(counts.values())
    print(f"PASS xscript {name}: every refusal fails; {target} successes accounted")
