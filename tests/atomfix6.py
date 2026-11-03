#!/usr/bin/env python3
"""AT5.1/AT5.2: concurrent MSET pairs, wide groups, captures and saved state.

Every phase counts replies, errors and tears. Captures must overlap the readers;
a missed capture window is rerolled on fresh keys, bounded, never skipped.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import random
import subprocess
import threading
import time

from _lib import Conn, encode, wait_ready
from _gate_process import stop_process


def info(conn):
    return dict(line.split(b':', 1) for line in conn.must('INFO', 'persistence').splitlines()
                if b':' in line)


@contextlib.contextmanager
def boot(a, label):
    a.output.mkdir(parents=True, exist_ok=True)
    assert not subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{a.port}'], text=True).strip()
    argv = ['taskset', '-c', a.cores, str(a.binary.resolve()), '--bind', '127.0.0.1',
            '--port', str(a.port), '--save', '', '--appendonly', 'no',
            '--dir', str(a.output.resolve()), '--dbfilename', 'atomfix6.rdb',
            '--databases', str(a.databases), '--enable-debug-command', 'yes']
    if not a.oracle:
        argv += ['--thread-mode', a.mode, '--read-local', str(a.read_local), '--atomic', '1',
                 '--shards', '16', '--net-io', a.engine]
        if a.mode == '2s':
            argv += ['--ratio', a.ratio]
    (a.output / (label + '-argv.json')).write_text(json.dumps(argv) + '\n')
    with (a.output / (label + '-server.log')).open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, LC_ALL='C'))
    conn = None
    try:
        conn = wait_ready('127.0.0.1', a.port, process=process, timeout=60)
        if a.databases > 1:
            assert conn.must('SELECT', 7) == b'OK'
        yield conn
    finally:
        if conn:
            conn.close()
        forced = stop_process(process)
        (a.output / (label + '-exit.json')).write_text(json.dumps(dict(rc=process.returncode, forced=forced)) + '\n')
        assert not forced and process.returncode == 0, (label, process.returncode)


def connection(a):
    c = Conn('127.0.0.1', a.port, timeout=60)
    if a.databases > 1:
        assert c.must('SELECT', 7) == b'OK'
    return c


def keys(admin, a, prefix):
    if a.oracle:
        return [[f'{prefix}:pair:{p}:{k}' for k in range(8)] for p in range(16)]
    by_shard = {}
    for offset in range(0, 8192, 256):
        names = [f'{prefix}:{i}' for i in range(offset, offset + 256)]
        for name, (sid, owner) in zip(names, admin.must('DEBUG', 'SHARDS', *names)):
            by_shard.setdefault(sid, (owner, []))[1].append(name)
        if len(by_shard) >= 8 and all(len(v[1]) >= 16 for v in by_shard.values()):
            break
    chosen = sorted(by_shard)[:8]
    first = chosen[0]
    second = next(s for s in by_shard if by_shard[s][0] != by_shard[first][0])
    chosen = [first, second] + [s for s in sorted(by_shard) if s not in (first, second)][:6]
    assert len(chosen) == 8 and all(len(by_shard[s][1]) >= 16 for s in chosen)
    result = [[by_shard[s][1][p] for s in chosen] for p in range(16)]
    assert len({s for s, _ in admin.must('DEBUG', 'SHARDS', *result[0])}) == 8
    return result


def phase(a, admin, pairs, label, wide=False, capture=False):
    for pair in pairs:
        assert admin.must('MSET', pair[0], 'initial', pair[1], 'initial') == b'OK'
    stop = threading.Event()
    lock = threading.Lock()
    result = dict(phase=label, writes=0, reads=0, torn=0, captures=0,
                  capture_samples=0, capture_reads=0, errors=[])
    capture_active = threading.Event()

    def writer(wid):
        with contextlib.closing(connection(a)) as c:
            rnd, seq = random.Random(wid), 0
            while not stop.is_set():
                commands = []
                for _ in range(16):
                    pair = pairs[rnd.randrange(len(pairs))]
                    seq += 1
                    value = f'{label}:{wid}:{seq}'
                    args = ['MSET']
                    for key in pair[:8 if wide else 2]:
                        args += [key, value]
                    commands.append(encode(*args))
                c.raw(b''.join(commands))
                assert all(c.read() == b'OK' for _ in commands), 'MSET error reply'
                with lock:
                    result['writes'] += len(commands)

    def reader(rid):
        with contextlib.closing(connection(a)) as c:
            rnd = random.Random(100 + rid)
            while not stop.is_set():
                chosen = [pairs[rnd.randrange(len(pairs))] for _ in range(16)]
                c.raw(b''.join(encode('MGET', *pair[:2]) for pair in chosen))
                replies = [c.read() for _ in chosen]
                assert all(isinstance(v, list) and len(v) == 2 for v in replies), 'MGET error reply'
                with lock:
                    result['reads'] += len(replies)
                    result['torn'] += sum(v[0] != v[1] for v in replies)
                    result['capture_reads'] += len(replies) if capture_active.is_set() else 0

    def saver():
        with contextlib.closing(connection(a)) as c:
            while not stop.is_set():
                active = info(c).get(b'rdb_bgsave_in_progress') == b'1'
                if active:
                    capture_active.set()
                    with lock:
                        result['capture_samples'] += 1
                else:
                    capture_active.clear()
                    assert c.must('BGSAVE').startswith(b'Background saving started')
                    with lock:
                        result['captures'] += 1
                stop.wait(.01)

    def checked(fn, *args):
        try:
            fn(*args)
        except BaseException as exc:
            with lock:
                result['errors'].append(repr(exc))
            stop.set()

    threads = [threading.Thread(target=checked, args=(writer, i)) for i in range(4)]
    threads += [threading.Thread(target=checked, args=(reader, i)) for i in range(2)]
    if capture:
        threads.append(threading.Thread(target=checked, args=(saver,)))
    for t in threads:
        t.start()
    stop.wait(a.seconds)
    stop.set()
    for t in threads:
        t.join(70)
    assert not any(t.is_alive() for t in threads), 'detector thread did not drain'
    deadline = time.monotonic() + 120
    while info(admin).get(b'rdb_bgsave_in_progress') == b'1':
        assert time.monotonic() < deadline, 'capture did not finish'
        time.sleep(.02)
    result['rest_torn'] = sum(admin.must('MGET', *pair[:2])[0] !=
                              admin.must('GET', pair[1]) for pair in pairs)
    print(json.dumps(result), flush=True)
    assert result['writes'] and result['reads'] and not result['errors'], result
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--mode', choices=['1s', '2s'], required=True)
    p.add_argument('--read-local', type=int, choices=[0, 1], required=True)
    p.add_argument('--databases', type=int, choices=[1, 16], required=True)
    p.add_argument('--engine', choices=['uring', 'epoll'], default='uring')
    p.add_argument('--seconds', type=float, default=8)
    p.add_argument('--filler', type=int, default=300000)
    p.add_argument('--oracle', action='store_true')
    a = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    results, all_pairs = [], []
    with boot(a, 'initial') as admin:
        for label, wide in [('steady', False), ('wide', True)]:
            pairs = keys(admin, a, label)
            all_pairs += pairs
            results.append(phase(a, admin, pairs, label, wide))
        value = 'f' * 100
        for offset in range(0, a.filler, 2000):
            batch = list(range(offset, min(a.filler, offset + 2000)))
            admin.raw(b''.join(encode('SET', f'filler:{i}', value) for i in batch))
            assert all(admin.read() == b'OK' for _ in batch)
        for attempt in range(3):
            pairs = keys(admin, a, f'capture-{attempt}')
            all_pairs += pairs
            result = phase(a, admin, pairs, f'capture-{attempt}', wide=True, capture=True)
            results.append(result)
            if result['capture_samples'] and result['capture_reads']:
                break
        else:
            raise AssertionError('capture/read overlap never armed in three fresh attempts')
        # Freeze all writers, re-read after cleanup, then SAVE exactly that state.
        time.sleep(.3)
        frozen = [admin.must('MGET', *pair[:2]) for pair in all_pairs]
        rest_torn = sum(v[0] != v[1] for v in frozen)
        assert admin.must('SAVE') == b'OK'
    with boot(a, 'restart') as admin:
        restored = [admin.must('MGET', *pair[:2]) for pair in all_pairs]
        restart_torn = sum(v[0] != v[1] for v in restored)
        assert restored == frozen, 'SAVE/restart changed the frozen values'
    summary = dict(mode=a.mode, read_local=a.read_local, databases=a.databases,
                   phases=results, rest_pairs=len(frozen), rest_torn=rest_torn,
                   restart_pairs=len(restored), restart_torn=restart_torn)
    (a.output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
    (a.output / 'atomfix6.rdb').unlink(missing_ok=True)
    assert not rest_torn and not restart_torn and all(not r['torn'] and not r['rest_torn'] for r in results), summary


if __name__ == '__main__':
    main()
