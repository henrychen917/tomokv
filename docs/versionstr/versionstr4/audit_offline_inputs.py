#!/usr/bin/env python3
"""Replay changed build-input predicates without running historical drivers."""
import ast
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

BASE = "5911a55b6"
ROOT = Path("build/versionstr3/POST").resolve()
OUT = Path("docs/versionstr/versionstr4")
rows = []
files = subprocess.check_output(
    ["git", "diff", "--name-only", BASE, "36cd5c0f1"], text=True).splitlines()
for name in files:
    if not name.endswith(".py"):
        continue
    new = ast.parse(Path(name).read_text())
    old = ast.parse(subprocess.check_output(["git", "show", BASE + ":" + name], text=True))
    old_nodes = {(n.lineno, type(n)): n for n in ast.walk(old)
                 if isinstance(n, (ast.GeneratorExp, ast.ListComp))}
    for node in ast.walk(new):
        if not isinstance(node, (ast.GeneratorExp, ast.ListComp)):
            continue
        predicates = node.generators[0].ifs
        if not any("version.o" in ast.unparse(v) for v in predicates):
            continue
        previous = old_nodes[node.lineno, type(node)].generators[0].ifs
        variants = []
        namespaces = ["src", "db0/src"] if name == "tools/storesize_artifacts.py" else ["from iterator"]
        for namespace in namespaces:
            env = dict(arm=ROOT, base=ROOT, build=ROOT, root=ROOT,
                       directory=ROOT / namespace if namespace != "from iterator" else ROOT,
                       args=SimpleNamespace(post=ROOT),
                       objects=sorted((ROOT / "src").rglob("*.o"))
                       if name == "tools/iopass_receipts.py" else ROOT)
            iterator = node.generators[0].iter
            paths = list(eval(compile(ast.Expression(iterator), name, "eval"), {}, env))

            def allowed(conditions, path):
                return all(eval(compile(ast.Expression(v), name, "eval"), {}, dict(env, p=path))
                           for v in conditions)

            before = [str(p) for p in paths if allowed(previous, p)]
            after = [str(p) for p in paths if allowed(predicates, p)]
            removed, added = sorted(set(before) - set(after)), sorted(set(after) - set(before))
            assert len(removed) == 1 and removed[0].endswith("/core/version.o") and not added, (
                name, node.lineno, removed, added)
            variants.append(dict(iterator=ast.unparse(iterator), namespace=namespace,
                                 before=len(before), after=len(after), removed=removed, added=added))
        rows.append(dict(file=name, line=node.lineno,
                         predicates=[ast.unparse(v) for v in predicates], variants=variants))
assert len(rows) == 13, len(rows)
(OUT / "offline-input-controls.json").write_text(json.dumps(rows, indent=2) + "\n")
print("PASS: 13 changed object collectors; only version.o removed from every original iterator")
