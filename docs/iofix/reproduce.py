#!/usr/bin/env python3
"""Read-only baseline probes; the gate batteries assert the corrected behavior."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
import select
import signal
import time
from _iofix import arguments, Listener, emit, info, encode, cpu_times


args = arguments(__doc__).parse_args()
args.output.mkdir(parents=True, exist_ok=True)
with Listener(args, 'baseline') as server:
    c = server.connect()
    emit(item='IO4.9', get=c.cmd('CONFIG', 'GET', 'hz'), set=c.cmd('CONFIG', 'SET', 'hz', '20'))
    sleeper = server.connect()
    sleeper.send('DEBUG', 'SLEEP', '.4')
    time.sleep(.08)
    t = time.monotonic()
    reply = c.cmd('PING')
    emit(item='IO4.10', other_ping_seconds=time.monotonic()-t, reply=reply)
    assert sleeper.read() == b'OK'

for policy in (0, 1):
    with Listener(args, f'wb-policy-{policy}', extra=['--wb-policy', str(policy)]) as server:
        c = server.connect()
        # A remote owner executes exactly one long command while the IO holds a small ready prefix.
        n = 3_000_000
        for base in range(0, n, 10000):
            assert c.cmd('RPUSH', 'iofix:list', *(['payload']*10000)) == base + 10000
        rows = c.cmd('DEBUG', 'SHARDS', 'iofix:list')
        owner = rows[0][1]
        while c.cmd('DEBUG', 'IO-THREAD') == owner:
            c.close()
            c = server.connect()
        before = cpu_times(server.process.pid)
        t = time.monotonic()
        held = 0
        for _ in range(16):
            c.raw(encode('PING') + encode('LPOS', 'iofix:list', 'absent') + encode('PING')*3)
            if not select.select([c.sock], [], [], .002)[0]:
                held += 1
            assert [c.read() for _ in range(5)] == [b'PONG', None, b'PONG', b'PONG', b'PONG']
        wall = time.monotonic() - t
        after = cpu_times(server.process.pid)
        cpu = sorted(((after[k]-v)/1e9, k) for k,v in before.items() if k in after)[::-1]
        emit(item='WB4.1', policy=policy, wall_seconds=wall, held=held, top_cpu_seconds=cpu[:3])

for sig in (signal.SIGTERM, signal.SIGINT):
    with Listener(args, sig.name, extra=['--save', '3600 1']) as server:
        c = server.connect()
        assert c.cmd('SET', 'iofix:signal', 'saved') == b'OK'
        # Observe the just-completed cron beat, then signal: do not rely on boot phase timing.
        fields = info(c)
        key = next((k for k in fields if b'save_cron_checks' in k), None)
        if key:
            initial = int(fields[key])
            deadline = time.monotonic() + 3
            while int(info(c)[key]) == initial and time.monotonic() < deadline:
                time.sleep(.005)
            assert int(info(c)[key]) > initial
        else:
            time.sleep(.1)
        t = time.monotonic()
        server.process.send_signal(sig)
        server.process.wait(timeout=12)
        emit(item='IO4.17', signal=sig.name, seconds=time.monotonic()-t, rc=server.process.returncode)

with Listener(args, 'oracle', oracle=True) as server:
    c = server.connect()
    emit(oracle='IO4.9', get=c.cmd('CONFIG','GET','hz'), set=c.cmd('CONFIG','SET','hz','20'))
    sleeper = server.connect()
    sleeper.send('DEBUG','SLEEP','.4')
    time.sleep(.08)
    t = time.monotonic()
    assert c.cmd('PING') == b'PONG'
    emit(oracle='IO4.10', other_ping_seconds=time.monotonic()-t)
    assert sleeper.read() == b'OK'
