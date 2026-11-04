#!/usr/bin/env python3
"""parkwake: park/wake witnesses of the IO and executor loops; no throughput measurement.

Every leg boots a fresh pinned server (LC_ALL=C, `--hz 1 --dynamic-hz no`, LB and automatic FLIP
off unless the case needs them) and asserts a latency DEADLINE on a protocol event whose producer
owes the parked consumer a wake. A missed wake on the production binary costs up to the 50 ms
park net (or the client-cron beat); on the diagnostic arm (`make park-net-arm`, park_net.h) it
costs 2 s, so the same rows show a PRE defect as a multi-second stall there. Each case also
asserts that its window really opened (anti-vacuity). No reply is retried; a failed leg is a
verdict, never re-rolled.

cases (--case):
  retry     F1  IO retry lane: EXEC with PUBLISH (served, delivered; also with a hot owner),
                EXEC with SUBSCRIBE, contended cross-owner EXEC retries and forced script
                escalation, one call outstanding; every call under --deadline-ms.
  script    F2  one-executor split boot: a blocker EVAL holds the executor while >= 300
                cross-shard RPOPLPUSH and two-key EVALs queue; the own EX->EX lane fills
                ("second hop queue is full") and a script wave is refused. Every reply in 5 s.
  swapdb    F3  appendfsync always + MULTI/EXEC load: each SWAPDB under --deadline-ms.
  watchdog  #4  SWAPDB issued while a 3.5 s EVAL runs: OK after it, the server alive, no
                "fatal: database" (Redis runs SWAPDB after the command in progress).
  control   F10 CONFIG SET appendonly rendezvous, CLIENT UNPAUSE and DEBUG CLIENT-LB (2s, one
                database): each control publication reaches parked workers at once.
  epoch     F11 connect/QUIT cycles on an idle server: the server-side fd release of each
                closed connection under --deadline-ms (16 databases and the 1-database control).
  slotless  F12 > 2,048 connections on one IO thread: ~2,200 slot-less clients blocked on one
                list are all served by one RPUSH, overflowing the EX->IO channel; every BLPOP
                reply under --slow-ms; notify_drop > 0 in the shutdown report.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import random
import re
import selectors
import socket
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import Conn, RespError, encode, info, lbsignals, topology, wait_ready  # noqa: E402
from _gate_process import stop_process  # noqa: E402


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def cpus(spec):
    out = []
    for item in spec.split(','):
        lo, _, hi = item.partition('-')
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


class Server:
    """One owned server lifetime; stop() requires a clean exit."""

    def __init__(self, a, label, *, mode=None, engine=None, databases=16, extra=(), cores=None,
                 ratio=None, hz='1', lb=False, flip_auto=False, appendonly='no', timeout=60,
                 preload=None):
        self.a, self.label = a, label
        mode = mode or a.mode
        engine = engine or a.engine
        self.directory = a.output / label
        self.directory.mkdir(parents=True, exist_ok=True)
        listening = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{a.port}'], text=True).strip()
        require(not listening, f'port {a.port} is already listening: {listening}')
        argv = ['taskset', '-c', cores or a.cores, str(a.binary.resolve()), '--bind', '127.0.0.1',
                '--port', str(a.port), '--dir', str(self.directory.resolve()), '--save', '',
                '--appendonly', appendonly, '--enable-debug-command', 'yes', '--shards', '16',
                '--thread-mode', mode, '--net-io', engine, '--databases', str(databases),
                '--hz', hz, '--dynamic-hz', 'no', '--key-lb', '0',
                '--client-lb', '1' if lb else '0']
        if mode == '2s':
            argv += ['--ratio', ratio or a.ratio, '--flip-auto', '1' if flip_auto else '0']
        argv += list(extra)
        self.argv = argv
        (self.directory / 'argv.json').write_text(json.dumps(argv) + '\n')
        self.log_path = self.directory / 'server.log'
        self.log = self.log_path.open('w')
        env = dict(os.environ, LC_ALL='C')
        if preload:
            env['LD_PRELOAD'] = str(Path(preload).resolve())
        self.proc = subprocess.Popen(argv, stdout=self.log, stderr=subprocess.STDOUT, env=env)
        self.exit = None
        try:
            self.admin = wait_ready('127.0.0.1', a.port, process=self.proc, timeout=timeout)
        except BaseException:
            self.kill()
            raise
        self.pid = self.proc.pid

    def conn(self, timeout=None):
        return Conn('127.0.0.1', self.a.port, timeout=timeout or self.a.conn_timeout)

    def alive(self):
        return self.proc.poll() is None

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.log.close()

    def stop(self):
        with contextlib.suppress(Exception):
            self.admin.close()
        forced = stop_process(self.proc)
        self.log.close()
        self.exit = dict(rc=self.proc.returncode, forced=forced)
        return self.exit

    def log_text(self):
        return self.log_path.read_text(errors='replace')


def io_thread(conn):
    reply = conn.must('DEBUG', 'IO-THREAD')
    require(isinstance(reply, int), f'DEBUG IO-THREAD returned {reply!r}')
    return reply


def io_threads(admin, mode):
    roles = topology(admin).roles
    return sorted(t for t, role in roles.items() if role == ('fused' if mode == '1s' else 'io'))


def placed(server, want, limit=4000):
    """{io: [conn, ...]} with want[io] connections per IO thread, extras closed."""
    have = {t: [] for t in want}
    extras = []
    for _ in range(limit):
        if all(len(have[t]) >= n for t, n in want.items()):
            break
        c = server.conn()
        t = io_thread(c)
        if t in have and len(have[t]) < want[t]:
            have[t].append(c)
        else:
            extras.append(c)
    else:
        raise AssertionError(f'placement did not converge: { {t: len(v) for t, v in have.items()} }')
    for c in extras:
        c.close()
    return have


def keys_on_distinct_owners(admin, prefix, count=2, limit=4000):
    names = [f'{prefix}:{i}' for i in range(limit)]
    chosen, owners = [], set()
    for start in range(0, limit, 256):
        rows = admin.must('DEBUG', 'SHARDS', *names[start:start + 256])
        for name, (sid, owner) in zip(names[start:start + 256], rows):
            if owner not in owners:
                owners.add(owner)
                chosen.append(name)
                if len(chosen) == count:
                    return chosen
    raise AssertionError(f'{prefix}: {count} keys on distinct owners not found')


def keys_on_distinct_shards(admin, prefix, count=2, limit=4000):
    names = [f'{prefix}:{i}' for i in range(limit)]
    chosen, shards = [], set()
    for start in range(0, limit, 256):
        rows = admin.must('DEBUG', 'SHARDS', *names[start:start + 256])
        for name, (sid, owner) in zip(names[start:start + 256], rows):
            if sid not in shards:
                shards.add(sid)
                chosen.append(name)
                if len(chosen) == count:
                    return chosen
    raise AssertionError(f'{prefix}: {count} keys on distinct shards not found')


def stat(admin, field, section='stats'):
    value = info(admin, section).get(field)
    require(value is not None, f'INFO {section} has no {field}')
    return int(value)


def gap(i):
    # Leave no producer to wake a stranded continuation; vary the idle phase against the tick.
    time.sleep(0.001 + (i % 7) * 0.0001)


def timed(fn):
    t0 = time.monotonic_ns()
    value = fn()
    return (time.monotonic_ns() - t0) / 1e6, value


# ---- F1: IO retry lane ----------------------------------------------------------------------
def case_retry(a, leg):
    s = Server(a, leg['label'], databases=leg['databases'])
    try:
        admin = s.admin
        out = leg.setdefault('forms', {})
        # A. EXEC with PUBLISH: the IO completes the unit after the publication chain.
        sub = s.conn()
        sub.must('SUBSCRIBE', 'pw:ch')
        c = s.conn()
        samples = []
        for i in range(a.calls):
            gap(i)
            ms, replies = timed(lambda: (c.send('MULTI'), c.send('SET', 'pw:k', str(i)),
                                         c.send('PUBLISH', 'pw:ch', str(i)), c.send('EXEC'),
                                         [c.read() for _ in range(4)])[-1])
            require(replies[0] == b'OK' and replies[3] == [b'OK', 1], f'EXEC+PUBLISH reply {replies!r}')
            message = sub.read()
            require(message == [b'message', b'pw:ch', str(i).encode()], f'subscriber got {message!r}')
            samples.append(ms)
            if sum(x > a.deadline_ms for x in samples) >= a.stop_after:
                break   # a failed deadline needs no further traffic
        out['exec_publish'] = summary(samples, a.deadline_ms)
        # A2. The same unit while another connection keeps the owner hot (p1 GETs on a key of the
        # same owner): a spinning owner finishes the unit while its IO is still inside its pass,
        # which is the window of the retry lane's conditional wake (audit F1 form 2).
        hot_key = next(k for k in (f'pw:hot:{j}' for j in range(4000))
                       if admin.must('DEBUG', 'SHARDS', k)[0][1] == admin.must('DEBUG', 'SHARDS', 'pw:k')[0][1])
        admin.must('SET', hot_key, 'h')
        stop_hot = threading.Event()

        def hot():
            conn = s.conn()
            try:
                while not stop_hot.is_set():
                    conn.cmd('GET', hot_key)
            finally:
                conn.close()

        heater = threading.Thread(target=hot, daemon=True)
        heater.start()
        samples = []
        try:
            for i in range(a.calls):
                gap(i)
                ms, replies = timed(lambda: (c.send('MULTI'), c.send('SET', 'pw:k', str(i)),
                                             c.send('PUBLISH', 'pw:ch', str(i)), c.send('EXEC'),
                                             [c.read() for _ in range(4)])[-1])
                require(replies[0] == b'OK' and replies[3] == [b'OK', 1], f'EXEC+PUBLISH reply {replies!r}')
                message = sub.read()
                require(message == [b'message', b'pw:ch', str(i).encode()], f'subscriber got {message!r}')
                samples.append(ms)
                if sum(x > a.deadline_ms for x in samples) >= a.stop_after:
                    break
        finally:
            stop_hot.set()
            heater.join(30)
        out['exec_publish_hot_owner'] = summary(samples, a.deadline_ms)
        sub.close()
        # B. EXEC with SUBSCRIBE/UNSUBSCRIBE: the subscription half of the same path.
        samples = []
        for i in range(a.calls):
            gap(i)
            ms, replies = timed(lambda: (c.send('MULTI'), c.send('SUBSCRIBE', 'pw:s'),
                                         c.send('UNSUBSCRIBE', 'pw:s'), c.send('EXEC'),
                                         [c.read() for _ in range(4)])[-1])
            require(replies[0] == b'OK' and isinstance(replies[3], list) and len(replies[3]) == 2,
                    f'EXEC+SUBSCRIBE reply {replies!r}')
            samples.append(ms)
            if sum(x > a.deadline_ms for x in samples) >= a.stop_after:
                break
        out['exec_subscribe'] = summary(samples, a.deadline_ms)
        # C. Contended cross-owner EXECs: dooms/wounds retry through the IO lane.
        k1, k2 = keys_on_distinct_owners(admin, 'pw:t', 2)
        before = stat(admin, 'atomic_txn_retries')
        samples = parallel_calls(s, 8, max(1, a.calls // 4), lambda i, conn: conn.raw(
            encode('MULTI') + encode('INCR', k1) + encode('INCR', k2) + encode('EXEC')), 4,
            lambda replies: isinstance(replies[3], list) and len(replies[3]) == 2)
        retries = stat(admin, 'atomic_txn_retries') - before
        out['exec_contended'] = dict(summary(samples, a.deadline_ms), retries=retries)
        # D. Forced script escalation (at412's opposite-order rivals): each escalated attempt is
        # handed to the IO lane by its executor.
        if leg.get('escalate', True):
            e1, e2 = keys_on_distinct_owners(admin, 'pw:e', 2)
            admin.must('MSET', e1, 0, e2, 0)
            admin.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
            admin.must('DEBUG', 'SCRIPT-STAGE-DEFER', 3000)
            before = stat(admin, 'script_escalations')
            script = "return {redis.call('INCR', KEYS[1]), redis.call('INCR', KEYS[2])}"
            samples = parallel_calls(s, 2, max(1, a.calls // 4), lambda i, conn: conn.send(
                'EVAL', script, 2, *((e1, e2) if i % 2 == 0 else (e2, e1))), 1,
                lambda replies: isinstance(replies[0], list) and len(replies[0]) == 2)
            escalations = stat(admin, 'script_escalations') - before
            admin.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
            admin.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 0)
            out['escalation'] = dict(summary(samples, a.deadline_ms), escalations=escalations)
            if escalations <= 0:
                leg['reasons'].append('vacuous: no script escalation happened')
        if retries <= 0:
            leg['notes'].append('no contended EXEC retry happened (form C unarmed this leg)')
        c.close()
        for name, row in out.items():
            if row['misses']:
                leg['reasons'].append(f"{name}: {row['misses']} calls over {a.deadline_ms} ms "
                                      f"(max {row['max_ms']:.1f} ms)")
    finally:
        finish(s, leg)


def parallel_calls(s, actors, rounds, send, replies, valid):
    """`actors` connections, each issuing `rounds` calls one outstanding; every call's latency."""
    samples, errors = [], []
    lock = threading.Lock()

    def run(i):
        conn = s.conn()
        try:
            for r in range(rounds):
                gap(r)
                t0 = time.monotonic_ns()
                send(i, conn)
                got = [conn.read() for _ in range(replies)]
                ms = (time.monotonic_ns() - t0) / 1e6
                if not valid(got):
                    raise AssertionError(f'actor {i} reply {got!r}')
                with lock:
                    samples.append(ms)
        except BaseException as error:
            errors.append(repr(error))
        finally:
            conn.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(actors)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    require(not errors and not any(t.is_alive() for t in threads), f'actors failed: {errors[:3]}')
    return samples


def summary(samples, deadline_ms):
    samples = list(samples)
    ordered = sorted(samples)
    return dict(calls=len(samples), max_ms=round(ordered[-1], 3) if ordered else None,
                p50_ms=round(ordered[len(ordered) // 2], 3) if ordered else None,
                misses=sum(x > deadline_ms for x in samples),
                slowest=[round(x, 3) for x in ordered[-5:]])


def finish(s, leg):
    exit = s.stop() if s.alive() else dict(rc=s.proc.returncode, forced=False)
    leg['server_exit'] = exit
    text = s.log_text()
    if 'fatal: database' in text:
        leg['reasons'].append('server log: ' + next(l for l in text.splitlines() if 'fatal: database' in l))
    if exit != dict(rc=0, forced=False):
        leg['reasons'].append(f'server exit {exit}')
    m = re.findall(r'notify_drop=(\d+)', text)
    leg['notify_drop'] = sum(int(x) for x in m)



def fill_list(conn, key, count, batch=10000):
    conn.sock.settimeout(120)
    sent = 0
    while sent < count:
        n = min(batch, count - sent)
        conn.raw(encode('RPUSH', key, *[str((sent + i) * 7919 % 1000003) for i in range(n)]))
        sent += n
        require(isinstance(conn.read(), int), 'RPUSH failed')


# ---- F2: script re-post refused by the executor's own full lane -----------------------------
def case_script(a, leg):
    require(a.mode == '2s', 'the own-lane livelock needs a split boot with one executor')
    s = Server(a, leg['label'], databases=leg['databases'], ratio='7:1', extra=('--atomic', '0'))
    conns = []
    try:
        admin = s.admin
        ios = io_threads(admin, '2s')
        require(len(ios) == 7 and len(topology(admin).owners) == 1, 'need 7 IO threads and one executor')
        last = max(ios)
        # The drain visits producers in thread order: the scripts' lane is drained last, after
        # every RPOPLPUSH first hop posted its second hop into the executor's own lane.
        movers = a.movers
        per_io = {t: (movers + len(ios) - 2) // (len(ios) - 1) for t in ios if t != last}
        per_io[last] = a.scripts
        groups = placed(s, per_io, limit=40 * (movers + a.scripts))
        conns = [c for v in groups.values() for c in v]
        src, dst = [], []
        names = [f'pw:q:{i}' for i in range(4 * movers)]
        rows = []
        for start in range(0, len(names), 256):
            rows += admin.must('DEBUG', 'SHARDS', *names[start:start + 256])
        by_shard = {}
        for name, (sid, _owner) in zip(names, rows):
            by_shard.setdefault(sid, []).append(name)
        shards = sorted(by_shard)
        for i in range(movers):
            a_sid, b_sid = shards[i % len(shards)], shards[(i + 1) % len(shards)]
            src.append(by_shard[a_sid].pop())
            dst.append(by_shard[b_sid].pop())
        for i in range(0, movers, 64):
            admin.raw(b''.join(encode('RPUSH', k, 'job') for k in src[i:i + 64]))
            for _ in src[i:i + 64]:
                require(admin.read() == 1, 'source list setup')
        e1, e2 = keys_on_distinct_shards(admin, 'pw:sx', 2)
        fill_list(admin, 'pw:block', a.blocker_elements)
        blocker = s.conn(timeout=60)
        movers_conns = [c for t, v in groups.items() if t != last for c in v][:movers]
        script_conns = groups[last]
        script = "redis.call('INCR', KEYS[1]); return redis.call('INCR', KEYS[2])"
        blocker.send('SORT', 'pw:block', 'ALPHA', 'LIMIT', 0, 1)
        time.sleep(0.05)
        for c, k1, k2 in zip(movers_conns, src, dst):
            c.send('RPOPLPUSH', k1, k2)
        time.sleep(0.02)
        for c in script_conns:
            c.send('EVAL', script, 2, e1, e2)
        deadline = time.monotonic() + a.reply_seconds
        full = ok = 0
        for c in movers_conns + script_conns + [blocker]:
            c.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                reply = c.read()
            except (socket.timeout, TimeoutError):
                leg['reasons'].append(f'a reply did not arrive within {a.reply_seconds} s '
                                      f'(executor livelocked)')
                break
            if isinstance(reply, RespError):
                require('second hop queue is full' in str(reply), f'unexpected error {reply}')
                full += 1
            else:
                ok += 1
        leg.update(movers=len(movers_conns), scripts=len(script_conns), lane_full_errors=full,
                   replies_ok=ok)
        if not leg['reasons'] and full == 0:
            leg['reasons'].append('vacuous: the executor\'s own lane never filled '
                                  '(no "second hop queue is full")')
        if not leg['reasons']:
            require(admin.must('GET', e1) == str(len(script_conns)).encode(), 'script effects lost')
            require(s.alive(), 'server died')
    finally:
        for c in conns:
            c.close()
        finish(s, leg)


# ---- F3: SWAPDB while EXEC replies retire behind fsync --------------------------------------
def case_swapdb(a, leg):
    require(a.mode == '2s', 'the fused IO acknowledges DatabaseExDrain itself (1s is immune)')
    # Durability must lag the executors' spin: under epoll persistence uses the syscall engine,
    # and the LD_PRELOAD shim delays each fsync/fdatasync (tests/parkwake_slowsync.c).
    s = Server(a, leg['label'], databases=16, appendonly='yes', engine='epoll', preload=a.slowsync,
               extra=('--appendfsync', 'everysec', '--atomic', str(leg.get('atomic', 1))))
    stop = threading.Event()
    errors = []
    try:
        admin = s.admin
        k1, k2 = keys_on_distinct_owners(admin, 'pw:w', 2)

        def load(index):
            conn = s.conn()
            try:
                while not stop.is_set():
                    conn.raw(encode('MULTI') + encode('INCR', k1) + encode('INCR', k2) + encode('EXEC'))
                    replies = [conn.read() for _ in range(4)]
                    if not (isinstance(replies[3], list) and len(replies[3]) == 2):
                        raise AssertionError(f'EXEC reply {replies!r}')
            except BaseException as error:
                if not stop.is_set():
                    errors.append(repr(error))
            finally:
                conn.close()

        workers = [threading.Thread(target=load, args=(i,), daemon=True) for i in range(4)]
        for t in workers:
            t.start()
        time.sleep(0.2)
        swapper = s.conn()
        samples = []
        for i in range(a.calls):
            gap(i)
            ms, reply = timed(lambda: swapper.cmd('SWAPDB', 0, 1))
            require(reply == b'OK', f'SWAPDB reply {reply!r}')
            samples.append(ms)
        stop.set()
        for t in workers:
            t.join(10)
        require(not errors, f'load failed: {errors[:2]}')
        leg['swapdb'] = summary(samples, a.deadline_ms)
        if leg['swapdb']['misses']:
            leg['reasons'].append(f"{leg['swapdb']['misses']} SWAPDB over {a.deadline_ms} ms "
                                  f"(max {leg['swapdb']['max_ms']:.1f} ms)")
        swapper.close()
    finally:
        stop.set()
        finish(s, leg)


# ---- item 4: SWAPDB during a command longer than the namespace watchdog ----------------------
def case_watchdog(a, leg):
    s = Server(a, leg['label'], databases=16)
    try:
        admin = s.admin
        fill_list(admin, 'pw:long', a.long_elements)
        runner = s.conn(timeout=120)
        swapper = s.conn(timeout=120)
        t0 = time.monotonic()
        runner.send('SORT', 'pw:long', 'ALPHA', 'LIMIT', 0, 1)
        time.sleep(0.3)
        swapper.send('SWAPDB', 0, 1)
        try:
            long_reply = runner.read()
            long_s = time.monotonic() - t0
            swap_reply = swapper.read()
            swap_s = time.monotonic() - t0
        except (EOFError, ConnectionError, OSError) as error:
            leg['reasons'].append(f'connection lost during the long command: {error!r} '
                                  f'(server alive={s.alive()})')
            return
        leg.update(long_command_s=round(long_s, 3), swapdb_done_s=round(swap_s, 3))
        require(isinstance(long_reply, list) and len(long_reply) == 1, f'SORT reply {long_reply!r}')
        require(swap_reply == b'OK', f'SWAPDB reply {swap_reply!r}')
        if long_s < 3.0:
            leg['reasons'].append(f'vacuous: the long command took only {long_s:.2f} s '
                                  '(watchdog bound about 2.7 s)')
        require(swap_s >= long_s - 0.05, 'SWAPDB answered before the command in progress ended')
        require(admin.must('PING') == b'PONG' and s.alive(), 'server not answering after SWAPDB')
        require(admin.must('SELECT', 1) == b'OK' and admin.must('LLEN', 'pw:long') == a.long_elements,
                'the swapped namespace does not hold the list')
    finally:
        finish(s, leg)


# ---- F10: control publications ---------------------------------------------------------------
def case_control(a, leg):
    out = leg.setdefault('forms', {})
    s = Server(a, leg['label'] + '-config', databases=leg['databases'])
    try:
        admin = s.admin
        samples = []
        for i in range(a.config_calls):
            gap(i)
            value = 'yes' if i % 2 == 0 else 'no'
            ms, reply = timed(lambda: admin.cmd('CONFIG', 'SET', 'appendonly', value))
            require(reply == b'OK', f'CONFIG SET appendonly {value}: {reply!r}')
            samples.append(ms)
            if value == 'yes':   # let the triggered rewrite settle before the next rendezvous
                for _ in range(400):
                    if b'aof_rewrite_in_progress:0' in admin.must('INFO', 'persistence'):
                        break
                    time.sleep(0.005)
        out['config_rendezvous'] = summary(samples, a.deadline_ms)
        # CLIENT UNPAUSE: a held write on another IO must resume at once.
        ios = io_threads(admin, a.mode)
        mine = io_thread(admin)
        other = next(t for t in ios if t != mine)
        held = placed(s, {other: 1})[other][0]
        samples = []
        for i in range(a.unpause_calls):
            require(admin.must('CLIENT', 'PAUSE', 60000, 'WRITE') == b'OK', 'CLIENT PAUSE')
            held.send('SET', 'pw:p', str(i))
            time.sleep(0.1)
            require(admin.must('CLIENT', 'UNPAUSE') == b'OK', 'CLIENT UNPAUSE')
            t0 = time.monotonic_ns()
            require(held.read() == b'OK', 'held SET')
            samples.append((time.monotonic_ns() - t0) / 1e6)
        out['unpause'] = summary(samples, a.deadline_ms)
        held.close()
    finally:
        finish(s, leg)
    if a.mode == '2s':
        # DEBUG CLIENT-LB: the source IO performs the move requested on the destination. In the
        # 16-database runtime the readiness fence refuses a move while any peer is mid-pass
        # (reported residual), so the wake is witnessed where a move completes: one database.
        s = Server(a, leg['label'] + '-clientlb', databases=1, lb=True)
        try:
            admin = s.admin
            ios = io_threads(admin, '2s')
            groups = placed(s, {ios[0]: 2, ios[1]: 1})
            selected, waker = groups[ios[0]]
            destination = groups[ios[1]][0]
            for _ in range(20):
                for c in (selected, waker, destination):
                    require(c.must('PING') == b'PONG', 'warm-up')
            client_id = selected.must('CLIENT', 'ID')
            before = stat(admin, 'tomokv_clientlb_moves', 'LB')
            deadline = time.monotonic() + 30
            while True:
                reply = destination.cmd('DEBUG', 'CLIENT-LB', client_id)
                if reply == b'OK':
                    break
                require(isinstance(reply, RespError) and 'no owner observation' in str(reply), f'{reply!r}')
                require(time.monotonic() < deadline, 'client-LB owner observation never armed')
                require(selected.must('PING') == b'PONG', 'observation traffic')
                time.sleep(0.01)
            t0 = time.monotonic_ns()
            while stat(admin, 'tomokv_clientlb_moves', 'LB') == before:
                require(time.monotonic_ns() - t0 < 10e9, 'directed client-LB move never completed')
                time.sleep(0.0005)
            out['debug_clientlb'] = summary([(time.monotonic_ns() - t0) / 1e6], a.deadline_ms)
            require(io_thread(selected) == ios[1], 'the selected connection did not move')
            for c in (selected, waker, destination):
                c.close()
        finally:
            finish(s, leg)
    for name, row in out.items():
        if row['misses']:
            leg['reasons'].append(f"{name}: {row['misses']} over {a.deadline_ms} ms (max {row['max_ms']:.1f} ms)")


# ---- F11: client-work epoch across the park --------------------------------------------------
def case_epoch(a, leg):
    s = Server(a, leg['label'], databases=leg['databases'])
    try:
        fd_dir = Path(f'/proc/{s.pid}/fd')
        samples = []
        for i in range(a.calls):
            c = s.conn()
            require(c.must('PING') == b'PONG', 'PING')
            time.sleep(0.003)   # every peer parks
            base = len(os.listdir(fd_dir))
            t0 = time.monotonic_ns()
            c.send('QUIT')
            require(c.read() == b'OK', 'QUIT')
            c.close()
            while len(os.listdir(fd_dir)) >= base:
                require(time.monotonic_ns() - t0 < 10e9, 'closed connection fd never released')
                time.sleep(0.0002)
            samples.append((time.monotonic_ns() - t0) / 1e6)
        leg['fd_release'] = summary(samples, a.deadline_ms)
        if leg['fd_release']['misses']:
            leg['reasons'].append(f"{leg['fd_release']['misses']} fd releases over {a.deadline_ms} ms "
                                  f"(max {leg['fd_release']['max_ms']:.1f} ms)")
    finally:
        finish(s, leg)


# ---- F12: completion notices for connections beyond the ready-mask slots ----------------------
def case_slotless(a, leg):
    cores = cpus(a.cores)
    if a.mode == '2s':
        s = Server(a, leg['label'], databases=leg['databases'], ratio='1:1',
                   cores=f'{cores[0]},{cores[1]}', extra=('--maxclients', '20000'))
    else:
        s = Server(a, leg['label'], databases=leg['databases'], cores=f'{cores[0]},{cores[1]}',
                   extra=('--maxclients', '20000'))
    conns = []
    try:
        admin = s.admin
        ios = io_threads(admin, a.mode)
        target = ios[0]
        key = next(k for k in (f'pw:z:{i}' for i in range(4000))
                   if admin.must('DEBUG', 'SHARDS', k)[0][1] != target)
        admin.must('SET', key, 'v' * 32)
        conns = placed(s, {target: a.connections}, limit=8 * a.connections)[target]
        sel = selectors.DefaultSelector()
        burst = conns[-a.burst:]   # the youngest connections: beyond the 1,024 ready-mask slots
        worst = []
        for r in range(a.rounds):
            # Every slot-less client blocks on one list owned by another thread; ONE push then
            # serves them all inside a single owner pass, so their completion notices outrun
            # the IO's drain of the 1,024-entry EX->IO channel.
            queue = f'{key}:q{r}'
            for c in burst:
                c.sock.sendall(encode('BLPOP', queue, 0))
            deadline = time.monotonic() + 30
            while int(info(admin, 'clients')['blocked_clients']) < len(burst):
                require(time.monotonic() < deadline, 'clients never all blocked')
                time.sleep(0.01)
            time.sleep(0.2)   # every worker parks
            pending = {}
            for c in burst:
                pending[c.sock.fileno()] = [c, bytearray()]
                sel.register(c.sock, selectors.EVENT_READ)
            t0 = time.monotonic_ns()
            require(admin.must('RPUSH', queue, *[str(i) for i in range(len(burst))]) == len(burst), 'RPUSH')
            slowest = 0
            limit_s = a.slow_ms / 1000 * 30
            while pending:
                ready = sel.select(timeout=max(0.0, limit_s - (time.monotonic_ns() - t0) / 1e9))
                if not ready:
                    break
                for k, _ in ready:
                    c, buf = pending[k.fd]
                    buf += c.sock.recv(1 << 16)
                    if buf.endswith(b'\r\n') and buf.count(b'\r\n') >= 5:
                        slowest = max(slowest, (time.monotonic_ns() - t0) / 1e6)
                        sel.unregister(c.sock)
                        del pending[k.fd]
            if pending:
                leg['reasons'].append(f'round {r}: {len(pending)} BLPOP replies missing after '
                                      f'{limit_s * 1000:.0f} ms')
                for k in list(pending):
                    sel.unregister(pending[k][0].sock)
                break
            worst.append(round(slowest, 3))
        leg['rounds_slowest_ms'] = worst
        if worst and max(worst) > a.slow_ms:
            leg['reasons'].append(f'slowest reply {max(worst):.1f} ms > {a.slow_ms} ms')
    finally:
        for c in conns:
            c.close()
        finish(s, leg)
    if not leg['reasons'] and leg.get('notify_drop', 0) == 0:
        leg['reasons'].append('vacuous: no completion notice was refused (notify_drop 0)')


CASES = {'retry': case_retry, 'script': case_script, 'swapdb': case_swapdb,
         'watchdog': case_watchdog, 'control': case_control, 'epoch': case_epoch,
         'slotless': case_slotless}


def legs_for(a):
    out = []
    for databases in map(int, a.databases.split(',')):
        out.append(dict(label=f'{a.case}-{a.mode}-{a.engine}-db{databases}', databases=databases))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--case', choices=sorted(CASES), required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), required=True)
    p.add_argument('--databases', default='16,1')
    p.add_argument('--calls', type=int, default=200)
    p.add_argument('--deadline-ms', type=float, default=20.0)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--movers', type=int, default=300)
    p.add_argument('--conn-timeout', type=float, default=30.0)
    p.add_argument('--stop-after', type=int, default=3, help='misses after which a form stops')
    p.add_argument('--slowsync', type=Path, default=Path(__file__).resolve().parents[1] / 'build/parkwake-slowsync.so')
    p.add_argument('--scripts', type=int, default=4)
    p.add_argument('--reply-seconds', type=float, default=5.0)
    p.add_argument('--blocker-elements', type=int, default=1000000)
    p.add_argument('--long-elements', type=int, default=10000000)
    p.add_argument('--config-calls', type=int, default=10)
    p.add_argument('--unpause-calls', type=int, default=10)
    p.add_argument('--connections', type=int, default=3300)
    p.add_argument('--burst', type=int, default=2200)
    p.add_argument('--pipeline', type=int, default=1)
    p.add_argument('--rounds', type=int, default=10)
    p.add_argument('--slow-ms', type=float, default=100.0)
    a = p.parse_args()
    require(1024 <= a.port < 32768, 'port outside the lane range')
    os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=True)
    legs = []
    for leg in legs_for(a):
        leg.update(case=a.case, mode=a.mode, engine=a.engine, reasons=[], notes=[], passed=False)
        try:
            CASES[a.case](a, leg)
        except BaseException as error:
            leg['reasons'].append(f'error: {error!r}')
            leg['traceback'] = traceback.format_exc()
        leg['passed'] = not leg['reasons']
        legs.append(leg)
        print(json.dumps({k: v for k, v in leg.items() if k != 'traceback'}), flush=True)
    passed = bool(legs) and all(leg['passed'] for leg in legs)
    (a.output / 'result.json').write_text(json.dumps(dict(
        case=a.case, mode=a.mode, engine=a.engine, binary=str(a.binary), passed=passed, legs=legs),
        indent=2) + '\n')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
