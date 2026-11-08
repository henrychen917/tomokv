#!/usr/bin/env python3
"""CD5.6 abort-site witness: run Z-T6's mpop-watch-then-tracking shape under gdb, no rates.

WATCH k; a two-key ZMPOP pops k from a cross-owner pair; the watcher's MULTI/PING/EXEC;
FLUSHALL and reseed; a RESP3 CLIENT TRACKING connection reads k. gdb is the server's parent,
so a SIGABRT leaves its backtrace in the receipt. A live server is stopped by SIGTERM.
Usage: txnfix4_abort_site.py --binary B --label L [--mode 2s] [--iterations N]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn, wait_ready  # noqa: E402

OUT = ROOT / 'docs/txnfix4/abort-site'


def pair(c, prefix):
    first = prefix + ':0'
    origin = c.must('DEBUG', 'SHARDS', first)[0]
    for start in range(1, 8192, 64):
        names = [f'{prefix}:{i}' for i in range(start, start + 64)]
        for name, where in zip(names, c.must('DEBUG', 'SHARDS', *names)):
            if where[1] != origin[1]:
                return first, name, [origin, where]
    raise AssertionError('no cross-owner pair')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--mode', choices=('1s', '2s'), default='2s')
    p.add_argument('--iterations', type=int, default=1)
    p.add_argument('--port', type=int, default=21460)
    a = p.parse_args()
    assert 21400 <= a.port <= 21499
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='abort-site-', dir=ROOT / 'build'))
    flags = ['--port', str(a.port), '--bind', '127.0.0.1', '--dir', str(work), '--save', '',
             '--appendonly', 'no', '--shards', '16', '--databases', '16', '--atomic', '1',
             '--read-local', '0', '--flip-auto', '0', '--enable-debug-command', 'yes']
    flags += ['--ratio', '6:2'] if a.mode == '2s' else ['--thread-mode', 'fused']
    gdb = ['taskset', '-c', '61-68', 'gdb', '-nx', '-batch', '-ex', 'set pagination off',
           '-ex', 'set debuginfod enabled off', '-ex', 'handle SIGPIPE nostop noprint',
           '-ex', 'run', '-ex', 'bt 12', '--args', str(a.binary.resolve())] + flags
    log_path = OUT / f'{a.label}.gdb.log'
    with log_path.open('w') as log:
        proc = subprocess.Popen(gdb, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, LC_ALL='C'))
    rows, died = [], False
    try:
        c = wait_ready('127.0.0.1', a.port, timeout=120)
        for it in range(a.iterations):
            c.must('FLUSHALL')
            missing, key, where = pair(c, f'cd56:{it}')
            w, t = Conn('127.0.0.1', a.port), Conn('127.0.0.1', a.port)
            c.must('ZADD', key, 1, 'a', 2, 'b', 3, 'c')
            w.must('WATCH', key)
            popped = c.cmd('ZMPOP', 2, missing, key, 'MIN')
            w.must('MULTI'); w.must('PING')
            exec_reply = w.cmd('EXEC')
            c.must('FLUSHALL'); c.must('ZADD', key, 1, 'a', 2, 'b', 3, 'c')
            t.must('HELLO', 3); t.must('CLIENT', 'TRACKING', 'ON')
            try:
                read = t.cmd('ZRANGE', key, 0, -1)
                alive = Conn('127.0.0.1', a.port, timeout=5).cmd('PING') == b'PONG'
            except (OSError, EOFError) as error:
                read, alive = repr(error), False
            rows.append(dict(iteration=it, locations=where, pop=repr(popped),
                             exec=repr(exec_reply), tracked_read=repr(read), alive=alive))
            w.close(); t.close()
            if not alive:
                died = True
                break
    finally:
        if not died:
            children = subprocess.run(['pgrep', '-P', str(proc.pid)], capture_output=True,
                                      text=True).stdout.split()
            for pid in children:
                os.kill(int(pid), signal.SIGTERM)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        shutil.rmtree(work, ignore_errors=True)
    text = log_path.read_text(errors='replace')
    frames = [line for line in text.splitlines() if line.startswith('#')][:12]
    summary = dict(label=a.label, binary=str(a.binary), mode=a.mode,
                   binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),
                   iterations=len(rows), died=died, sigabrt='SIGABRT' in text,
                   exec_committed=sum(r['exec'] != 'None' for r in rows),
                   backtrace=frames, rows=rows[:3] + rows[-2:])
    (OUT / f'{a.label}.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in ('label', 'iterations', 'died', 'sigabrt',
                                              'exec_committed')}))
    for frame in frames[:8]:
        print(frame)


if __name__ == '__main__':
    main()
