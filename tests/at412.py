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
                '-ex', 'set print elements 8', '-ex', 'set print max-depth 4',
                '-ex', 'run', '-ex', 'thread apply all bt full', '--args', *argv[3:]]
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    c = None
    original_read = Conn.read
    stopped = threading.Event()
    def diagnostic_read(conn):
        try:
            return original_read(conn)
        except TimeoutError:
            if not stopped.is_set():
                stopped.set()
                p.send_signal(signal.SIGINT)
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
            raise
    try:
        debug = getattr(args, 'debug_stacks', False) and not oracle
        c = wait_ready('127.0.0.1', port, process=None if debug else p, timeout=20)
        if debug:
            info = dict(line.split(b':', 1) for line in c.must('INFO', 'server').splitlines() if b':' in line)
            pid = int(info[b'process_id'])
            assert Path(f'/proc/{pid}/exe').resolve() == Path(binary).resolve(), 'debug boot PID mismatch'
            Conn.read = diagnostic_read
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
        Conn.read = original_read
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
    """T11a, single-IO boot: the one IO thread runs the snapshot drain, so nothing that needs
    that IO can close an apply window while it spins.
    S1: SAVE while a script is parked at READ. The script reaches Final on an EX; only the
        owner-side window close at Final lets the drain end (PRE: SAVE never returns).
    H2: BGSAVE while a forced-escalation script, parked at READ, has met a rival write. It
        hands off at that conflict; only the EX-side window close at the hand-off lets the drain
        end, and E redispatches from the IO lane after the snapshot barrier clears."""
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
    with contextlib.closing(Conn('127.0.0.1', port, timeout=4)) as script, \
         contextlib.closing(Conn('127.0.0.1', port, timeout=4)) as rival:
        if oracle:
            assert rival.must('INCR', keys[1]) == 2
            assert c.must('BGSAVE') == b'Background saving started'
            assert script.must(*call) == [2, 3]
        else:
            before = stats(c)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            script.send(*call)
            wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'],
                 'H2 stage window never opened')
            assert rival.must('INCR', keys[1]) == 2
            assert c.must('BGSAVE') == b'Background saving started'
            assert script.read() == [2, 3]
            after = stats(c)
            assert after['script_escalations'] == before['script_escalations']+1, 'H2 hand-off did not happen'
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 0)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
        wait(lambda: b'rdb_bgsave_in_progress:0' in c.must('INFO', 'persistence'), 'H2 BGSAVE did not finish', 10)
        assert b'rdb_last_bgsave_status:ok' in c.must('INFO', 'persistence')
    exact(c, keys, [2, 3])
    return [[1, 1], [2, 3]]


def stall_info(port):
    """Print the counters that locate a stall, from a fresh connection: a snapshot and the
    deltas over one second (which waits are still being polled), then return. A connection on
    the stalled thread cannot answer, so up to eight connections are tried."""
    def sample(probe):
        out = {}
        for line in probe.must('INFO', 'everything').decode(errors='replace').splitlines():
            key, _, value = line.partition(':')
            if value.lstrip('-').isdigit():
                out[key] = int(value)
        return out
    for attempt in range(8):
        try:
            with contextlib.closing(Conn('127.0.0.1', port, timeout=1)) as probe:
                first = sample(probe)
                time.sleep(1)
                second = sample(probe)
            keep = ('atomic_', 'script_', 'rdb_', 'snapshot', 'multi_', 'txn_')
            print('STALL-INFO', json.dumps({k: v for k, v in second.items() if k.startswith(keep) and v}), flush=True)
            print('STALL-DELTA', json.dumps({k: second[k]-first.get(k, 0) for k in second
                                            if second[k] != first.get(k, 0)}), flush=True)
            return
        except Exception as e:
            print('STALL-INFO attempt', attempt, repr(e), flush=True)


def storm(c, port, keys, call, oracle, seconds=30, bgsave=False, flip=False, refusals=None):
    c.must('MSET', keys[0], 0, keys[1], 0)
    before = stats(c)
    start = threading.Barrier(21)
    stop = threading.Event()
    hold = threading.Event()
    counts = [0]*20
    attempts = [0]*20
    errors = []
    # Diagnostic only (never set by the gate): AT412_STORM_MIX=scripts,execs,writers selects
    # which worker classes run; idle workers just wait at the barrier and count nothing.
    # T10: a connection that ever ran MULTI keeps a session and is never transferable
    # (migration_protocol_idle; PRE identical), so FLIP would refuse every attempt. The FLIP
    # storm therefore runs the scripts and plain writers only.
    mix = set(os.environ.get('AT412_STORM_MIX',
                             'scripts,writers' if flip else 'scripts,execs,writers').split(','))
    def enabled(i):
        return ('scripts' if i < 8 else 'execs' if i < 16 else 'writers') in mix
    def worker(i):
        try:
            # A FLIP may hold dispatch up to its own 5 s deadline before it refuses; an
            # operation waiting through it is not a stall (flip_under_load uses 15 s too).
            with contextlib.closing(Conn('127.0.0.1', port, timeout=15 if flip else 5)) as client:
                start.wait(timeout=10)
                while not stop.is_set() and enabled(i):
                    # FLIP transfers only quiescent connections (no in-flight op, no WATCH or
                    # MULTI state) and drains in-flight atomic work; under the uninterrupted
                    # storm it is refused on PRE and POST alike. Workers therefore start no NEW
                    # operation while a FLIP is issued, but every operation already in flight
                    # (escalated scripts included) must drain through it.
                    while hold.is_set() and not stop.is_set():
                        time.sleep(.001)
                    attempts[i] += 1
                    if i < 8:
                        reply = client.cmd(*call)
                        if isinstance(reply, RespError) and refusals is not None and (
                                str(reply).startswith('TRYAGAIN Cross-shard') or
                                str(reply).startswith('BUSY Cross-shard')):
                            refusals[0] += 1  # PRE control only: no write happened
                            continue
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
    flip_refusals = []
    flip_target = [4]
    flip_seconds = []
    flipper = Conn('127.0.0.1', port, timeout=30) if flip and not oracle else None
    try:
        while time.monotonic() < deadline and not stop.is_set():
            now = time.monotonic()
            try:
                assert c.must('PING') == b'PONG'
            except TimeoutError:
                stall_info(port)
                raise
            assert time.monotonic()-now < 1, 'PING stalled'
            if bgsave:
                try:
                    reply = c.cmd('BGSAVE')
                except TimeoutError:
                    stall_info(port)
                    raise
                assert reply == b'Background saving started' or (
                    isinstance(reply, RespError) and 'Background save already in progress' in str(reply)), reply
                saves += reply == b'Background saving started'
            if flip and time.monotonic() >= next_flip:
                io = flip_target[0]
                if oracle:
                    flips += 1
                else:
                    # A FLIP may legally refuse (for example when its drain cannot finish in
                    # time); only a completed FLIP counts, and at least one must complete.
                    began = time.monotonic()
                    hold.set()
                    try:
                        reply = flipper.cmd('FLIP', io, 8-io)
                    except TimeoutError:
                        stall_info(port)
                        raise
                    finally:
                        hold.clear()
                    flip_seconds.append(round(time.monotonic()-began, 3))
                    if reply == b'OK':
                        flips += 1
                        flip_target[0] = 6 if io == 4 else 4  # move only after a real change
                    else:
                        assert isinstance(reply, RespError), reply
                        flip_refusals.append(str(reply))
                next_flip += 1
            time.sleep(.1)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=16 if flip else 6)
    if errors or any(t.is_alive() for t in threads):
        stall_info(port)
        if flip:
            print('FLIP-LOG', json.dumps(dict(flips=flips, refusals=flip_refusals, seconds=flip_seconds)), flush=True)
    assert not any(t.is_alive() for t in threads), 'storm workers stuck'
    assert not errors, errors
    both = sum(counts[:16])
    exact(c, keys, [both+sum(counts[16::2]), both+sum(counts[17::2])])
    if mix == {'scripts', 'execs', 'writers'}:
        assert all(attempts) and all(counts[:12]) and all(counts[16:]), (counts, attempts)
    elif mix == {'scripts', 'writers'} and flip:
        assert all(counts[:8]) and all(counts[16:]), (counts, attempts)
    if bgsave:
        assert saves > 0, 'no BGSAVE started'
        wait(lambda: b'rdb_bgsave_in_progress:0' in c.must('INFO', 'persistence'), 'BGSAVE did not finish', 10)
        assert b'rdb_last_bgsave_status:ok' in c.must('INFO', 'persistence')
    if not oracle and (mix == {'scripts', 'execs', 'writers'} or flip):
        after = stats(c)
        if refusals is None and not flip:  # PRE controls have no escalated units to wound
            assert after['atomic_group_wounds'] > before['atomic_group_wounds'], 'no group wound observed'
        if refusals is None and flip:
            assert after['script_escalations'] > before['script_escalations'], 'no escalation during the FLIPs'
        if flip:
            flip_delta = {k: after.get(k, 0)-before.get(k, 0) for k in after if k.startswith('flip_')}
            # A FLIP may be refused when it cannot quiesce every connection in time (PRE does the
            # same under this storm); at least one must complete and move a connection.
            assert flips > 0 and after['flip_completed'] >= before['flip_completed']+flips, (flip_delta, flips, flip_refusals, flip_seconds)
            assert after['flip_clients_transferred'] > before['flip_clients_transferred'], ('no client transferred', flip_delta)
    if flipper:
        flipper.close()
    return dict(counts=counts, attempts=attempts, flips=flips, saves=saves, flip_refusals=flip_refusals,
                flip_max_seconds=max(flip_seconds, default=0),
                **({} if refusals is None else dict(pre_control_refusals=refusals[0])))


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
    """T9: escalated scripts against blind MSET groups (script intents keep MSET a blind group
    at atomic 0). Four script and four MSET connections race; every round must leave one whole
    generation and no refusal. A blind restart needs an E arrival to cross an MSET group that is
    still pending, which no hook can park without touching MSET's path, so rounds repeat (each
    one fully checked) until the counter moves, at most five times."""
    call = invocation(c, command, keys,
        "for i=1,#KEYS do redis.call('SET',KEYS[i],ARGV[1]) end return 1")
    before = stats(c)
    if not oracle:
        c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 1000)
    def script(conn):
        for _ in range(100):
            assert conn.must(*call, 'S') == 1
    def writer(conn):
        for _ in range(100):
            assert conn.must('MSET', keys[0], 'M', keys[1], 'M') == b'OK'
    rounds = 0
    while True:
        rounds += 1
        parallel(port, [script]*4 + [writer]*4, timeout=60)
        result = c.must('MGET', *keys)
        assert result in ([b'S', b'S'], [b'M', b'M']), ('torn generation', result)
        if oracle:
            break
        after = stats(c)
        if after['atomic_txn_blind_restarts'] > before['atomic_txn_blind_restarts']:
            break
        assert rounds < 5, 'blind restart window never opened in five checked rounds'
    if oracle:
        return dict(values=[v.decode() for v in result])
    after = stats(c)
    assert after['script_escalated_commits'] > before['script_escalated_commits'], 'no escalated commit'
    return dict(rounds=rounds,
                blind_restarts=after['atomic_txn_blind_restarts']-before['atomic_txn_blind_restarts'],
                wounds=after['atomic_group_wounds']-before['atomic_group_wounds'],
                escalated_commits=after['script_escalated_commits']-before['script_escalated_commits'])


def crowded(c, port, keys, call, oracle):
    """T13: more than 64 units wait on one key pair at once.
    E0 escalates (its parked APPLY meets a rival INCR, as in T4) and is parked again at its
    escalated APPLY, so it executes with started Write claims on both keys. 128 forced scripts
    then yield at APPLY, escalate and queue behind E0, with 32 EXECs and 8 INCR writers.
    The constant-time witness (registry visits per placement flat from 16 to 128 waiters) is
    the serverless at412-owner fixture on the same production placement code."""
    k0, k1 = keys
    c.must('MSET', k0, 0, k1, 0)
    holder = Conn('127.0.0.1', port, timeout=10)
    clients = [Conn('127.0.0.1', port, timeout=10) for _ in range(168)]
    scripts, execs, writers = clients[:128], clients[128:160], clients[160:]
    try:
        if oracle:
            assert c.must('INCR', k1) == 1
            assert holder.must(*call) == [1, 2]
        else:
            before = stats(c)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            c.must('DEBUG', 'SCRIPT-APPLY-DEFER', 2500000)
            holder.send(*call)
            wait(lambda: stats(c)['script_apply_owner_tasks'] > before['script_apply_owner_tasks'],
                 'E0 optimistic lead APPLY did not install')
            assert c.must('INCR', k1) == 1
            wait(lambda: stats(c)['script_escalations'] > before['script_escalations'], 'E0 did not escalate')
            base = stats(c)
            wait(lambda: stats(c)['script_apply_owner_tasks'] > base['script_apply_owner_tasks'],
                 'E0 escalated APPLY did not start')
            c.must('DEBUG', 'SCRIPT-APPLY-DEFER', 0)
        for x in scripts:
            x.send(*call)
        for x in execs:
            x.raw(encode('MULTI')+encode('INCR', k0)+encode('INCR', k1)+encode('EXEC'))
        for i, x in enumerate(writers):
            x.send('INCR', keys[i % 2])
        peak = 0
        if not oracle:
            wait(lambda: stats(c).get('script_waiters_peak', 0) > 64,
                 'never had >64 simultaneous waiters', 2)
            peak = stats(c)['script_waiters_peak']
            now = time.monotonic()
            assert c.must('PING') == b'PONG' and time.monotonic()-now < 1, 'PING stalled'
            assert holder.read() == [1, 2]
        for x in scripts:
            r = x.read()
            assert isinstance(r, list) and len(r) == 2 and all(isinstance(v, int) for v in r), r
        for x in execs:
            assert [x.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
            r = x.read()
            assert isinstance(r, list) and len(r) == 2 and all(isinstance(v, int) for v in r), r
        for x in writers:
            assert isinstance(x.read(), int)
        exact(c, keys, [1+128+32+4, 2+128+32+4])
        escalated = 0
        if not oracle:
            escalated = stats(c)['script_escalations']-before['script_escalations']
            assert escalated > 64, ('fewer than 65 scripts escalated', escalated)
        return dict(scripts=128, execs=32, writers=8, peak=peak, escalated=escalated)
    finally:
        holder.close()
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
    """T7 (T15 reuses it with a disconnect): a writer episode between escalated scripts.
    H (EXEC: MGET k j; SET k 0) holds a started Write claim on k, parked by ATOMIC-FANOUT-DEFER.
    E_old yields to H at its APPLY (H6), escalates and waits behind H. W = MSET k 100 k' 100
    (k' shares k's shard: localfast) is blocked by H and opens an episode that marks k and k'
    with a stamp later than E_old's age. E_young escalates after that stamp. When H commits,
    E_old passes W's mark (age <= stamp), W waits for E_old's claim, and E_young waits for W's
    mark: the serial order H, E_old, W, E_young that the A' rule predicts."""
    k, j = keys
    peer = same_shard(c, k, oracle)
    c.must('MSET', k, 0, j, 0, peer, 0)
    hold = [('MGET', k, j), ('SET', k, 0)]
    with contextlib.ExitStack() as stack:
        h, old, writer, young = [stack.enter_context(contextlib.closing(
            Conn('127.0.0.1', port, timeout=6))) for _ in range(4)]
        if oracle:
            assert transaction(h, hold) == [[b'0', b'0'], b'OK']
            assert old.must(*call) == [1, 1]
            if not disconnect:
                assert writer.must('MSET', k, 100, peer, 100) == b'OK'
                assert young.must(*call) == [101, 2]
        else:
            before = stats(c)
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 1500000)
            h.raw(encode('MULTI')+b''.join(encode(*x) for x in hold)+encode('EXEC'))
            assert [h.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
            wait(lambda: stats(c)['atomic_txn_executed'] > before['atomic_txn_executed'], 'H never started')
            c.must('DEBUG', 'ATOMIC-FANOUT-DEFER', 0)
            base = stats(c)
            old.send(*call)
            wait(lambda: stats(c)['script_escalations'] > base['script_escalations'],
                 'E_old did not escalate at its APPLY conflict with H')
            # The counter moves at the EX hand-off; E_old's age is drawn later, on the IO at its
            # first escalated dispatch (C1). Wait until E_old is placing behind H, so W's stamp is
            # certainly later than E_old's age (and a disconnect hits a dispatched E).
            wait(lambda: stats(c)['atomic_txn_place_waits'] > base['atomic_txn_place_waits'],
                 'E_old never placed behind H')
            if disconnect:
                old.close()
            else:
                writer.send('MSET', k, 100, peer, 100)
                wait(lambda: stats(c)['atomic_txn_writer_marks'] > base['atomic_txn_writer_marks'],
                     'W did not open its episode')
                young.send(*call)
                wait(lambda: stats(c)['script_escalations'] >= base['script_escalations']+2,
                     'E_young did not escalate after the stamp')
            now = time.monotonic()
            assert c.must('PING') == b'PONG' and time.monotonic()-now < 1, 'PING stalled'
            assert h.read() == [[b'0', b'0'], b'OK']
            if not disconnect:
                assert old.read() == [1, 1]
                assert writer.read() == b'OK'
                assert young.read() == [101, 2]
            else:
                wait(lambda: c.must('MGET', k, j) == [b'1', b'1'], 'dispatched disconnected E did not finish')
    values = [1, 1] if disconnect else [101, 2]
    exact(c, keys, values)
    if not disconnect:
        exact(c, [peer], [100])
    return values


def errors(c, port, keys, command, oracle):
    """T14: errors of an ESCALATED script are final and exact.
    WRONGTYPE: E INCRs k1, then INCRs a list: Redis keeps the first write. OOM: E (escalated by a
    DEL of k1 during its READ park; DEL is allowed under maxmemory) reaches APPLY under maxmemory 1.
    Redis appends ". script: <sha>, on @user_script:1." to an EVAL/EVALSHA OOM raised inside the
    script. TomoKV's cross-owner scripts check maxmemory at APPLY admission and omit that suffix on
    PRE as on POST (XS-OOM-1, pre-existing, review section 4.4); the message itself is compared."""
    c.must('SET', keys[0], 0)
    c.must('RPUSH', keys[1], 'list')
    call = invocation(c, command, keys, "redis.call('INCR',KEYS[1]); return redis.call('INCR',KEYS[2])")
    oom_call = invocation(c, command, [keys[0], keys[1]], "return redis.call('SET',KEYS[1],'oom')")
    def text(reply):
        assert isinstance(reply, RespError), reply
        message = str(reply)
        return message.split(' script: ')[0], ' script: ' in message
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
        c.must('SET', keys[0], 'before')
        try:
            if oracle:
                assert c.must('DEL', keys[0]) == 1
                c.must('CONFIG', 'SET', 'maxmemory', 1)
                oom = script.cmd(*oom_call)
            else:
                # The rival DEL lands inside the READ park and BEFORE maxmemory is lowered:
                # with script intents live, PRE and POST answer a DEL under maxmemory with
                # ERR out of memory (XS-OOM-2, pre-existing), which Redis would not.
                before = stats(c)
                script.send(*oom_call)
                wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'], 'OOM conflict window absent')
                assert c.must('DEL', keys[0]) == 1
                c.must('CONFIG', 'SET', 'maxmemory', 1)
                oom = script.read()
                after = stats(c)
                # A function checks maxmemory itself when its SET runs (FunctionMemoryScope::admit
                # on the real owner), i.e. in the optimistic RUN, before any conflict is detected:
                # its OOM is final without escalation. EVAL/EVALSHA write on the workbench and meet
                # maxmemory only at APPLY admission, so they escalate first and the ESCALATED
                # attempt answers OOM.
                expected = 0 if command == 'FCALL' else 1
                assert after['script_escalations'] == before['script_escalations']+expected, (
                    'OOM case escalations', expected, after['script_escalations']-before['script_escalations'])
                assert after['script_escalated_commits'] == before['script_escalated_commits'], 'OOM escalated script committed'
        finally:
            c.must('CONFIG', 'SET', 'maxmemory', 0)
            if not oracle:
                c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
                c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 0)
        message, suffix = text(oom)
        assert message.startswith('OOM '), oom
        assert c.must('EXISTS', keys[0]) == 0, 'OOM script wrote despite the error'
    return dict(wrongtype=str(reply), oom=message, kept=2, oom_script_suffix=suffix)


def drain_messages(sock, quiet=.6, deadline=6):
    """Read pub/sub messages from a raw socket until it stays quiet for `quiet` seconds."""
    data = b''
    end = time.monotonic() + deadline
    sock.settimeout(quiet)
    while time.monotonic() < end:
        try:
            chunk = sock.recv(65536)
        except TimeoutError:
            break
        if not chunk:
            break
        data += chunk
    messages, pos = [], 0
    while pos < len(data):
        assert data.startswith(b'*', pos), data[pos:pos+40]
        eol = data.index(b'\r\n', pos)
        count = int(data[pos+1:eol]); pos = eol + 2
        items = []
        for _ in range(count):
            assert data.startswith(b'$', pos), data[pos:pos+40]
            eol = data.index(b'\r\n', pos)
            size = int(data[pos+1:eol]); pos = eol + 2
            items.append(data[pos:pos+size]); pos += size + 2
        messages.append(items)
    for message in messages:
        assert message[:2] == [b'message', b'__keyevent@0__:incrby'], message
    return messages


def readonly_notifications(c, port, keys, call, command, oracle):
    c.must('CONFIG', 'SET', 'notify-keyspace-events', 'KEA')
    with contextlib.closing(Conn('127.0.0.1', port, timeout=3)) as sub:
        # Redis (and TomoKV) publish INCR as the 'incrby' event.
        assert sub.must('SUBSCRIBE', '__keyevent@0__:incrby')[0] == b'subscribe'
        conflicts(c, port, keys, call, oracle)
        # Drain from the raw socket until it stays quiet: the buffered reader cannot be read again
        # after a timeout, and select() cannot see events it already buffered.
        events = [e[2] for e in drain_messages(sub.sock)]
    rival = events.count(keys[1].encode()) - events.count(keys[0].encode())
    script_events = (events.count(keys[0].encode()), events.count(keys[1].encode()) - 10)
    # Ten rival INCRs on k2 (nine during the READ parks, one behind E); the committed script adds
    # one event per key. Events from the eight cancelled optimistic attempts must never appear.
    assert rival == 10 and len(events) == 10 + sum(script_events), (events, script_events)
    deviation = None
    if oracle:
        assert script_events == (1, 1), events
    else:
        # XS-NOTIFY-1 (pre-existing, identical on PRE): a cross-owner script publishes neither
        # keyspace events nor CLIENT TRACKING invalidations, optimistic or escalated. Tolerated
        # only as all-or-nothing; a partial or duplicated publication fails.
        assert script_events in ((1, 1), (0, 0)), ('partial or cancelled-attempt events', events)
        if script_events == (0, 0):
            deviation = 'XS-NOTIFY-1'
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
        # A '#!lua flags=no-writes' EVAL does not compile on PRE or POST (XS-SHEBANG-1, a
        # pre-existing gap); the read-only body is run as *_RO and as a plain EVAL/EVALSHA.
        source = READ
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
    return dict(events=len(events), script_events=list(script_events), deviation=deviation, readonly=80)


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
                       bgsave=args.case == 'T11b', flip=args.case == 'T10',
                       refusals=[0] if args.pre_control else None)
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
    # PRE controls only: count TRYAGAIN/BUSY script refusals instead of failing on them.
    p.add_argument('--pre-control', action='store_true')
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
                            fields = ('wrongtype', 'oom', 'kept')
                            reference = references[command]
                            assert {f: result['value'][f] for f in fields} == {f: reference[f] for f in fields}, (
                                result['value'], reference)
                            if result['value']['oom_script_suffix'] != reference['oom_script_suffix']:
                                result['deviation'] = 'XS-OOM-1'
                    result['pass'] = True
                except Exception:
                    result.update(pass_=False, error=traceback.format_exc())
                results.append(result)
                print(json.dumps(result), flush=True)
                (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    return any(not r.get('pass') for r in results)


if __name__ == '__main__':
    raise SystemExit(main())
