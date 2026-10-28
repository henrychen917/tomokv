#!/usr/bin/env python3
"""snapfix directed rows: XS-SHUT-1 and SNAP-STORM-1. Errors and unopened windows fail; no rates.

shutdown       SHUTDOWN NOSAVE inside a cross-owner script storm while further activations are
               parked in flight (DEBUG SCRIPT-STAGE-DEFER), with appendonly yes and appendfsync
               always. The server must exit 0 without a forced kill. A restart from the AOF must
               show both keys equal (no partial activation) and at least every acknowledged
               reply: Redis NOSAVE still keeps the AOF, so no acknowledged write may be lost.
bgsave-script  (a) A BGSAVE sent on the IO thread that admitted a parked cross-owner activation
               must return; PRE waits in drain_atomic_groups for a retirement that only its own
               thread can perform. (b) A bounded script + writer storm under a BGSAVE loop:
               no operation may wait past the stall bound, every activation completes, data
               accounting is exact and a storm-time snapshot reloads consistently.
bgsave-loop    Twelve back-to-back BGSAVEs return within the stall bound without growing the
               process (PRE doubled every shard's table per snapshot). Independent of the
               storm rows so their earlier PRE stalls cannot mask this defect.
bgsave-exec    A capture-length dataset, pipelined plain writers of one hot key sharing one IO
               lane into that key's owner, an EXEC (+WATCH) storm on the hot key and a cross-owner
               witness pair, and a BGSAVE loop. A probe from a different IO lane into the same
               owner must never wait past the stall bound (PRE: the owner's unbounded snapshot
               drain never leaves the refilled lane while its capture inflates every write), every
               EXEC completes, accounting is exact and a storm-time snapshot reloads consistently.

Every leg boots its own server on --cores/--port and requires a clean exit. The Redis 7.4 oracle
runs the same cases on --port+1 (DEBUG hooks and IO placement are TomoKV-only witnesses).
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
import traceback

from _lib import Conn, RespError, encode, wait_ready

WRITE = "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}"
# This base answers an over-full cross-owner script window or an exhausted conflict retry with a
# refusal instead of queueing. Neither writes anything, so a refusal is counted, never a stall.
REFUSALS = ('BUSY Cross-shard', 'TRYAGAIN Cross-shard')


class Stall(AssertionError):
    pass


def stats(c, section='stats'):
    out = {}
    for line in c.must('INFO', section).decode(errors='replace').splitlines():
        key, _, value = line.partition(':')
        if value.lstrip('-').isdigit():
            out[key] = int(value)
    return out


def persistence(c):
    return dict(line.split(':', 1) for line in c.must('INFO', 'persistence').decode().splitlines()
                if ':' in line)


def wait(predicate, message, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError(message)


class Boot:
    """One owned server lifetime. stop() requires a clean exit without a forced kill."""

    def __init__(self, args, directory, mode, engine, atomic, oracle, extra=(), name='server'):
        self.oracle = oracle
        self.port = args.port + int(oracle)
        self.directory = directory
        binary = Path(args.oracle if oracle else args.binary).resolve()
        flags = ['--bind', '127.0.0.1', '--port', str(self.port), '--dir', str(directory.resolve()),
                 '--save', '', '--enable-debug-command', 'yes', *extra]
        if not oracle:
            flags += ['--shards', '16', '--thread-mode', mode, '--net-io', engine,
                      '--atomic', str(atomic), '--read-local',
                      str(getattr(args, 'read_local', int(mode == '1s'))),
                      '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0',
                      '--databases', str(getattr(args, 'databases', 16))]
            if mode == '2s':
                flags += ['--ratio', '6:2']
        self.argv = ['taskset', '-c', args.cores, str(binary), *flags]
        directory.mkdir(parents=True, exist_ok=True)
        self.log = directory / f'{name}.log'
        (directory / f'{name}.argv.json').write_text(json.dumps(self.argv) + '\n')
        self.name = name
        with self.log.open('w') as log:
            self.proc = subprocess.Popen(self.argv, stdout=log, stderr=subprocess.STDOUT)
        try:
            self.c = wait_ready('127.0.0.1', self.port, process=self.proc, timeout=60)
        except Exception:
            self.kill()
            raise
        self.c.sock.settimeout(args.stall)
        self.exit = None

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()

    def wait_exit(self, timeout):
        forced = False
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            forced = True
            self.kill()
        self.exit = dict(rc=self.proc.returncode, forced=forced)
        (self.directory / f'{self.name}.exit.json').write_text(json.dumps(self.exit) + '\n')
        return self.exit

    def stop(self):
        if self.c:
            with contextlib.suppress(Exception):
                self.c.close()
            self.c = None
        if self.exit is None:
            if self.proc.poll() is None:
                self.proc.terminate()
            self.wait_exit(10)
        assert self.exit == dict(rc=0, forced=False), ('server did not exit cleanly', self.name, self.exit)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        try:
            self.stop()
        except AssertionError:
            if kind is None:
                raise


def placement(c, key):
    shard, owner = c.must('DEBUG', 'SHARDS', key)[0][:2]
    return int(shard), int(owner)


def keys_for(c, prefix, oracle, count=3, distinct=True):
    """`count` keys on pairwise different owners (or plain names on the oracle)."""
    if oracle:
        return [f'{prefix}:{i}' for i in range(count)], None
    chosen, owners = [], []
    for i in range(4000):
        key = f'{prefix}:{i}'
        where = placement(c, key)
        if not distinct or all(where[1] != o[1] for o in owners):
            chosen.append(key)
            owners.append(where)
            if len(chosen) == count:
                return chosen, owners
    raise AssertionError('not enough distinct owners')


def io_thread(conn):
    return int(conn.must('DEBUG', 'IO-THREAD'))


def connect(port, stall, io=None, avoid=(), oracle=False, tries=96):
    """A connection, on IO thread `io` when given, else on one outside `avoid`."""
    spare = []
    try:
        for _ in range(tries):
            conn = Conn('127.0.0.1', port, timeout=stall)
            if oracle:
                return conn
            where = io_thread(conn)
            if (io is not None and where == io) or (io is None and where not in avoid):
                return conn
            spare.append(conn)
        raise AssertionError(f'no connection reached IO thread {io} / outside {sorted(avoid)}')
    finally:
        for conn in spare:
            conn.close()


def integers(reply):
    return [int(v) for v in reply]


class Latency:
    """Largest observed single-operation wait per worker class (evidence of the stall margin)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.max = {}

    def observe(self, kind, began):
        waited = time.monotonic() - began
        with self.lock:
            if waited > self.max.get(kind, 0.0):
                self.max[kind] = waited

    def report(self):
        return {k: round(v, 3) for k, v in sorted(self.max.items())}


def run_storm(seconds, workers, stall):
    """Run worker callables until `seconds` elapse or one fails; a socket timeout is a stall."""
    stop = threading.Event()
    errors = []

    def wrap(fn):
        try:
            fn(stop)
        except (TimeoutError, socket.timeout) as e:
            errors.append(f'STALL > {stall}s: {fn.__name__}: {e!r}')
            stop.set()
        except Exception as e:  # noqa: BLE001
            errors.append(f'{fn.__name__}: {traceback.format_exc()}')
            stop.set()

    threads = [threading.Thread(target=wrap, args=(fn,), daemon=True) for fn in workers]
    for t in threads:
        t.start()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stop.is_set():
        time.sleep(.05)
    stop.set()
    for t in threads:
        t.join(timeout=stall + 5)
    if any(t.is_alive() for t in threads):
        errors.append('a storm worker never returned')
    return errors


# ---------------------------------------------------------------------------------------------
# shutdown (XS-SHUT-1)
# ---------------------------------------------------------------------------------------------

def case_shutdown(args, directory, mode, engine, atomic, oracle):
    aof = ['--appendonly', 'yes', '--appendfsync', 'always']
    first = Boot(args, directory, mode, engine, atomic, oracle, aof, 'server')
    acked = [[0, 0]]
    sent = [0]
    refused = [0]
    lock = threading.Lock()
    try:
        c = first.c
        keys, owners = keys_for(c, 'snapfix:shut', oracle, 2)
        c.must('MSET', keys[0], 0, keys[1], 0)
        stop = threading.Event()
        storm_conns = [Conn('127.0.0.1', first.port, timeout=args.stall) for _ in range(6)]

        def storm(conn):
            try:
                while not stop.is_set():
                    with lock:
                        sent[0] += 1
                    reply = conn.cmd('EVAL', WRITE, 2, *keys)
                    if isinstance(reply, RespError) and str(reply).startswith(REFUSALS):
                        with lock:
                            refused[0] += 1
                        continue
                    assert isinstance(reply, list) and len(reply) == 2, reply
                    with lock:
                        acked.append(integers(reply))
            except (EOFError, ConnectionError, OSError):
                pass  # SHUTDOWN closed the connection; anything unanswered was never acknowledged

        threads = [threading.Thread(target=storm, args=(x,), daemon=True) for x in storm_conns]
        for t in threads:
            t.start()
        wait(lambda: len(acked) > 20, 'script storm never acknowledged a write')
        parked = []
        if not oracle:
            before = stats(c)
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 3000000)
            parked = [Conn('127.0.0.1', first.port, timeout=args.stall) for _ in range(8)]
            for x in parked:
                with lock:
                    sent[0] += 1
                x.send('EVAL', WRITE, 2, *keys)
            # Vacuity guard: SHUTDOWN must meet activations that have already pinned their keys.
            wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'] and
                 stats(c)['script_keys_armed'] > stats(c)['script_keys_released'],
                 'no cross-owner activation was parked in flight before SHUTDOWN')
        c.send('SHUTDOWN', 'NOSAVE')
        try:
            reply = c.read()
        except (EOFError, ConnectionError, OSError):
            reply = None
        assert reply is None or reply == b'OK', reply
        exit_status = first.wait_exit(30)
        stop.set()
        for t in threads:
            t.join(timeout=args.stall + 5)
        for x in storm_conns + parked:
            x.close()
        assert exit_status == dict(rc=0, forced=False), ('SHUTDOWN NOSAVE exit', exit_status)
    finally:
        with contextlib.suppress(Exception):
            first.stop()
    top = [max(v[0] for v in acked), max(v[1] for v in acked)]
    with Boot(args, directory, mode, engine, atomic, oracle, aof, 'restart') as again:
        values = integers(again.c.must('MGET', *keys))
        assert values[0] == values[1], ('partial activation survived the restart', values)
        assert values[0] >= top[0] and values[1] >= top[1], ('acknowledged write lost', values, top)
        assert values[0] <= sent[0], ('more activations than were sent', values, sent[0])
    return dict(restored=values, acknowledged_max=top, sent=sent[0], refused=refused[0],
                acknowledged=len(acked) - 1)


# ---------------------------------------------------------------------------------------------
# bgsave-script (SNAP-STORM-1, script activations)
# ---------------------------------------------------------------------------------------------

def bgsave_done(c, timeout=60):
    wait(lambda: persistence(c).get('rdb_bgsave_in_progress') == '0', 'BGSAVE did not finish', timeout)
    assert persistence(c).get('rdb_last_bgsave_status') == 'ok', persistence(c)


def bgsave_loop(c, saves, stall):
    def loop(stop):
        while not stop.is_set():
            reply = c.cmd('BGSAVE')
            assert reply == b'Background saving started' or (
                isinstance(reply, RespError) and 'already in progress' in str(reply)), reply
            saves[0] += reply == b'Background saving started'
            time.sleep(.1)
    loop.__name__ = 'bgsave-loop'
    return loop


def storm_snapshot_check(args, directory, mode, engine, atomic, oracle, booted, witness, final, label):
    """The storm left its last BGSAVE on disk: shut down without saving, boot from that file, and
    require the witness pair equal (a consistent cut) and no value beyond the final live one."""
    bgsave_done(booted.c)
    booted.c.send('SHUTDOWN', 'NOSAVE')
    with contextlib.suppress(EOFError, ConnectionError, OSError):
        booted.c.read()
    assert booted.wait_exit(30) == dict(rc=0, forced=False), ('storm server exit', booted.exit)
    with Boot(args, directory, mode, engine, atomic, oracle, (), f'{label}-reload') as again:
        loaded = [int(v or 0) for v in again.c.must('MGET', *witness)]
        assert loaded[0] == loaded[1], ('storm-time snapshot is not a consistent cut', loaded)
        assert 0 < loaded[0] <= final, ('storm-time snapshot outside the storm', loaded, final)
    return loaded


def case_bgsave_script(args, directory, mode, engine, atomic, oracle):
    result = {}
    with Boot(args, directory / 'parked', mode, engine, atomic, oracle, (), 'parked') as b:
        c = b.c
        keys, owners = keys_for(c, 'snapfix:snap', oracle, 2)
        c.must('MSET', keys[0], 0, keys[1], 0)
        own_io = None if oracle else io_thread(c)
        script = connect(b.port, args.stall, io=own_io, oracle=oracle)
        try:
            if not oracle:
                before = stats(c)
                c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 400000)
            script.send('EVAL', WRITE, 2, *keys)
            if not oracle:
                wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'],
                     'parked activation never opened its stage window')
                assert stats(c)['atomic_inflight'] >= 1, 'activation is not in flight at BGSAVE'
            began = time.monotonic()
            try:
                reply = c.cmd('BGSAVE')
            except (TimeoutError, socket.timeout) as e:
                raise Stall(f'BGSAVE on the activation IO thread did not return in {args.stall}s') from e
            result['bgsave_seconds'] = round(time.monotonic() - began, 3)
            assert reply == b'Background saving started', reply
            assert integers(script.read()) == [1, 1]
            if not oracle:
                c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
            bgsave_done(c)
        finally:
            script.close()
        assert integers(c.must('MGET', *keys)) == [1, 1]
    # (b) bounded storm: eight script clients on the witness pair, four writers on keys of the
    # same owners, the BGSAVE loop on its own connection.
    b = Boot(args, directory / 'storm', mode, engine, atomic, oracle, (), 'storm')
    try:
        c = b.c
        keys, owners = keys_for(c, 'snapfix:sstorm', oracle, 2)
        writer_keys = [f'{keys[0]}:w', f'{keys[1]}:w'] if oracle else [
            same_owner(c, f'snapfix:sw{i}', owners[i][1]) for i in range(2)]
        c.must('MSET', keys[0], 0, keys[1], 0, writer_keys[0], 0, writer_keys[1], 0)
        done = [0] * 8
        refused = [0]
        writes = [0, 0]
        saves = [0]
        latency = Latency()

        def scripter(i):
            def run(stop):
                with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as x:
                    while not stop.is_set():
                        began = time.monotonic()
                        reply = x.cmd('EVAL', WRITE, 2, *keys)
                        latency.observe('script', began)
                        if isinstance(reply, RespError) and str(reply).startswith(REFUSALS):
                            refused[0] += 1
                            continue
                        assert isinstance(reply, list) and len(reply) == 2, reply
                        done[i] += 1
            run.__name__ = f'script-{i}'
            return run

        def writer(i):
            def run(stop):
                with contextlib.closing(Conn('127.0.0.1', b.port, timeout=args.stall)) as x:
                    while not stop.is_set():
                        began = time.monotonic()
                        x.must('INCR', writer_keys[i % 2])
                        latency.observe('writer', began)
                        writes[i % 2] += 1
            run.__name__ = f'writer-{i}'
            return run

        saver = Conn('127.0.0.1', b.port, timeout=args.stall)
        errors = run_storm(args.seconds, [scripter(i) for i in range(8)] +
                           [writer(i) for i in range(4)] + [bgsave_loop(saver, saves, args.stall)],
                           args.stall)
        saver.close()
        assert not errors, errors
        assert saves[0] > 0 and sum(done) > 0, (saves, done)
        final = integers(c.must('MGET', *keys, *writer_keys))
        assert final[:2] == [sum(done), sum(done)] and final[2:] == writes, (final, done, writes)
        if not oracle:
            s = stats(c)
            assert s.get('atomic_txn_order_violations', 0) == 0, s
            assert s['script_keys_armed'] == s['script_keys_released'], 'script PINs leaked'
        result['storm'] = dict(activations=sum(done), refused=refused[0], writes=writes, saves=saves[0],
                               max_latency=latency.report())
        result['snapshot'] = storm_snapshot_check(args, directory / 'storm', mode, engine, atomic,
                                                  oracle, b, keys, final[0], 'storm')
    finally:
        with contextlib.suppress(Exception):
            b.stop()
    return result


def bgsave_loop_bounded(args, directory, mode, engine, atomic, oracle, saves=None):
    """(c) Back-to-back BGSAVEs must not grow the process. PRE sized every snapshot's fresh table as
    twice the CURRENT capacity and never shrank it after the merge, so each BGSAVE doubled every
    shard's table: RSS doubled per save and each Preparing first had to finish merging the
    previous doubled table while the armed atomic barrier held every new unit."""
    saves = getattr(args, 'saves', 12) if saves is None else saves
    assert saves >= 3, 'RSS comparison requires at least three completed saves'
    with Boot(args, directory, mode, engine, atomic, oracle, (), 'loop') as b:
        c = b.c
        c.must('SET', 'snapfix:loop', 1)
        completed_before = int(persistence(c)['rdb_saves'])
        rss, seconds, start_seconds = [], [], []
        for save in range(saves):
            began = time.monotonic()
            try:
                reply = c.cmd('BGSAVE')
            except (TimeoutError, socket.timeout) as e:
                raise Stall(f'BGSAVE did not return in {args.stall}s') from e
            assert reply == b'Background saving started', reply
            start_seconds.append(round(time.monotonic() - began, 6))
            bgsave_done(c, args.stall)
            completed = int(persistence(c)['rdb_saves']) - completed_before
            assert completed == save + 1, ('BGSAVE never completed its cut', save + 1, completed)
            seconds.append(round(time.monotonic() - began, 3))
            rss.append(stats(c, 'memory')['used_memory_rss'])
        result = dict(rss=rss, seconds=seconds, start_seconds=start_seconds, completed_saves=completed)
        # Keep the complete curves even when the growth assertion rejects PRE.
        (directory / 'rss.json').write_text(json.dumps(result, indent=2) + '\n')
        # PRE: about 21 MB after the second save and about 1 GB after the twelfth.
        assert max(rss[2:]) <= 3 * rss[1] + (64 << 20), ('BGSAVE loop grew the process', rss)
        return result


def same_owner(c, prefix, owner, shard=None):
    for i in range(4000):
        key = f'{prefix}:{i}'
        where = placement(c, key)
        if where[1] == owner and (shard is None or where[0] != shard):
            return key
    raise AssertionError(f'no key on owner {owner}')


# ---------------------------------------------------------------------------------------------
# bgsave-exec (SNAP-STORM-1, EXEC + plain writers)
# ---------------------------------------------------------------------------------------------

def populate(c, count, batch=500):
    for start in range(0, count, batch):
        args = []
        for i in range(start, min(count, start + batch)):
            args += [f'snapfix:fill:{i}', 'v' * 16]
        c.must('MSET', *args)


def case_bgsave_exec(args, directory, mode, engine, atomic, oracle):
    b = Boot(args, directory, mode, engine, atomic, oracle, (), 'server')
    result = {}
    try:
        c = b.c
        populate(c, args.dataset)
        if oracle:
            hot, pair = 'snapfix:hot', ['snapfix:pair:0', 'snapfix:pair:1']
            probe_key, writer_io, probe_io = 'snapfix:probe', None, None
        else:
            hot_shard, owner = placement(c, 'snapfix:hot')
            hot = 'snapfix:hot'
            pair, pair_where = keys_for(c, 'snapfix:pair', False, 2)
            probe_key = same_owner(c, 'snapfix:probe', owner)
            writer_io = next(t for t in range(8) if t != owner and (mode == '1s' or t < 6))
        c.must('MSET', hot, 0, pair[0], 0, pair[1], 0, probe_key, 'p')
        writer_conns = [connect(b.port, args.stall, io=writer_io, oracle=oracle) for _ in range(args.writers)]
        avoid = set() if oracle else {writer_io, owner}
        probe = connect(b.port, args.stall, avoid=avoid, oracle=oracle)
        lanes = None if oracle else dict(owner=owner, writer_io=writer_io, probe_io=io_thread(probe))
        exec_conns = [Conn('127.0.0.1', b.port, timeout=args.stall) for _ in range(6)]
        saver = Conn('127.0.0.1', b.port, timeout=args.stall)
        incr = [0] * len(writer_conns)
        committed = [0] * len(exec_conns)
        aborted = [0]
        probe_max = [0.0]
        saves = [0]
        latency = Latency()
        burst = encode('INCR', hot) * args.burst

        def writer(i):
            def run(stop):
                x = writer_conns[i]
                while not stop.is_set():
                    began = time.monotonic()
                    x.raw(burst)
                    for _ in range(args.burst):
                        assert isinstance(x.read(), int)
                    latency.observe('writer-burst', began)
                    incr[i] += args.burst
            run.__name__ = f'writer-{i}'
            return run

        def execer(i):
            def run(stop):
                x = exec_conns[i]
                while not stop.is_set():
                    began = time.monotonic()
                    if i % 2:
                        x.must('WATCH', *pair)
                    x.raw(encode('MULTI') + encode('INCR', hot) + encode('INCR', pair[0]) +
                          encode('INCR', pair[1]) + encode('EXEC'))
                    head = [x.read() for _ in range(4)]
                    assert head == [b'OK', b'QUEUED', b'QUEUED', b'QUEUED'], head
                    reply = x.read()
                    latency.observe('exec', began)
                    if reply is None and i % 2:
                        aborted[0] += 1
                        continue
                    assert isinstance(reply, list) and len(reply) == 3, reply
                    committed[i] += 1
            run.__name__ = f'exec-{i}'
            return run

        def prober(stop):
            while not stop.is_set():
                began = time.monotonic()
                assert probe.must('GET', probe_key) == b'p'
                probe_max[0] = max(probe_max[0], time.monotonic() - began)
                time.sleep(.02)

        before = None if oracle else stats(c, 'persistence')
        errors = run_storm(args.seconds, [writer(i) for i in range(len(writer_conns))] +
                           [execer(i) for i in range(len(exec_conns))] + [prober] +
                           [bgsave_loop(saver, saves, args.stall)], args.stall)
        result.update(probe_max=round(probe_max[0], 3), saves=saves[0], writes=sum(incr),
                      execs=sum(committed), aborted=aborted[0], lanes=lanes,
                      max_latency=latency.report())
        for x in writer_conns + exec_conns + [probe, saver]:
            x.close()
        assert not errors, (errors, result)
        assert saves[0] > 0 and sum(committed) > 0 and sum(incr) > 0, result
        final = integers(c.must('MGET', hot, *pair))
        assert final == [sum(incr) + sum(committed), sum(committed), sum(committed)], (final, result)
        if not oracle:
            s = stats(c)
            assert s.get('atomic_txn_order_violations', 0) == 0, s
            p = stats(c, 'persistence')
            assert p['snapshot_cuts_armed'] > before['snapshot_cuts_armed'], 'no snapshot cut armed'
        result['snapshot'] = storm_snapshot_check(args, directory, mode, engine, atomic, oracle, b,
                                                  pair, final[1], 'exec')
    finally:
        with contextlib.suppress(Exception):
            b.stop()
    return result


CASES = {'shutdown': case_shutdown, 'bgsave-script': case_bgsave_script,
         'bgsave-loop': bgsave_loop_bounded,
         'bgsave-exec': case_bgsave_exec}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case', choices=sorted(CASES), required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--modes', nargs='+', default=['1s', '2s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--no-oracle', action='store_true')
    p.add_argument('--seconds', type=float, default=6)
    p.add_argument('--saves', type=int, default=12, help='completed saves in bgsave-loop only')
    p.add_argument('--stall', type=float, default=5)
    p.add_argument('--dataset', type=int, default=30000)
    p.add_argument('--writers', type=int, default=4)
    p.add_argument('--burst', type=int, default=64)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    legs = ([] if args.no_oracle else [('redis', 'redis', 0, True)]) + [
        (m, e, a, False) for m in args.modes for e in args.engines for a in args.atomics]
    for mode, engine, atomic, oracle in legs:
        label = f'{mode}-{engine}-{atomic}'
        row = dict(case=args.case, leg=label)
        began = time.monotonic()
        try:
            row['value'] = CASES[args.case](args, args.output / label, mode, engine, atomic, oracle)
            row['pass'] = True
        except Exception:
            row.update(pass_=False, error=traceback.format_exc())
        row['seconds'] = round(time.monotonic() - began, 3)
        results.append(row)
        print(json.dumps(row), flush=True)
        (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(not r.get('pass') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
