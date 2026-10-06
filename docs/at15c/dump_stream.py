#!/usr/bin/env python3
"""Dump the unchanged edgetime generator without opening a socket."""
import ast
import json
from pathlib import Path
import random
import time

source = Path('tests/differ.py')
tree = ast.parse(source.read_text())
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'gen_edgetime')
scope = dict(time=time)
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
ops = scope['gen_edgetime'](random.Random(7))
out = Path('docs/at15c/edgetime-seed7.json')
out.write_text(json.dumps(ops, indent=2) + '\n')
print('zero-based operations:', len(ops))
for target in (1526, 2910):
    print('\nTARGET', target, ops[target], 'batch', target // 64 * 64)
    for i in range(target // 64 * 64, target + 2):
        print(i, json.dumps(ops[i]))
    print('PRIOR REFERENCES TO TARGET KEY')
    for i, op in enumerate(ops[:target]):
        if ops[target][1] in op:
            print(i, json.dumps(op))
