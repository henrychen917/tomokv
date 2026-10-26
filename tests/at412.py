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
import signal
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
    if getattr(args, 'debug_stacks', False) and not oracle:
        argv = ['taskset', '-c', args.cores, 'gdb', '-q', '-batch',
                '-ex', 'set pagination off', '-ex', 'handle SIGINT stop nopass',
                '-ex', 'run', '-ex', 'thread apply all bt full', '--args', *argv[3:]]
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    c = None
    try:
        debug = getattr(args, 'debug_stacks', False) and not oracle
        c = wait_ready('127.0.0.1', port, process=None if debug else p, timeout=20)
        if debug:
            info = dict(line.split(b':', 1) for line in c.must('INFO', 'server').splitlines() if b':' in line)
            pid = int(info[b'process_id'])
            assert Path(f'/proc/{pid}/exe').resolve() == Path(binary).resolve(), 'debug boot PID mismatch'
        c.sock.settimeout(4)
        yield c, port
    except Exception:
        if getattr(args, 'debug_stacks', False) and not oracle and p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        raise
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


def conflicts(c, port, keys, call, oracle, aof=False, during=None):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as script:
        if oracle:
            for _ in range(9):
                c.must('INCR', keys[1])
            reply = script.must(*call)
        else:
            if during:
                c.must('DEBUG', 'SCRIPT-STAGE-WATCH', script.must('CLIENT', 'ID'))
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 30000)
            script.send(*call)
            if during:
                during()
            base = before['script_stage_owner_tasks']
            for n in range(9):
                wait(lambda: stats(c).get('script_stage_watch_tasks', 0) >= n+1 if during else
                     stats(c)['script_stage_owner_tasks'] >= base + 2*n + 1,
                     f'READ park {n+1} never opened')
                assert c.must('INCR', keys[1]) == n+1
            wait(lambda: stats(c).get('script_escalations', 0) > before.get('script_escalations', 0),
                 'ninth conflict did not escalate')
            # Deliberately send before reading E's reply: T1/T12 require W to
            # encounter E, rather than merely checking an already serial run.
            c.send('INCR', keys[1])
            reply = script.read()
            tenth = c.read()
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
            if during:
                c.must('DEBUG', 'SCRIPT-STAGE-WATCH', 0)
        assert reply == [1, 10], reply
        if oracle:
            tenth = c.must('INCR', keys[1])
        assert tenth == 11, tenth
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


def combined(c, port, keys, call, command, oracle, mode):
    held_keys = pair(c, 'at412:combined-held', oracle)
    c.must('MSET', held_keys[0], 'w', held_keys[1], 'w')
    held_call = invocation(c, command, held_keys, READ)
    holders = [Conn('127.0.0.1', port, timeout=5) for _ in range(4*(8 if mode == '1s' else 6)+1)]
    before = stats(c)
    def during():
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 800000)
        for h in holders:
            h.send(*held_call)
        wait(lambda: stats(c)['script_crossshard_window_waits'] > before['script_crossshard_window_waits'],
             'combined FIFO window never opened', .2)
        assert stats(c)['atomic_inflight'] > 4, 'combined run did not hold >4 cuts'
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 30000)
    try:
        if oracle:
            for h in holders:
                h.send(*held_call)
        result = conflicts(c, port, keys, call, oracle, during=None if oracle else during)
        assert all(h.read() == [b'w', b'w'] for h in holders)
        return result
    finally:
        for h in holders:
            h.close()


def window(c, port, keys, call, oracle, mode, mget=False):
    c.must('MSET', keys[0], 'w', keys[1], 'w')
    count = 4 if mget else 4 * (8 if mode == '1s' else 6) + 1
    clients = [Conn('127.0.0.1', port, timeout=5) for _ in range(count)]
    try:
        ids = {x.must('CLIENT', 'ID') for x in clients} if mget else set()
        before = stats(c)
        if not oracle:
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER' if mget else 'SCRIPT-STAGE-DEFER', 500000)
        begin = time.monotonic()
        for client in clients:
            client.send(*(('MGET', *keys) if mget else call))
        if mget:
            if not oracle:
                def consumed():
                    rows = [dict(part.split(b'=', 1) for part in line.split())
                            for line in c.must('CLIENT', 'LIST').splitlines()]
                    held = [r for r in rows if int(r[b'id']) in ids and
                            r[b'cmd'] == b'mget' and r[b'qbuf'] == b'0']
                    return len(held) == 4
                # Four consumed fan-out frames in the single IO, each still
                # parked, prove four registrations at atomic 0 AND atomic 1.
                # atomic_fanout_cuts intentionally counts only atomic-OFF cuts.
                wait(consumed, 'four MGET frames were not admitted')
                assert not any(select.select([x.sock], [], [], 0)[0] for x in clients), 'MGET park missed'
            # The script must return while all four MGETs remain parked.
            assert c.must(*call) == [b'w', b'w']
            if not oracle:
                assert not any(select.select([x.sock], [], [], 0)[0] for x in clients), 'script waited for MGET'
        replies = [x.read() for x in clients]
        assert all(x == [b'w', b'w'] for x in replies), replies
        assert time.monotonic()-begin < ((count+3)//4+1)*.5+2, 'FIFO completion bound exceeded'
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


def storm(c, port, keys, call, oracle, seconds=30, bgsave=False, flip=False):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    start = threading.Barrier(21)
    stop = threading.Event()
    counts = [0]*20
    attempts = [0]*20
    errors = []
    def worker(i):
        try:
            with contextlib.closing(Conn('127.0.0.1', port, timeout=5)) as client:
                start.wait(timeout=10)
                while not stop.is_set():
                    attempts[i] += 1
                    if i < 8:
                        reply = client.must(*call)
                        assert isinstance(reply, list) and len(reply) == 2, reply
                    elif i < 16:
                        if i >= 12:
                            client.must('WATCH', *keys)
                        client.raw(encode('MULTI') + encode('INCR', keys[0]) +
                                   encode('INCR', keys[1]) + encode('EXEC'))
                        assert [client.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
                        reply = client.read()
                        if i >= 12 and reply is None:
                            continue
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
    next_flip = time.monotonic()+1
    flips = saves = 0
    try:
        while time.monotonic() < deadline and not stop.is_set():
            now = time.monotonic()
            assert c.must('PING') == b'PONG'
            assert time.monotonic()-now < 1, 'PING stalled'
            if bgsave:
                reply = c.cmd('BGSAVE')
                assert reply == b'Background saving started' or (
                    isinstance(reply, RespError) and 'Background save already in progress' in str(reply)), reply
                saves += reply == b'Background saving started'
            if flip and time.monotonic() >= next_flip:
                io = 4 if flips % 2 == 0 else 6
                if not oracle:
                    assert c.must('FLIP', io, 8-io) == b'OK'
                flips += 1
                next_flip += 1
            time.sleep(.1)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=6)
    assert not any(t.is_alive() for t in threads), 'storm workers stuck'
    assert not errors, errors
    both = sum(counts[:16])
    exact(c, keys, [both+sum(counts[16::2]), both+sum(counts[17::2])])
    assert all(attempts) and all(counts[:12]) and all(counts[16:]), (counts, attempts)
    if bgsave:
        assert saves > 0, 'no BGSAVE started'
        wait(lambda: b'rdb_bgsave_in_progress:0' in c.must('INFO', 'persistence'), 'BGSAVE did not finish', 10)
        assert b'rdb_last_bgsave_status:ok' in c.must('INFO', 'persistence')
    if not oracle:
        after = stats(c)
        assert after['atomic_group_wounds'] > before['atomic_group_wounds'], 'no group wound observed'
        if flip:
            assert flips > 0 and after['flip_completed'] >= before['flip_completed']+flips
            assert after['flip_clients_transferred'] > before['flip_clients_transferred'], 'no client transferred'
    return dict(counts=counts, attempts=attempts, flips=flips, saves=saves)


def transaction(c, commands):
    c.raw(encode('MULTI') + b''.join(encode(*cmd) for cmd in commands) + encode('EXEC'))
    assert c.read() == b'OK'
    for _ in commands:
        assert c.read() == b'QUEUED'
    return c.read()


def parallel(port, workers, timeout=25):
    errors = []
    def run(fn):
        try:
            with contextlib.closing(Conn('127.0.0.1', port, timeout=6)) as conn:
                fn(conn)
        except Exception:
            errors.append(traceback.format_exc())
    threads = [threading.Thread(target=run, args=(f,), daemon=True) for f in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
    assert not any(t.is_alive() for t in threads), 'concurrent actors exceeded bound'
    assert not errors, errors


def opposite(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    if not oracle:
        c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 3000)
    counts = [0, 0]
    def actor(i):
        ordered = call[:3] + tuple(keys if i == 0 else keys[::-1])
        def run(conn):
            for _ in range(40):
                reply = conn.must(*ordered)
                assert isinstance(reply, list) and len(reply) == 2, reply
                counts[i] += 1
        return run
    parallel(port, [actor(0), actor(1)])
    exact(c, keys, [80, 80])
    assert counts == [40, 40]
    if not oracle:
        assert stats(c)['script_escalations'] > before['script_escalations'], 'no forced escalation'
    return counts


def blind(c, port, keys, command, oracle):
    call = invocation(c, command, keys,
        "for i=1,#KEYS do redis.call('SET',KEYS[i],ARGV[1]) end return 1")
    before = stats(c)
    if not oracle:
        c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 3000)
    def script(conn):
        for _ in range(80):
            assert conn.must(*call, 'S') == 1
    def writer(conn):
        for _ in range(80):
            assert conn.must('MSET', keys[0], 'M', keys[1], 'M') == b'OK'
    parallel(port, [script, writer])
    result = c.must('MGET', *keys)
    assert result in ([b'S', b'S'], [b'M', b'M']), result
    if not oracle:
        assert stats(c)['atomic_txn_blind_restarts'] > before['atomic_txn_blind_restarts'], 'blind restart window never opened'
    return [v.decode() for v in result]


def crowded(c, port, keys, call, oracle):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    clients = [Conn('127.0.0.1', port, timeout=8) for _ in range(169)]
    try:
        holder = clients[0]
        if not oracle:
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 2000000)
        holder.raw(encode('MULTI')+encode('GET', keys[0])+encode('GET', keys[1])+
                   encode('SET', keys[0]+':holder', 1)+encode('EXEC'))
        assert [holder.read() for _ in range(4)] == [b'OK']+[b'QUEUED']*3
        if not oracle:
            wait(lambda: stats(c)['atomic_txn_intents_live'] > before['atomic_txn_intents_live'], 'holder never placed')
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 0)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 1000)
        for x in clients[1:129]:
            x.send(*call)
        for x in clients[129:161]:
            x.raw(encode('MULTI')+encode('INCR', keys[0])+encode('INCR', keys[1])+encode('EXEC'))
            assert [x.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
        for x in clients[161:]:
            x.send('INCR', keys[0])
        if not oracle:
            wait(lambda: stats(c).get('script_waiters_peak', 0) > 64, 'never had >64 simultaneous waiters', 1.8)
            assert c.must('PING') == b'PONG'
        assert holder.read() == [b'0', b'0', b'OK']
        for x in clients[1:161]:
            r = x.read()
            assert isinstance(r, list) and len(r) == 2 and all(isinstance(v, int) for v in r), r
        for x in clients[161:]:
            assert isinstance(x.read(), int)
        exact(c, keys, [168, 160])
        return dict(scripts=128, execs=32, writers=8,
                    peak=0 if oracle else stats(c)['script_waiters_peak'])
    finally:
        for x in clients:
            x.close()


def same_shard(c, key, oracle):
    if oracle:
        return key+':peer'
    sid = c.must('DEBUG', 'SHARDS', key)[0][0]
    for n in range(1000):
        candidate = f'{key}:peer:{n}'
        if c.must('DEBUG', 'SHARDS', candidate)[0][0] == sid:
            return candidate
    raise AssertionError('no same-shard peer')


def episode(c, port, keys, call, oracle, disconnect=False):
    peer = same_shard(c, keys[0], oracle)
    c.must('MSET', keys[0], 0, keys[1], 0, peer, 0)
    before = stats(c)
    with contextlib.ExitStack() as stack:
        h, old, writer, young = [stack.enter_context(contextlib.closing(
            Conn('127.0.0.1', port, timeout=6))) for _ in range(4)]
        if oracle:
            assert transaction(h, [('GET', peer), ('GET', keys[1]), ('SET', peer, 0)]) == [b'0', b'0', b'OK']
            assert old.must(*call) == [1, 1]
            if not disconnect:
                assert writer.must('MSET', keys[0], 100, peer, 100) == b'OK'
                assert young.must(*call) == [101, 2]
        else:
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 1500000)
            h.raw(encode('MULTI')+encode('GET', peer)+encode('GET', keys[1])+encode('SET', peer, 0)+encode('EXEC'))
            assert [h.read() for _ in range(4)] == [b'OK']+[b'QUEUED']*3
            wait(lambda: stats(c)['atomic_txn_intents_live'] > before['atomic_txn_intents_live'], 'EXEC holder never opened')
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 0)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 1000)
            base = stats(c)
            old.send(*call)
            wait(lambda: stats(c)['script_escalations'] > base['script_escalations'] and
                 stats(c)['script_stage_owner_tasks'] >= base['script_stage_owner_tasks']+3,
                 'older E never read under its first claim', 1)
            if disconnect:
                old.close()
            else:
                writer.send('MSET', keys[0], 100, peer, 100)
                wait(lambda: stats(c)['atomic_txn_writer_marks'] > before['atomic_txn_writer_marks'], 'W did not open its episode', .3)
                young.send(*call)
                wait(lambda: stats(c)['script_escalations'] >= base['script_escalations']+2,
                     'younger E did not escalate after the stamp', .6)
            assert c.must('PING') == b'PONG'
            assert h.read() == [b'0', b'0', b'OK']
            if not disconnect:
                assert old.read() == [1, 1]
                assert writer.read() == b'OK'
                assert young.read() == [101, 2]
            else:
                wait(lambda: c.must('MGET', *keys) == [b'1', b'1'], 'dispatched disconnected E did not finish')
    values = [1, 1] if disconnect else [101, 2]
    exact(c, keys, values)
    return values


def errors(c, port, keys, command, oracle):
    c.must('SET', keys[0], 0)
    c.must('RPUSH', keys[1], 'list')
    call = invocation(c, command, keys, "redis.call('INCR',KEYS[1]); return redis.call('INCR',KEYS[2])")
    with contextlib.closing(Conn('127.0.0.1', port, timeout=6)) as script:
        if oracle:
            assert c.must('INCR', keys[0]) == 1
            reply = script.cmd(*call)
        else:
            before = stats(c)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 100000)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            script.send(*call)
            wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'], 'WRONGTYPE conflict window absent')
            assert c.must('INCR', keys[0]) == 1
            reply = script.read()
            assert stats(c)['script_escalations'] == before['script_escalations']+1, 'WRONGTYPE did not escalate'
        assert isinstance(reply, RespError) and str(reply).startswith('WRONGTYPE'), reply
        assert c.must('GET', keys[0]) == b'2', 'Lua writes before WRONGTYPE were lost'
        assert c.must('LRANGE', keys[1], 0, -1) == [b'list']
        oom_call = invocation(c, command, keys, "return redis.call('SET',KEYS[1],'oom')")
        c.must('CONFIG', 'SET', 'maxmemory', 1)
        try:
            oom = script.cmd(*oom_call)
            assert isinstance(oom, RespError) and str(oom).startswith('OOM'), oom
        finally:
            c.must('CONFIG', 'SET', 'maxmemory', 0)
        assert c.must('GET', keys[0]) == b'2'
    return dict(wrongtype=str(reply), oom=str(oom), kept=2)


def readonly_notifications(c, port, keys, call, command, oracle):
    c.must('CONFIG', 'SET', 'notify-keyspace-events', 'KEA')
    with contextlib.closing(Conn('127.0.0.1', port, timeout=3)) as sub:
        assert sub.must('SUBSCRIBE', '__keyevent@0__:incr')[0] == b'subscribe'
        conflicts(c, port, keys, call, oracle)
        events = []
        sub.sock.settimeout(.2)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            if not select.select([sub.sock], [], [], .2)[0]:
                break
            event = sub.read()
            assert event[:2] == [b'message', b'__keyevent@0__:incr'], event
            events.append(event[2])
        assert events.count(keys[0].encode()) == 1 and events.count(keys[1].encode()) == 11 and len(events) == 12, events
    c.must('CONFIG', 'SET', 'notify-keyspace-events', '')
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    if command == 'FCALL':
        name = 'at412_readonly'
        c.must('FUNCTION', 'LOAD', 'REPLACE', '#!lua name='+name+'\n'+
            "redis.register_function{function_name='"+name+"',callback=function(KEYS,ARGV) "+READ+
            " end,flags={'no-writes'}}")
        calls = [('FCALL_RO', name, 2, *keys), ('FCALL', name, 2, *keys)]
    else:
        source = '#!lua flags=no-writes\n'+READ
        arg = c.must('SCRIPT', 'LOAD', source) if command == 'EVALSHA' else source
        calls = [(command+'_RO', arg, 2, *keys), (command, arg, 2, *keys)]
    def writer(conn):
        for n in range(100):
            conn.must('MSET', keys[0], n, keys[1], n)
    def reader(conn):
        for invocation_ in calls:
            for _ in range(40):
                r = conn.must(*invocation_)
                assert isinstance(r, list) and len(r) == 2 and r[0] == r[1], r
    parallel(port, [writer, reader])
    if not oracle:
        assert stats(c)['script_escalations'] == before['script_escalations'], 'read-only script escalated'
    return dict(events=12, readonly=80)


def disconnect_shutdown(c, port, keys, call, command, oracle, mode):
    episode(c, port, keys, call, oracle, disconnect=True)
    ro = invocation(c, command, keys, READ)
    clients = [Conn('127.0.0.1', port, timeout=5) for _ in range(4*(8 if mode == '1s' else 6)+1)]
    try:
        before = stats(c)
        if not oracle:
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 300000)
        for x in clients:
            x.send(*ro)
        if not oracle:
            wait(lambda: stats(c)['script_crossshard_window_waits'] > before['script_crossshard_window_waits'], 'disconnect FIFO never queued')
    finally:
        for x in clients:
            x.close()
    if not oracle:
        wait(lambda: stats(c)['atomic_inflight'] == 0 and stats(c)['atomic_txn_intents_live'] == 0,
             'disconnect left credits or claims', 6)
        settle(c)
    exact(c, keys, [1, 1])
    assert c.must('PING') == b'PONG'
    # Leave real script calls in flight when shutdown is requested.
    peers = [Conn('127.0.0.1', port, timeout=5) for _ in range(8)]
    try:
        for x in peers:
            x.send(*call)
        c.send('SHUTDOWN', 'NOSAVE')
        try:
            reply = c.read()
        except (EOFError, ConnectionError, OSError):
            reply = None
        assert reply is None or reply == b'OK', reply
    finally:
        for x in peers:
            x.close()
    return dict(disconnect=[1, 1], shutdown=True)


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
        result = combined(c, port, keys, call, command, oracle, mode)
    elif args.case == 'T11a':
        result = save(c, port, keys, call, oracle)
    elif args.case == 'T7':
        result = episode(c, port, keys, call, oracle)
    elif args.case == 'T8':
        result = opposite(c, port, keys, call, oracle)
    elif args.case == 'T9':
        result = blind(c, port, keys, command, oracle)
    elif args.case == 'T13':
        result = crowded(c, port, keys, call, oracle)
    elif args.case == 'T14':
        result = errors(c, port, keys, command, oracle)
    elif args.case == 'T15':
        return disconnect_shutdown(c, port, keys, call, command, oracle, mode)
    elif args.case == 'T16':
        result = readonly_notifications(c, port, keys, call, command, oracle)
    else:
        assert args.case in ('T6', 'T10', 'T11b')
        result = storm(c, port, keys, call, oracle, args.seconds,
                       bgsave=args.case == 'T11b', flip=args.case == 'T10')
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
    p.add_argument('--case', choices=[f'T{i}' for i in range(1,17) if i != 11]+['T11a','T11b'], required=True)
    p.add_argument('--modes', nargs='+', default=['1s','2s'])
    p.add_argument('--engines', nargs='+', default=['uring','epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0,1])
    p.add_argument('--commands', nargs='+', default=['EVAL','EVALSHA','FCALL'])
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--debug-stacks', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    references = {}
    single = args.case in ('T3','T11a')
    for oracle in (True, False):
        cells = [('redis','redis',0)] if oracle else [
            (m,e,a) for m in (['2s'] if single or args.case == 'T10' else args.modes)
            for e in args.engines for a in args.atomics]
        for mode, engine, atomic in cells:
            for command in args.commands:
                label = f'{mode}-{engine}-{atomic}-{command}'
                result = dict(case=args.case, leg=label)
                try:
                    with boot(args, args.output/label, mode, engine, atomic, oracle,
                              single, args.case == 'T12') as (c, port):
                        result['value'] = run_case(args, c, port, oracle, mode, command)
                    if args.case == 'T15':
                        exited = json.loads((args.output/label/'exit.json').read_text())
                        assert exited == dict(rc=0, forced=False), exited
                    if args.case == 'T14':
                        if oracle:
                            references[command] = result['value']
                        else:
                            assert result['value'] == references[command], (result['value'], references[command])
                    result['pass'] = True
                except Exception:
                    result.update(pass_=False, error=traceback.format_exc())
                results.append(result)
                print(json.dumps(result), flush=True)
                (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    return any(not r.get('pass') for r in results)


if __name__ == '__main__':
    raise SystemExit(main())
