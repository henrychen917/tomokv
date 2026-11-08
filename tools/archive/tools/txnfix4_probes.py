#!/usr/bin/env python3
"""txnfix4 supplementary probes (receipts only, no gate row, no rates).

aofrw         CD5.3 through an AOF-rewrite capture: appendonly yes, two 128 MiB values on the
              hash's shard (their AOF growth starts an automatic rewrite), fields lapse while
              aof_rewrite_in_progress is 1, then HGET/HLEN/HINCRBY and the post-rewrite state.
exec-mpop-aof Additional finding outside the brief: MULTI; LMPOP|ZMPOP 1 key; EXEC with
              appendonly yes. Records the EXEC reply (3 s bound) and whether a fresh
              connection still gets PONG; LPOP and BLMPOP are the controls.
Usage: txnfix4_probes.py --probe P --binary B --label L
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

PORT = 21470


def fields(c, section):
    reply = c.must('INFO', section).decode()
    return dict(line.split(':', 1) for line in reply.split('\r\n') if ':' in line)


class Server:
    def __init__(self, binary, mode, atomic, extra=()):
        self.dir = Path(tempfile.mkdtemp(prefix='txnfix4-probe-', dir=ROOT / 'build'))
        argv = [str(binary), '--port', str(PORT), '--bind', '127.0.0.1', '--dir', str(self.dir),
                '--save', '', '--shards', '16', '--databases', '16', '--atomic', str(atomic),
                '--read-local', '0', '--flip-auto', '0', '--enable-debug-command', 'yes',
                *extra]
        argv += ['--ratio', '6:2'] if mode == '2s' else ['--thread-mode', 'fused']
        self.log = (self.dir / 'server.log').open('w')
        self.proc = subprocess.Popen(['taskset', '-c', '61-68'] + argv, stdout=self.log,
                                     stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C'))
        wait_ready('127.0.0.1', PORT, timeout=60, process=self.proc).close()

    def close(self, kill=False):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL if kill else signal.SIGTERM)
            try:
                self.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)
        return self.proc.returncode


def server_ms(c):
    seconds, micros = c.must('TIME')
    return int(seconds) * 1000 + int(micros) // 1000


def aofrw(binary):
    rows = []
    for mode in ('2s', '1s'):
        for atomic in (0, 1):
            s = Server(binary, mode, atomic, ('--appendonly', 'yes'))
            try:
                c = Conn('127.0.0.1', PORT, timeout=120)
                c.must('DEBUG', 'SET-ACTIVE-EXPIRE', 0)
                for _ in range(1200):
                    if fields(c, 'persistence').get('aof_rewrite_in_progress') == '0':
                        break
                    time.sleep(0.05)
                shard = c.must('DEBUG', 'SHARDS', 'rw:h')[0][0]
                bigs, i = [], 0
                while len(bigs) < 2:
                    names = [f'rw:big:{j}' for j in range(i, i + 128)]
                    bigs += [n for n, w in zip(names, c.must('DEBUG', 'SHARDS', *names))
                             if w[0] == shard]
                    i += 128
                for big in bigs[:2]:
                    c.must('SETRANGE', big, 128 * 1024 * 1024 - 1, 'x')
                c.must('HSET', 'rw:h', 'f', 'v', 'n', '5', 'keep', 'k')
                c.must('HPEXPIRE', 'rw:h', 120, 'FIELDS', 2, 'f', 'n')
                deadline = c.must('HPEXPIRETIME', 'rw:h', 'FIELDS', 1, 'f')[0]
                while server_ms(c) <= deadline + 10:
                    time.sleep(0.001)
                before = fields(c, 'persistence').get('aof_rewrite_in_progress')
                replies = dict(hget=repr(c.cmd('HGET', 'rw:h', 'f')), hlen=c.cmd('HLEN', 'rw:h'),
                               hincrby=c.cmd('HINCRBY', 'rw:h', 'n', 1))
                after = fields(c, 'persistence').get('aof_rewrite_in_progress')
                for _ in range(2400):
                    if fields(c, 'persistence').get('aof_rewrite_in_progress') == '0':
                        break
                    time.sleep(0.05)
                final = c.cmd('HGETALL', 'rw:h')
                rows.append(dict(mode=mode, atomic=atomic, rewrite_in_progress=[before, after],
                                 replies=replies, after_rewrite=repr(final),
                                 correct=replies == dict(hget='None', hlen=1, hincrby=1) and
                                 final == [b'keep', b'k', b'n', b'1']))
                c.close()
            finally:
                s.close()
    return rows


def exec_mpop_aof(binary):
    rows = []
    for mode in ('2s', '1s'):
        for atomic in (0, 1):
            for body in (('LMPOP', '1', 'l', 'LEFT'), ('ZMPOP', '1', 'z', 'MIN'), ('LPOP', 'l'),
                         ('BLMPOP', '0.05', '1', 'l', 'LEFT')):
                s = Server(binary, mode, atomic, ('--appendonly', 'yes'))
                hung = False
                try:
                    c = Conn('127.0.0.1', PORT, timeout=3)
                    c.must('RPUSH', 'l', 'a', 'b')
                    c.must('ZADD', 'z', 1, 'a', 2, 'b')
                    c.must('MULTI')
                    queued = c.cmd(*body)
                    try:
                        reply = repr(c.cmd('EXEC'))
                    except (OSError, EOFError) as error:
                        reply, hung = f'no reply in 3 s ({type(error).__name__})', True
                    try:
                        fresh = repr(Conn('127.0.0.1', PORT, timeout=3).cmd('PING'))
                    except (OSError, EOFError) as error:
                        fresh = f'no reply in 3 s ({type(error).__name__})'
                    rows.append(dict(mode=mode, atomic=atomic, command=' '.join(body),
                                     queued=repr(queued), exec=reply, fresh_ping=fresh,
                                     hung=hung))
                finally:
                    s.close(kill=hung)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', choices=('aofrw', 'exec-mpop-aof'), required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--label', required=True)
    a = p.parse_args()
    out = ROOT / 'docs/txnfix4/probes'
    out.mkdir(parents=True, exist_ok=True)
    rows = aofrw(a.binary) if a.probe == 'aofrw' else exec_mpop_aof(a.binary)
    record = dict(probe=a.probe, label=a.label, binary=str(a.binary),
                  binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(), rows=rows)
    (out / f'{a.probe}-{a.label}.json').write_text(json.dumps(record, indent=2) + '\n')
    for row in rows:
        print(json.dumps(row))


if __name__ == '__main__':
    main()
