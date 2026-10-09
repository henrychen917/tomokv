#!/usr/bin/env python3
"""Bisect gen_multidb(seed=7)'s random SWAPDB commands on fresh owned listeners."""
import ast
import json
from pathlib import Path
import random
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tests'))
from _lib import Conn
from _differ_aclkeys import wait_blocked
from aclkeys_wake_state import registered
from psfix import boot
binary, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=False)
node = next(n for n in ast.parse((ROOT/'tests/differ.py').read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'gen_multidb')
namespace = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), '<gen_multidb>', 'exec'), namespace)
# The deterministic prelude ends after the invalid-index matrix. Keep only the
# valid random swaps, preserving their original order and self-swaps.
operations = namespace['gen_multidb'](random.Random(7))
start = operations.index(['SWAPDB', '0', '-2147483649']) + 1
swaps = [op for op in operations[start:] if op[0] == 'SWAPDB']
rows = []
def fails(arming):
    directory = output / str(len(rows)); directory.mkdir()
    with boot([str(binary), '--bind','127.0.0.1','--port','18340','--shards','16',
               '--databases','16','--ratio','6:2','--atomic','0','--save','',
               '--dir',str(directory.resolve())], '112-119', 18340, directory/'server.log'):
        admin = Conn('127.0.0.1',18340,timeout=2,buffering=0)
        worker = Conn('127.0.0.1',18340,timeout=2,buffering=0)
        try:
            for op in arming: assert admin.cmd(*op) == b'OK'
            assert admin.cmd('DEL','block:aclkeys') == 0
            ident = worker.cmd('CLIENT','ID')
            worker.send('XREAD','BLOCK',0,'STREAMS','block:aclkeys',0)
            wait_blocked(admin,(worker.sock,worker.file),ident,
                         lambda c,args:c.cmd(*args),lambda v:v,lambda f:worker.read(),timeout=2)
            registered(admin)
            assert admin.cmd('XADD','block:aclkeys','1-0','field','value') == b'1-0'
            try:
                assert worker.read() == [[b'block:aclkeys',[[b'1-0',[b'field',b'value']]]]]
                lost = False
            except TimeoutError: lost = True
        finally: worker.close(); admin.close()
    row = dict(commands=arming, count=len(arming), lost=lost)
    rows.append(row)
    (output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(len(arming), 'lost' if lost else 'woke',flush=True)
    return lost
assert fails(swaps)
while len(swaps) > 1:
    left,right=swaps[:len(swaps)//2],swaps[len(swaps)//2:]
    if fails(left): swaps=left
    elif fails(right): swaps=right
    else: raise AssertionError('neither half preserves the failure')
assert not fails([]), 'fresh control failed'
print('MINIMAL',swaps,flush=True)
