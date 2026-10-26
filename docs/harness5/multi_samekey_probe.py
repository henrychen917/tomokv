"""Diagnostic (not a benchmark): EXEC time of ONE transaction with N queued writes, fresh server per mode.

Found while gating unit/type/stream: "XADD mass insertion and XLEN" (10,000 XADDs in one MULTI) takes
~24 s on TomoKV in both modes, against well under 1 s on Redis. KIND=xadd-one-key | rpush-one-key |
set-distinct-keys. A doubling of N that quadruples EXEC time is O(N^2)."""
import sys, time
sys.path.insert(0, '/home/user/Projects/cx-harness5/docs/harness5')
from pathlib import Path
import repro_tcl as R
import os
KINDS = {'xadd-one-key': lambda n, j: ('XADD', f's{n}', '*', 'item', j), 'rpush-one-key': lambda n, j: ('RPUSH', f'l{n}', j), 'set-distinct-keys': lambda n, j: ('SET', f'k{n}:{j}', j)}
KIND = KINDS[os.environ['KIND']]
for mode in ('2s', '1s', 'redis'):
    binary = R.REDIS if mode == 'redis' else Path('/home/user/Projects/cx-harness5/build/tomokv')
    process, _ = R.boot(mode, binary, 45899, '32-39', '6:2', [], Path(f'/home/user/Projects/cx-harness5/build/h5-multi-scaling/{mode}'))
    try:
        c = R.Client(45899); row = []
        for n in (1000, 2000, 4000):
            c.send(['DEL', f's{n}']); c.read()
            t0 = time.monotonic()
            c.send(['MULTI']); c.read()
            enc = lambda *a: b'*%d\r\n' % len(a) + b''.join(b'$%d\r\n%s\r\n' % (len(x), x) for x in (str(v).encode() for v in a))
            payload = b''.join(enc(*KIND(n, j)) for j in range(n))
            c.sock.sendall(payload)
            for _ in range(n): c.read(30)
            t1 = time.monotonic()
            c.send(['EXEC']); reply = c.read(120)
            t2 = time.monotonic()
            row.append(f'n={n}: queue {t1-t0:.3f}s exec {t2-t1:.3f}s ({len(reply)} ids)')
        print(mode, '; '.join(row), flush=True)
    finally:
        R.stop(process)
