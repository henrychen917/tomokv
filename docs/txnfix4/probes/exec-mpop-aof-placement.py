#!/usr/bin/env python3
"""MULTI; LMPOP 1 l LEFT; EXEC with appendonly yes: immediately after boot vs after the initial
AOF rewrite finished. Fresh server per trial."""
import os, signal, subprocess, sys, tempfile, time
sys.path.insert(0, '/home/user/Projects/cx-txnfix4/tests')
from _lib import Conn, wait_ready
binary, mode, wait_rw, body = sys.argv[1], sys.argv[2], sys.argv[3] == 'wait', sys.argv[4]
port = 21498
work = tempfile.mkdtemp(prefix='hangtiming-', dir='/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/hang')
flags = ['--port', str(port), '--bind', '127.0.0.1', '--dir', work, '--save', '', '--appendonly', 'yes',
         '--shards', '16', '--databases', '16', '--atomic', '0', '--read-local', '0', '--flip-auto', '0',
         '--enable-debug-command', 'yes']
flags += ['--ratio', '3:2'] if mode == '2s' else ['--thread-mode', 'fused']
proc = subprocess.Popen(['taskset', '-c', '69-73', binary] + flags, stdout=open(work + '/log', 'w'),
                        stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C'))
def info(c):
    r = c.must('INFO', 'persistence').decode()
    return dict(l.split(':', 1) for l in r.split('\r\n') if ':' in l)
hung = False
try:
    c = Conn('127.0.0.1', port, timeout=3) if False else wait_ready('127.0.0.1', port, timeout=60, process=proc)
    rw0 = info(c).get('aof_rewrite_in_progress')
    if wait_rw:
        for _ in range(600):
            if info(c).get('aof_rewrite_in_progress') == '0': break
            time.sleep(0.05)
    c.sock.settimeout(3)
    io = c.cmd('DEBUG', 'IO-THREAD'); owner = c.cmd('DEBUG', 'SHARDS', 'l')
    print('conn io thread', io, 'key l shard/owner', owner, flush=True)
    c.must('RPUSH', 'l', 'a', 'b'); c.must('ZADD', 'z', 1, 'a', 2, 'b')
    rw1 = None
    c.must('MULTI'); c.cmd(*body.split())
    try: reply = c.cmd('EXEC')
    except (OSError, EOFError) as e: reply, hung = f'no reply ({type(e).__name__})', True
    try: ping = Conn('127.0.0.1', port, timeout=3).cmd('PING')
    except (OSError, EOFError) as e: ping = f'no reply ({type(e).__name__})'
    try: rw2 = info(Conn('127.0.0.1', port, timeout=3)).get('aof_rewrite_in_progress')
    except (OSError, EOFError) as e: rw2 = 'n/a'
    print(f'{mode} wait_rw={wait_rw} body={body!r} rewrite_at_boot={rw0} exec={reply!r} fresh_ping={ping!r} rewrite_after={rw2}')
finally:
    proc.send_signal(signal.SIGKILL if hung else signal.SIGTERM)
    proc.wait()
