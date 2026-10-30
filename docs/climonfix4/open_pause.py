#!/usr/bin/env python3
"""Bounded fresh-state witness for the deferred UNPAUSE/UNBLOCK ordering issue."""
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from climonfix4 import server
from redis_tcl import sha

out = ROOT / 'build/climonfix4/open-pause'
out.mkdir(exist_ok=True)
args = SimpleNamespace(cores='16-23', port=20270, ratio='6:2', engine='uring')
rows = []
for arm, binary, modes in (
    ('Redis', Path('/home/user/Projects/redis74/src/redis-server'), ('redis',)),
    ('PRE', ROOT / 'build/climonfix4/tomokv-PRE', ('1s', '2s')),
    ('POST', ROOT / 'build/climonfix4/tomokv-POST', ('1s', '2s')),
):
    for mode in modes:
        for trial in range(10):
            with server(args, binary, mode, out / arm / mode / str(trial)) as (conn, argv):
                control, a, b = (conn(name) for name in ('control', 'a', 'b'))
                ids = [c.cmd('CLIENT', 'ID') for c in (a, b)]
                assert control.cmd('CLIENT', 'PAUSE', 10000, 'WRITE') == b'OK'
                for c in (a, b):
                    c.send('BLPOP', 'pending', 0)
                for _ in range(200):
                    count = int(re.search(rb'blocked_clients:(\d+)', control.cmd('INFO', 'clients'))[1])
                    if count == 2:
                        break
                    time.sleep(.01)
                else:
                    raise AssertionError('postponed-client window did not arm')
                paused = [control.cmd('CLIENT', 'UNBLOCK', cid, flavor)
                          for cid, flavor in zip(ids, ('TIMEOUT', 'ERROR'))]
                assert paused == [0, 0]
                assert control.cmd('CLIENT', 'UNPAUSE') == b'OK'
                resumed = [control.cmd('CLIENT', 'UNBLOCK', cid, flavor)
                           for cid, flavor in zip(ids, ('TIMEOUT', 'ERROR'))]
                rows.append(dict(arm=arm, mode=mode, trial=trial, argv=argv,
                                 binary_sha256=sha(binary), paused=paused, resumed=resumed))
            (ROOT / 'docs/climonfix4/open-pause-results.json').write_text(json.dumps(rows, indent=2) + '\n')
        selected = [r for r in rows if r['arm'] == arm and r['mode'] == mode]
        print(arm, mode, sum(r['resumed'] != [1, 1] for r in selected), 'differences in 10 armed boots', flush=True)
assert all(r['resumed'] == [1, 1] for r in rows if r['arm'] == 'Redis')
for arm in ('PRE', 'POST'):
    assert any(r['resumed'] != [1, 1] for r in rows if r['arm'] == arm), (arm, 'ordering window not reproduced')
