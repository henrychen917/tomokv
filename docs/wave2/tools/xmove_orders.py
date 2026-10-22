#!/usr/bin/env python3
"""wave2 fix (b) receipt for gate row 310 (xmove battery, atomic 0). Never a performance run.

1. Serial-order table: each legal order of the three concurrent cells is produced deterministically
   (the push and LMOVE issued one after the other, each reply read before the next command), and
   the server's replies and lists are compared with the outcome tests/xmove.py now accepts for it.
2. Repetitions: the unchanged gate invocation `tests/xmove.py 127.0.0.1 PORT --release-build`
   (and the 991d48f65 version of the battery, for comparison) runs N times on fresh boots of the
   integrated binary in the gate's debug-AT shape; every attempt line is kept.
Server 80-87, clients 89-95, port 22820. usage: xmove_orders.py <out-dir> <runs> <atomic>...
CONTEND=1 (runs without --release-build) adds one busy-loop process per server CPU (80-87) during
the repetitions, so the
server's threads are preempted the way a shared box preempts them (the lottery calibration ran on
shared CPUs); it makes the other legal orders occur. Nothing outside 80-95 is used.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/home/user/Projects/cx-wave2')
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server  # noqa: E402

PORT = 22820
OUT = Path(sys.argv[1]).resolve()
RUNS = int(sys.argv[2])
ATOMICS = [int(a) for a in sys.argv[3:]] or [0]
OUT.mkdir(parents=True, exist_ok=False)
binary = ROOT / 'build/tomokv'
SHAPE = ['--ratio', '6:2', '--shards', '16', '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
os.sched_setaffinity(0, set(range(89, 96)))
old = OUT / 'xmove-991d48f65.py'
old.write_text(subprocess.check_output(['git', '-C', str(ROOT), 'show', '991d48f65:tests/xmove.py'], text=True))


def serial_table(atomic):
    sys.argv = ['xmove.py', '127.0.0.1', str(PORT)]
    import importlib
    xm = importlib.import_module('xmove')
    rows = []
    with server(binary, '80-87', PORT, OUT / f'serial-a{atomic}', SHAPE + ['--atomic', str(atomic)]):
        admin = xm.Conn()
        source, destination, _ = xm.find_geometry(admin)

        def setup():
            admin.command('DEL', source, destination)
            admin.command('RPUSH', source, 'moved', 'keep')
            admin.command('RPUSH', destination, 'dest')

        def state():
            return [admin.command('LRANGE', source, '0', '-1'), admin.command('LRANGE', destination, '0', '-1')]

        cases = [  # cell, push command, order, expected (move reply, push reply, source, destination)
            ('control', ('RPUSH', 'control'), 'push after hop two', (b'moved', 2, [b'keep', b'control'], [b'dest', b'moved'])),
            ('control', ('RPUSH', 'control'), 'push before hop one', (b'moved', 3, [b'keep', b'control'], [b'dest', b'moved'])),
            ('forced', ('RPUSH', 'concurrent'), 'push after hop two', (b'moved', 2, [b'keep', b'concurrent'], [b'dest', b'moved'])),
            ('forced', ('RPUSH', 'concurrent'), 'push before hop one', (b'moved', 3, [b'keep', b'concurrent'], [b'dest', b'moved'])),
            ('same_edge', ('LPUSH', 'new-edge'), 'push after hop two', (b'moved', 2, [b'new-edge', b'keep'], [b'dest', b'moved'])),
            ('same_edge', ('LPUSH', 'new-edge'), 'push before hop one', (b'new-edge', 3, [b'moved', b'keep'], [b'dest', b'new-edge'])),
        ]
        for cell, (verb, value), order, wanted in cases:
            setup()
            if order == 'push before hop one':
                pushed = admin.command(verb, source, value)
                moved = admin.command('LMOVE', source, destination, 'LEFT', 'RIGHT')
            else:
                moved = admin.command('LMOVE', source, destination, 'LEFT', 'RIGHT')
                pushed = admin.command(verb, source, value)
            got = (moved, pushed, *state())
            rows.append(dict(atomic=atomic, cell=cell, order=order, got=repr(got), wanted=repr(wanted),
                             matches=got == wanted))
        admin.file.close()
        admin.sock.close()
    return rows


def repetitions(atomic, script, label):
    results = []
    burners = []
    if os.environ.get('CONTEND') == '1':
        burners = [subprocess.Popen(['taskset', '-c', str(cpu), sys.executable, '-c', 'while True: pass'])
                   for cpu in range(80, 88)]
    try:
        return _repetitions(atomic, script, label, results)
    finally:
        for b in burners:
            b.kill()
            b.wait()


def _repetitions(atomic, script, label, results):
    for run in range(1, RUNS + 1):
        directory = OUT / f'{label}-a{atomic}-run{run}'
        with server(binary, '80-87', PORT, directory, SHAPE + ['--atomic', str(atomic)]):
            log = directory / 'battery.log'
            with log.open('w') as output:
                # Under CONTEND the release-only LMOVE size-ratio timing cell is skipped (the battery's
                # own switch): it measures cost, not order, and preemption would only add noise.
                extra = [] if os.environ.get('CONTEND') == '1' else ['--release-build']
                rc = subprocess.run(['taskset', '-c', '89-95', sys.executable, str(script), '127.0.0.1',
                                     str(PORT), *extra], cwd=ROOT, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=600).returncode
        text = log.read_text(errors='replace')
        retried = re.findall(r'attempt \d+: (.+?); replies and lists match', text)
        results.append(dict(run=run, exit_code=rc, passed=f'PASS xmove atomic={atomic}' in text,
                            retried_orders=retried, failure=[l for l in text.splitlines()
                                                             if 'Error' in l or 'wanted' in l][-3:]))
    return results


summary = dict(binary=str(binary), sha256=subprocess.check_output(['sha256sum', str(binary)], text=True).split()[0],
               runs=RUNS, atomics=ATOMICS, contend=os.environ.get('CONTEND') == '1', serial=[], repetitions={})
for atomic in ATOMICS:
    summary['serial'] += serial_table(atomic)
    for label, script in (('fixed', ROOT / 'tests/xmove.py'), ('pre-fix', old)):
        rows = repetitions(atomic, script, label)
        summary['repetitions'][f'{label}-a{atomic}'] = dict(
            runs=len(rows), passed=sum(r['passed'] for r in rows),
            retried_orders=sorted({o for r in rows for o in r['retried_orders']}),
            retry_count=sum(len(r['retried_orders']) for r in rows), rows=rows)
        print(label, atomic, summary['repetitions'][f'{label}-a{atomic}']['passed'], '/', len(rows), flush=True)
print(json.dumps([(r['cell'], r['order'], r['matches']) for r in summary['serial']]))
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
