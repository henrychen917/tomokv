#!/usr/bin/env python3
"""AT4.12 directed schedules; errors and unopened windows always fail.

Each invocation owns its boots. No rates are measured. T3/T11a require a
single IO and multiple owners, and therefore use split 1:7 only.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time
import traceback

from _lib import Conn, RespError, encode, wait_ready

WRITE = "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}"
READ = "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}"


def stats(c):
    return {k.decode(): int(v) for k, v in
            (line.split(b':', 1) for line in c.must('INFO', 'stats').splitlines() if b':' in line)
            if v.lstrip(b'-').isdigit()}


def wait(predicate, message, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.001)
    raise AssertionError(message)


@contextlib.contextmanager
def boot(args, directory, mode, engine, atomic, oracle=False, single=False, aof=False):
    directory.mkdir(parents=True)
    port = args.port + int(oracle)
    binary = args.oracle if oracle else args.binary
    flags = ['--bind', '127.0.0.1', '--port', str(port), '--dir', str(directory.resolve()),
             '--save', '', '--appendonly', 'yes' if aof else 'no', '--appendfsync', 'no',
             '--enable-debug-command', 'yes']
    if not oracle:
        flags += ['--shards', '16', '--thread-mode', mode, '--net-io', engine,
                  '--atomic', str(atomic), '--read-local', '1' if mode == '1s' else '0',
                  '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0', '--databases', '16']
        if mode == '2s':
            flags += ['--ratio', '1:7' if single else '6:2']
    argv = ['taskset', '-c', args.cores, str(Path(binary).resolve()), *flags]
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    c = None
    try:
        c = wait_ready('127.0.0.1', port, process=p, timeout=20)
        c.sock.settimeout(4)
        yield c, port
    finally:
        if c:
            c.close()
        p.terminate()
        forced = False
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            forced = True
            p.kill()
            p.wait()
        (directory / 'exit.json').write_text(json.dumps(dict(rc=p.returncode, forced=forced)) + '\n')


def pair(c, prefix, oracle):
    if oracle:
        return [prefix + ':a', prefix + ':b']
    first = None
    for i in range(1000):
        key = f'{prefix}:{i}'
        placement = c.must('DEBUG', 'SHARDS', key)[0]
        if first is None:
            first = (key, placement)
        elif placement[1] != first[1][1]:
            print(json.dumps(dict(keys=[first[0], key], geometry=[first[1], placement])), flush=True)
            return [first[0], key]
    raise AssertionError('no two-owner pair')


def invocation(c, command, keys, source=WRITE):
    if command == 'EVALSHA':
        return (command, c.must('SCRIPT', 'LOAD', source), 2, *keys)
    if command == 'FCALL':
        name = 'at412_' + hashlib.sha1(source.encode()).hexdigest()[:12]
        c.must('FUNCTION', 'LOAD', 'REPLACE',
               f'#!lua name={name}\nredis.register_function("{name}",function(KEYS,ARGV) {source} end)')
        return (command, name, 2, *keys)
    return (command, source, 2, *keys)


def exact(c, keys, values):
    observed = c.must('MGET', *keys)
    assert observed == [str(v).encode() for v in values], (observed, values)


def settle(c):
    wait(lambda: stats(c).get('script_keys_armed', 0) == stats(c).get('script_keys_released', 0),
         'script PINs leaked')
    s = stats(c)
    for key in ('script_group_occ_giveups', 'script_crossshard_window_refusals',
                'atomic_txn_order_violations', 'atomic_gauge_underflows'):
        assert s.get(key, 0) == 0, (key, s.get(key))


def conflicts(c, port, keys, call, oracle, aof=False):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as script:
        if oracle:
            for _ in range(9):
                c.must('INCR', keys[1])
            reply = script.must(*call)
        else:
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 30000)
            script.send(*call)
            base = before['script_stage_owner_tasks']
            for n in range(9):
                wait(lambda: stats(c)['script_stage_owner_tasks'] >= base + 2*n + 1,
                     f'READ park {n+1} never opened')
                assert c.must('INCR', keys[1]) == n+1
            wait(lambda: stats(c).get('script_escalations', 0) > before.get('script_escalations', 0),
                 'ninth conflict did not escalate')
            reply = script.read()
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
        assert reply == [1, 10], reply
        assert c.must('INCR', keys[1]) == 11
    exact(c, keys, [1, 11])
    if not oracle:
        after = stats(c)
        assert after['script_group_occ_retries'] - before['script_group_occ_retries'] == 8
        assert after['script_escalations'] - before.get('script_escalations', 0) == 1
        assert after['script_escalated_commits'] - before.get('script_escalated_commits', 0) == 1
    if aof:
        c.must('DEBUG', 'LOADAOF')
        exact(c, keys, [1, 11])
    return [reply, 11]


def window(c, port, keys, call, oracle, mode, mget=False):
    c.must('MSET', keys[0], 'w', keys[1], 'w')
    count = 4 if mget else 4 * (8 if mode == '1s' else 6) + 1
    clients = [Conn('127.0.0.1', port, timeout=5) for _ in range(count)]
    try:
        before = stats(c)
        if not oracle:
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER' if mget else 'SCRIPT-STAGE-DEFER', 500000)
        for client in clients:
            client.send(*(('MGET', *keys) if mget else call))
        if mget:
            if not oracle:
                wait(lambda: stats(c).get('atomic_fanout_cuts', 0) >= before.get('atomic_fanout_cuts', 0)+4,
                     'four MGET cuts did not open')
            # The script must return while all four MGETs remain parked.
            assert c.must(*call) == [b'w', b'w']
            if not oracle:
                assert not any(select.select([x.sock], [], [], 0)[0] for x in clients), 'script waited for MGET'
        replies = [x.read() for x in clients]
        assert all(x == [b'w', b'w'] for x in replies), replies
        if not oracle:
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER' if mget else 'SCRIPT-STAGE-DEFER', 0)
            if not mget:
                assert stats(c).get('script_crossshard_window_waits', 0) > before.get('script_crossshard_window_waits', 0), 'FIFO never queued'
        return len(replies)
    finally:
        for x in clients:
            x.close()


def partial(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as script:
        if oracle:
            assert c.must('INCR', keys[1]) == 1
            reply = script.must(*call)
        else:
            before = stats(c)
            c.must('DEBUG', 'SCRIPT-APPLY-DEFER', 250000)
            script.send(*call)
            wait(lambda: stats(c)['script_apply_owner_tasks'] > before['script_apply_owner_tasks'],
                 'lead APPLY did not install')
            assert c.must('GET', keys[0]) == b'0', 'partial candidate visible'
            assert c.must('INCR', keys[1]) == 1
            reply = script.read()
            c.must('DEBUG', 'SCRIPT-APPLY-DEFER', 0)
            assert stats(c)['script_escalations'] == before.get('script_escalations', 0)+1
        assert reply == [1, 2], reply
    exact(c, keys, [1, 2])
    return reply


def save(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    with contextlib.closing(Conn('127.0.0.1', port, timeout=4)) as script:
        if not oracle:
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 250000)
        script.send(*call)
        if not oracle:
            wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'],
                 'S1 stage window never opened')
        assert c.must('SAVE') == b'OK'
        assert script.read() == [1, 1]
    exact(c, keys, [1, 1])
    return [1, 1]


def storm(c, port, keys, call, oracle, seconds=30, bgsave=False):
    c.must('MSET', keys[0], 0, keys[1], 0)
    start = threading.Barrier(21)
    stop = threading.Event()
    counts = [0]*20
    errors = []
    def worker(i):
        try:
            with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as client:
                start.wait(timeout=10)
                while not stop.is_set():
                    if i < 8:
                        reply = client.must(*call)
                        assert isinstance(reply, list) and len(reply) == 2, reply
                    elif i < 16:
                        client.raw(encode('MULTI') + encode('INCR', keys[0]) +
                                   encode('INCR', keys[1]) + encode('EXEC'))
                        assert [client.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
                        reply = client.read()
                        assert isinstance(reply, list) and len(reply) == 2, reply
                    else:
                        client.must('INCR', keys[(i-16)%2])
                    counts[i] += 1
        except Exception as e:
            errors.append(repr(e))
            stop.set()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    start.wait(timeout=10)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline and not stop.is_set():
            now = time.monotonic()
            assert c.must('PING') == b'PONG'
            assert time.monotonic()-now < 1, 'PING stalled'
            if bgsave:
                reply = c.cmd('BGSAVE')
                assert reply == b'Background saving started' or isinstance(reply, RespError), reply
            time.sleep(.1)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=6)
    assert not any(t.is_alive() for t in threads), 'storm workers stuck'
    assert not errors, errors
    both = sum(counts[:16])
    exact(c, keys, [both+sum(counts[16::2]), both+sum(counts[17::2])])
    assert all(counts), counts
    return dict(counts=counts)


def run_case(args, c, port, oracle, mode, command):
    keys = pair(c, f'at412:{args.case}:{command}', oracle)
    call = invocation(c, command, keys, READ if args.case in ('T2', 'T3') else WRITE)
    if args.case in ('T1', 'T12'):
        result = conflicts(c, port, keys, call, oracle, aof=args.case == 'T12')
    elif args.case in ('T2', 'T3'):
        result = window(c, port, keys, call, oracle, mode, mget=args.case == 'T3')
    elif args.case == 'T4':
        result = partial(c, port, keys, call, oracle)
    elif args.case == 'T5':
        # Each mechanism must fire in this boot, with cumulative counters.
        ro = invocation(c, command, keys, READ)
        window(c, port, keys, ro, oracle, mode)
        result = conflicts(c, port, keys, call, oracle)
    elif args.case == 'T11a':
        result = save(c, port, keys, call, oracle)
    else:
        result = storm(c, port, keys, call, oracle, args.seconds, bgsave=args.case == 'T11b')
    if not oracle:
        settle(c)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--case', choices=['T1','T2','T3','T4','T5','T6','T11a','T11b','T12'], required=True)
    p.add_argument('--modes', nargs='+', default=['1s','2s'])
    p.add_argument('--engines', nargs='+', default=['uring','epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0,1])
    p.add_argument('--commands', nargs='+', default=['EVAL','EVALSHA','FCALL'])
    p.add_argument('--seconds', type=float, default=30)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    single = args.case in ('T3','T11a')
    for oracle in (True, False):
        cells = [('redis','redis',0)] if oracle else [
            (m,e,a) for m in (['2s'] if single else args.modes)
            for e in args.engines for a in args.atomics]
        for mode, engine, atomic in cells:
            for command in args.commands:
                label = f'{mode}-{engine}-{atomic}-{command}'
                result = dict(case=args.case, leg=label)
                try:
                    with boot(args, args.output/label, mode, engine, atomic, oracle,
                              single, args.case == 'T12') as (c, port):
                        result['value'] = run_case(args, c, port, oracle, mode, command)
                    result['pass'] = True
                except Exception:
                    result.update(pass_=False, error=traceback.format_exc())
                results.append(result)
                print(json.dumps(result), flush=True)
                (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    return any(not r.get('pass') for r in results)


if __name__ == '__main__':
    raise SystemExit(main())
