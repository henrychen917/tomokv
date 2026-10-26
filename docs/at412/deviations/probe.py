#!/usr/bin/env python3
"""Pre-existing deviations found by the at412 rows (no rates; one server at a time).

XS-NOTIFY-1: a cross-owner script publishes no keyspace event and no CLIENT TRACKING
             invalidation for its writes (a one-key script and a plain SET do).
XS-OOM-1:    an EVAL/EVALSHA cross-owner script refused by maxmemory omits Redis's
             ". script: <sha>, on @user_script:1." suffix (the one-key path keeps it).
Usage: probe.py BINARY|redis MODE ATOMIC PORT CORES
"""
import json, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tests'))
from _lib import Conn, wait_ready

binary, mode, atomic, port, cores = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
redis = binary == 'redis'
data = tempfile.mkdtemp(prefix='at412-dev-')
if redis:
    argv = ['/home/user/Projects/redis74/src/redis-server', '--bind', '127.0.0.1', '--port', str(port),
            '--dir', data, '--save', '', '--enable-debug-command', 'yes']
else:
    argv = [binary, '--bind', '127.0.0.1', '--port', str(port), '--dir', data, '--save', '',
            '--shards', '16', '--thread-mode', mode, '--atomic', atomic, '--enable-debug-command', 'yes',
            '--databases', '16', '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
    if mode == '2s':
        argv += ['--ratio', '6:2']
proc = subprocess.Popen(['taskset', '-c', cores, *argv], stdout=open(data + '/log', 'w'), stderr=subprocess.STDOUT)
result = dict(binary=binary, mode=mode, atomic=atomic)
try:
    c = wait_ready('127.0.0.1', port, process=proc, timeout=20)
    if redis:
        k = ['dev:a', 'dev:b']
    else:
        first = None
        for i in range(1000):
            key = f'dev:{i}'
            owner = c.must('DEBUG', 'SHARDS', key)[0][1]
            if first is None:
                first = (key, owner)
            elif owner != first[1]:
                k = [first[0], key]
                break
    c.must('MSET', k[0], 1, k[1], 1)
    c.must('CONFIG', 'SET', 'notify-keyspace-events', 'KEA')
    sub = Conn('127.0.0.1', port, timeout=3)
    sub.must('PSUBSCRIBE', '__keyevent@0__:*')
    track = Conn('127.0.0.1', port, timeout=3)
    track.cmd('HELLO', '3')
    track.must('CLIENT', 'TRACKING', 'ON')
    track.must('GET', k[0]); track.must('GET', k[1])
    s = Conn('127.0.0.1', port, timeout=5)
    result['two_key_eval'] = repr(s.must('EVAL', "redis.call('SET',KEYS[1],'x'); redis.call('SET',KEYS[2],'y'); return 1", 2, *k))
    def drain(sock):
        time.sleep(.5); sock.setblocking(False)
        try:
            out = sock.recv(65536)
        except BlockingIOError:
            out = b''
        sock.setblocking(True)
        return out
    result['events_after_two_key_script'] = drain(sub.sock).decode(errors='replace')
    result['tracking_after_two_key_script'] = drain(track.sock).decode(errors='replace')
    s.must('EVAL', "return redis.call('SET',KEYS[1],'z')", 1, k[0])
    result['events_after_one_key_script'] = drain(sub.sock).decode(errors='replace')
    result['tracking_after_one_key_script'] = drain(track.sock).decode(errors='replace')
    c.must('CONFIG', 'SET', 'maxmemory', 1)
    oom = s.cmd('EVAL', "return redis.call('SET',KEYS[1],'oom')", 2, *k)
    result['two_key_eval_oom'] = str(oom)
    oom1 = s.cmd('EVAL', "return redis.call('SET',KEYS[1],'oom')", 1, k[0])
    result['one_key_eval_oom'] = str(oom1)
    c.must('CONFIG', 'SET', 'maxmemory', 0)
finally:
    proc.terminate(); proc.wait()
print(json.dumps(result, indent=2))
