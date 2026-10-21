#!/usr/bin/env python3
"""Record the separate keyless-expiry / command-keymiss delivery-order concern."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from compat2_support import Client, server, save

OUT = ROOT / 'docs/compat2/notification-order'
OUT.mkdir(exist_ok=False)
records = []
arms = [('pre', ROOT / 'build/compat2/pre-source/build/tomokv'),
        ('post', ROOT / 'build/tomokv')]
for arm, binary in [*arms, ('oracle', Path('/home/user/Projects/redis74/src/redis-server'))]:
    for mode, engine in ([('oracle', 'oracle')] if arm == 'oracle' else
                         [(m, e) for m in ('1s', '2s') for e in ('epoll', 'uring')]):
        name = f'{arm}-{mode}-{engine}'
        with server(binary, OUT / name, 26850, '72' if arm == 'oracle' else '64-71',
                    mode, engine, oracle=arm == 'oracle'), Client(26850) as c, Client(26850) as sub:
            assert c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'Exm') == b'OK'
            assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
            sub.send('SUBSCRIBE', '__keyevent@0__:expired', '__keyevent@0__:keymiss')
            sub.read(); sub.read()
            rows = []
            for n in range(24):
                key = f'compat2:order:{n}'
                assert c.cmd('SET', key, 'live', 'PX', 100) == b'OK'
                deadline = c.cmd('PEXPIRETIME', key)
                assert c.cmd('GET', key) == b'live', 'live arm required'
                while time.time_ns() // 1000000 <= deadline + 10:
                    time.sleep(.002)
                assert c.cmd('GET', key) is None
                events = [sub.read(), sub.read()]
                expected = [[b'message', b'__keyevent@0__:expired', key.encode()],
                            [b'message', b'__keyevent@0__:keymiss', key.encode()]]
                assert sorted(events) == sorted(expected), events
                rows.append(dict(key=key, events=events, expired_first=events == expected))
            records.append(dict(arm=arm, mode=mode, engine=engine, rows=rows))
            save(OUT / 'results.json', records)
            print(name, 'reversed', sum(not r['expired_first'] for r in rows), flush=True)
