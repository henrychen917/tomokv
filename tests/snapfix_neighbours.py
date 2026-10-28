#!/usr/bin/env python3
"""snapfix neighbour checks (non-gate): the paths next to the XS-SHUT-1 and SNAP-STORM-1 fixes.

shutdown-save  SHUTDOWN SAVE with parked cross-owner activations inside a script storm (no AOF):
               exit 0, and the saved file restores both keys equal and >= every acknowledgement.
sigterm        SIGTERM in the same storm with appendonly yes / appendfsync always: exit 0, AOF
               restart equal and >= every acknowledgement.
flushall       Script + EXEC + writer storm with a BGSAVE loop and a FLUSHALL every 300 ms: no stall,
               every MGET of each atomic pair is equal, both pairs equal at the end, snapshot reloads.
bgsave-flip    2s only: script + writer storm (MULTI connections never transfer) with a BGSAVE loop
               and a FLIP 6:2 <-> 4:4 every second: no stall, at least one FLIP completes, exact
               accounting, storm-time snapshot reloads as a consistent cut.
aofrw-exec     appendonly yes, the bgsave-exec storm shape with a BGREWRITEAOF loop instead of BGSAVE:
               no stall, exact accounting, DEBUG LOADAOF and a restart reproduce the live data.
aofrw-script   the same with the cross-owner script + writer storm.

Reuses tests/snapfix.py boots (clean exit required). Never part of the gate ledger.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import threading
import time
import traceback

import snapfix as s
from _lib import Conn, RespError, encode


def parked_storm(args, booted, keys, oracle):
    """Script storm plus eight DEFER-parked activations; returns (stop, threads, conns, acked, sent)."""
    acked, sent, lock = [[0, 0]], [0], threading.Lock()
    stop = threading.Event()
    conns = [Conn('127.0.0.1', booted.port, timeout=args.stall) for _ in range(6)]

    def storm(conn):
        try:
            while not stop.is_set():
                with lock:
                    sent[0] += 1
                reply = conn.cmd('EVAL', s.WRITE, 2, *keys)
                if isinstance(reply, RespError) and str(reply).startswith(s.REFUSALS):
                    continue
                assert isinstance(reply, list) and len(reply) == 2, reply
                with lock:
                    acked.append(s.integers(reply))
        except (EOFError, ConnectionError, OSError):
            pass

    threads = [threading.Thread(target=storm, args=(x,), daemon=True) for x in conns]
    for t in threads:
        t.start()
    s.wait(lambda: len(acked) > 20, 'script storm never acknowledged a write')
    if not oracle:
        c = booted.c
        before = s.stats(c)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 1500000)
        for _ in range(8):
            x = Conn('127.0.0.1', booted.port, timeout=args.stall)
            conns.append(x)
            with lock:
                sent[0] += 1
            x.send('EVAL', s.WRITE, 2, *keys)
        s.wait(lambda: s.stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'] and
               s.stats(c)['script_keys_armed'] > s.stats(c)['script_keys_released'],
               'no activation parked in flight')
    return stop, threads, conns, acked, sent


def finish_parked(args, stop, threads, conns):
    stop.set()
    for t in threads:
        t.join(timeout=args.stall + 5)
    for x in conns:
        x.close()


def case_shutdown_save(args, directory, mode, engine, atomic, oracle):
    booted = s.Boot(args, directory, mode, engine, atomic, oracle, (), 'server')
    try:
        keys, _ = s.keys_for(booted.c, 'snapfix:nsave', oracle, 2)
        booted.c.must('MSET', keys[0], 0, keys[1], 0)
        stop, threads, conns, acked, sent = parked_storm(args, booted, keys, oracle)
        booted.c.sock.settimeout(30)
        booted.c.send('SHUTDOWN', 'SAVE')
        try:
            reply = booted.c.read()
        except (EOFError, ConnectionError, OSError):
            reply = None
        assert reply is None or reply == b'OK', reply
        status = booted.wait_exit(40)
        finish_parked(args, stop, threads, conns)
        assert status == dict(rc=0, forced=False), ('SHUTDOWN SAVE exit', status)
    finally:
        with contextlib.suppress(Exception):
            booted.stop()
    top = [max(v[0] for v in acked), max(v[1] for v in acked)]
    with s.Boot(args, directory, mode, engine, atomic, oracle, (), 'restart') as again:
        values = s.integers(again.c.must('MGET', *keys))
        assert values[0] == values[1] and values[0] >= top[0], ('SHUTDOWN SAVE restore', values, top)
    return dict(restored=values, acknowledged_max=top, sent=sent[0])


def case_sigterm(args, directory, mode, engine, atomic, oracle):
    aof = ['--appendonly', 'yes', '--appendfsync', 'always']
    booted = s.Boot(args, directory, mode, engine, atomic, oracle, aof, 'server')
    try:
        keys, _ = s.keys_for(booted.c, 'snapfix:term', oracle, 2)
        booted.c.must('MSET', keys[0], 0, keys[1], 0)
        stop, threads, conns, acked, sent = parked_storm(args, booted, keys, oracle)
        booted.proc.send_signal(signal.SIGTERM)
        status = booted.wait_exit(30)
        finish_parked(args, stop, threads, conns)
        assert status == dict(rc=0, forced=False), ('SIGTERM exit', status)
    finally:
        with contextlib.suppress(Exception):
            booted.stop()
    top = [max(v[0] for v in acked), max(v[1] for v in acked)]
    with s.Boot(args, directory, mode, engine, atomic, oracle, aof, 'restart') as again:
        values = s.integers(again.c.must('MGET', *keys))
        assert values[0] == values[1] and values[0] >= top[0], ('SIGTERM AOF restore', values, top)
    return dict(restored=values, acknowledged_max=top, sent=sent[0])


def script_worker(port, stall, keys, tally, i):
    def run(stop):
        with contextlib.closing(Conn('127.0.0.1', port, timeout=stall)) as x:
            while not stop.is_set():
                reply = x.cmd('EVAL', s.WRITE, 2, *keys)
                if isinstance(reply, RespError) and str(reply).startswith(s.REFUSALS):
                    continue
                assert isinstance(reply, list) and len(reply) == 2, reply
                tally[i] += 1
    run.__name__ = f'script-{i}'
    return run


def exec_worker(port, stall, keys, tally, i):
    def run(stop):
        with contextlib.closing(Conn('127.0.0.1', port, timeout=stall)) as x:
            while not stop.is_set():
                x.raw(encode('MULTI') + encode('INCR', keys[0]) + encode('INCR', keys[1]) + encode('EXEC'))
                assert [x.read() for _ in range(3)] == [b'OK', b'QUEUED', b'QUEUED']
                reply = x.read()
                assert isinstance(reply, list) and len(reply) == 2, reply
                tally[i] += 1
    run.__name__ = f'exec-{i}'
    return run


def writer_worker(port, stall, key, tally, i):
    def run(stop):
        with contextlib.closing(Conn('127.0.0.1', port, timeout=stall)) as x:
            while not stop.is_set():
                x.must('INCR', key)
                tally[i] += 1
    run.__name__ = f'writer-{i}'
    return run


def case_flushall(args, directory, mode, engine, atomic, oracle):
    booted = s.Boot(args, directory, mode, engine, atomic, oracle, (), 'server')
    try:
        c = booted.c
        spair, _ = s.keys_for(c, 'snapfix:fs', oracle, 2)
        epair, _ = s.keys_for(c, 'snapfix:fe', oracle, 2)
        tally = [0] * 20
        saves, flushes, torn = [0], [0], []
        observer = Conn('127.0.0.1', booted.port, timeout=args.stall)
        flusher = Conn('127.0.0.1', booted.port, timeout=args.stall)
        saver = Conn('127.0.0.1', booted.port, timeout=args.stall)

        def observe(stop):
            while not stop.is_set():
                for pair in (spair, epair):
                    a, b = observer.must('MGET', *pair)
                    if (a or b'0') != (b or b'0'):
                        torn.append((pair, a, b))
                time.sleep(.005)
        observe.__name__ = 'observer'

        def flush(stop):
            while not stop.is_set():
                assert flusher.must('FLUSHALL') == b'OK'
                flushes[0] += 1
                time.sleep(.3)
        flush.__name__ = 'flushall'
        workers = ([script_worker(booted.port, args.stall, spair, tally, i) for i in range(6)] +
                   [exec_worker(booted.port, args.stall, epair, tally, 6 + i) for i in range(4)] +
                   [writer_worker(booted.port, args.stall, f'{spair[i % 2]}:w', tally, 10 + i) for i in range(4)] +
                   [observe, flush, s.bgsave_loop(saver, saves, args.stall)])
        errors = s.run_storm(args.seconds, workers, args.stall)
        for x in (observer, flusher, saver):
            x.close()
        assert not errors, errors
        assert not torn, ('torn atomic pair observed', torn[:5])
        assert flushes[0] > 3 and saves[0] > 0, (flushes, saves)
        final = [int(v or 0) for v in c.must('MGET', *spair, *epair)]
        assert final[0] == final[1] and final[2] == final[3], ('pairs diverged', final)
        s.bgsave_done(c)
        if not oracle:
            st = s.stats(c)
            assert st.get('atomic_txn_order_violations', 0) == 0, st
    finally:
        with contextlib.suppress(Exception):
            booted.stop()
    return dict(flushes=flushes[0], saves=saves[0], final=final, scripts=sum(tally[:6]),
                execs=sum(tally[6:10]), writes=sum(tally[10:14]))


def case_bgsave_flip(args, directory, mode, engine, atomic, oracle):
    if mode != '2s' and not oracle:
        return dict(skipped='FLIP is a 2s placement transition')
    booted = s.Boot(args, directory, mode, engine, atomic, oracle, (), 'server')
    result = {}
    try:
        c = booted.c
        keys, owners = s.keys_for(c, 'snapfix:flip', oracle, 2)
        wkeys = [f'{keys[0]}:w', f'{keys[1]}:w']
        c.must('MSET', keys[0], 0, keys[1], 0, wkeys[0], 0, wkeys[1], 0)
        tally = [0] * 12
        saves, flips, refusals = [0], [0], []
        hold = threading.Event()
        saver = Conn('127.0.0.1', booted.port, timeout=args.stall)
        flipper = Conn('127.0.0.1', booted.port, timeout=15)

        def holding(fn):
            def run(stop):
                inner_stop = stop
                with contextlib.closing(Conn('127.0.0.1', booted.port, timeout=15)) as x:
                    while not inner_stop.is_set():
                        while hold.is_set() and not inner_stop.is_set():
                            time.sleep(.001)
                        fn(x)
            run.__name__ = fn.__name__
            return run

        def mk_script(i):
            def script(x):
                reply = x.cmd('EVAL', s.WRITE, 2, *keys)
                if isinstance(reply, RespError) and str(reply).startswith(s.REFUSALS):
                    return
                assert isinstance(reply, list) and len(reply) == 2, reply
                tally[i] += 1
            script.__name__ = f'script-{i}'
            return script

        def mk_writer(i):
            def writer(x):
                x.must('INCR', wkeys[i % 2])
                tally[8 + i] += 1
            writer.__name__ = f'writer-{i}'
            return writer

        def flip(stop):
            target = 4
            while not stop.is_set():
                time.sleep(1)
                if oracle:
                    flips[0] += 1
                    continue
                hold.set()
                try:
                    reply = flipper.cmd('FLIP', target, 8 - target)
                finally:
                    hold.clear()
                if reply == b'OK':
                    flips[0] += 1
                    target = 6 if target == 4 else 4
                else:
                    assert isinstance(reply, RespError), reply
                    refusals.append(str(reply))
        flip.__name__ = 'flipper'
        workers = ([holding(mk_script(i)) for i in range(8)] + [holding(mk_writer(i)) for i in range(4)] +
                   [flip, s.bgsave_loop(saver, saves, args.stall)])
        errors = s.run_storm(max(args.seconds, 5), workers, 16)
        saver.close()
        flipper.close()
        assert not errors, errors
        assert flips[0] > 0, ('no FLIP completed', refusals)
        final = s.integers(c.must('MGET', *keys, *wkeys))
        assert final[0] == final[1] == sum(tally[:8]) and final[2:] == [
            sum(tally[8::2]), sum(tally[9::2])], (final, tally)
        result.update(flips=flips[0], refusals=refusals, saves=saves[0], scripts=sum(tally[:8]),
                      writes=sum(tally[8:]))
        result['snapshot'] = s.storm_snapshot_check(args, directory, mode, engine, atomic, oracle,
                                                    booted, keys, final[0], 'flip')
    finally:
        with contextlib.suppress(Exception):
            booted.stop()
    return result


def rewrite_loop(conn, rewrites):
    def loop(stop):
        while not stop.is_set():
            reply = conn.cmd('BGREWRITEAOF')
            assert isinstance(reply, bytes) or (isinstance(reply, RespError) and (
                'already in progress' in str(reply) or 'scheduled' in str(reply))), reply
            rewrites[0] += isinstance(reply, bytes)
            time.sleep(.2)
    loop.__name__ = 'bgrewriteaof-loop'
    return loop


def rewrite_done(c, timeout=60):
    s.wait(lambda: s.persistence(c).get('aof_rewrite_in_progress') == '0' and
           s.persistence(c).get('aof_rewrite_scheduled', '0') == '0', 'AOF rewrite did not finish', timeout)
    assert s.persistence(c).get('aof_last_bgrewrite_status') == 'ok', s.persistence(c)


def case_aofrw(args, directory, mode, engine, atomic, oracle, shape):
    aof = ['--appendonly', 'yes', '--appendfsync', 'everysec']
    booted = s.Boot(args, directory, mode, engine, atomic, oracle, aof, 'server')
    try:
        c = booted.c
        pair, _ = s.keys_for(c, f'snapfix:rw{shape}', oracle, 2)
        hot = f'{pair[0]}:hot'
        c.must('MSET', pair[0], 0, pair[1], 0, hot, 0)
        tally = [0] * 16
        rewrites = [0]
        admin = Conn('127.0.0.1', booted.port, timeout=args.stall)
        if shape == 'exec':
            workers = [exec_worker(booted.port, args.stall, pair, tally, i) for i in range(6)]
        else:
            workers = [script_worker(booted.port, args.stall, pair, tally, i) for i in range(6)]
        workers += [writer_worker(booted.port, args.stall, hot, tally, 8 + i) for i in range(4)]
        errors = s.run_storm(args.seconds, workers + [rewrite_loop(admin, rewrites)], args.stall)
        admin.close()
        assert not errors, errors
        assert rewrites[0] > 0, 'no AOF rewrite started'
        units, writes = sum(tally[:8]), sum(tally[8:])
        live = s.integers(c.must('MGET', *pair, hot))
        assert live == [units, units, writes], (live, units, writes)
        rewrite_done(c)
        assert c.must('DEBUG', 'LOADAOF') == b'OK'
        assert s.integers(c.must('MGET', *pair, hot)) == live, 'DEBUG LOADAOF changed the data'
    finally:
        with contextlib.suppress(Exception):
            booted.stop()
    with s.Boot(args, directory, mode, engine, atomic, oracle, aof, 'restart') as again:
        assert s.integers(again.c.must('MGET', *pair, hot)) == live, 'AOF restart changed the data'
    return dict(rewrites=rewrites[0], units=units, writes=writes, live=live)


CASES = {'shutdown-save': case_shutdown_save, 'sigterm': case_sigterm, 'flushall': case_flushall,
         'bgsave-flip': case_bgsave_flip,
         'aofrw-exec': lambda *a: case_aofrw(*a, shape='exec'),
         'aofrw-script': lambda *a: case_aofrw(*a, shape='script')}


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
    p.add_argument('--seconds', type=float, default=5)
    p.add_argument('--stall', type=float, default=5)
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
