#!/usr/bin/env python3
"""Own-child GDB checks of the two pre-fix AOF hangs; no attach permission needed."""
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import threading
import time

from wave15 import ROOT, BUILD, DOC, sha, save
sys.path.insert(0, str(ROOT/'tests'))
from _lib import Conn
from wave15_aof import settled


def run(kind):
    tag = kind+'-everysec-db16-epoll'
    out = DOC/'aof-stacks'/tag
    out.mkdir(parents=True, exist_ok=False)
    data = BUILD/('aof-stack-'+tag)
    data.mkdir(exist_ok=False)
    binary = BUILD/'merged-before-integration-fixes'
    args = [str(binary), '--bind', '127.0.0.1', '--port', '20099', '--protected-mode', 'no',
        '--shards', '16', '--databases', '16', '--net-io', 'epoll',
        '--read-local', '0', '--key-lb', '0', '--client-lb', '0',
        '--flip-auto', '0', '--enable-debug-command', 'yes', '--save', '', '--dir', str(data),
        '--appendonly', 'yes', '--appendfsync', 'everysec', '--auto-aof-rewrite-min-size', '1mb',
        '--auto-aof-rewrite-percentage', '100' if kind == 'large' else '0',
        '--atomic', '1' if kind == 'large' else '0',
        *(['--ratio', '6:2'] if kind == 'large' else ['--thread-mode', 'fused'])]
    proc = subprocess.Popen(['gdb', '-q', '-nx', '--interpreter=mi2', '--args', *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    events = queue.Queue()
    lines = []
    def read():
        for line in proc.stdout:
            lines.append(line); events.put(line)
    reader = threading.Thread(target=read, daemon=True); reader.start()
    def command(text, expected, timeout=10):
        proc.stdin.write(text+'\n'); proc.stdin.flush()
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            try: line = events.get(timeout=.2)
            except queue.Empty: continue
            if expected in line: return line
        raise AssertionError((text, 'GDB response missing'))
    record = dict(binary=str(binary), sha256=sha(binary), argv=args, cores=sorted(os.sched_getaffinity(0)))
    client = None
    try:
        command('1-gdb-set pagination off', '1^done')
        command('2-gdb-set confirm off', '2^done')
        command('3-gdb-set disable-randomization off', '3^done')
        command('4-gdb-set mi-async on', '4^done')
        command('5-exec-run', '5^running')
        end = time.monotonic()+15
        while time.monotonic() < end:
            try:
                client = Conn('127.0.0.1', 20099, timeout=1, buffering=0)
                assert client.cmd('PING') == b'PONG'
                break
            except (OSError, AssertionError):
                if client: client.close(); client = None
                time.sleep(.02)
        assert client is not None, 'server did not boot under parent debugger'
        end = time.monotonic()+15
        while not settled(client):
            assert time.monotonic() < end, 'initial AOF rewrite did not settle'
            time.sleep(.01)
        if kind == 'participants':
            names = [b'LEFT']+[f'stack:key:{i}'.encode() for i in range(64)]
            placement = client.cmd('DEBUG', 'SHARDS', *names)
            index = next(i for i in range(1, len(names)) if placement[i][0] != placement[0][0])
            key = names[index]
            record['placement'] = dict(word=placement[0], key=placement[index], key_name=key.decode())
            assert client.cmd('LPUSH', key, 'v') == 1
            assert client.cmd('MULTI') == b'OK'
            assert client.cmd('LMPOP', 1, key, 'LEFT') == b'QUEUED'
            client.send('EXEC')
        else:
            client.send('SETRANGE', 'big', 33554431, 'x')
        try:
            record['unexpected_reply'] = repr(client.read())
            raise AssertionError('PRE hang did not reproduce')
        except socket.timeout:
            record['reply_timed_out'] = True
        command('6-exec-interrupt --all', '*stopped', timeout=15)
        command('7-interpreter-exec console "thread apply all bt 18"', '7^done', timeout=30)
        record['backtrace_captured'] = True
        command('8-interpreter-exec console "kill"', '8^done')
        command('9-gdb-exit', '9^exit')
        proc.wait(timeout=5)
    finally:
        if client: client.close()
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        reader.join(timeout=2)
        (out/'gdb-mi.log').write_text(''.join(lines))
        save(out/'result.json', record)
    print(kind, 'captured', flush=True)


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(56, 64))
    os.environ['LC_ALL'] = 'C'
    for kind in sys.argv[1:] or ('participants', 'large'):
        assert kind in ('participants', 'large')
        run(kind)
