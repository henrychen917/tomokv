#!/usr/bin/env python3
"""txnfix4 directed witnesses for round-5 CD5.3, CD5.4, CD5.5, CD5.6 and TM5.1. No rates.

Usage: txnfix4.py --binary B --oracle R --cores LIST --port P --engine uring|epoll
                  --case oom|watch|crash|hash|placement --output DIR [--iterations N]

Every case boots its own servers on --cores and on ports P (TomoKV) and P+1 (Redis 7.4 oracle),
with LC_ALL=C and persistence off (the hash case saves into its own private directory and deletes
the dump). Each server is stopped by its recorded PID and must exit cleanly; a TomoKV leg also
needs a clean shutdown report. TomoKV runs eight legs: 2s and 1s, atomic 0 and 1, one and sixteen
databases (the 1s/16-database legs arm the read-local lane). The oracle runs the same sequences
wherever the expectation is Redis's own; same-shard, same-owner and cross-owner are TomoKV
placements, proved per boot with DEBUG SHARDS on the FINAL key names, and are ignored by Redis.

oom        CD5.4. SMOVE, LMOVE, RPOPLPUSH, BLMOVE, BRPOPLPUSH, RENAME, RENAMENX (and MOVE with 16
           databases) under noeviction and volatile-lru, with three triggers: `over` (maxmemory 1:
           the source's shard is over budget), `edge` (maxmemory 1mb, the destination shard filled
           until 200/50/10/1-byte SETs are refused, the auditor's L-T3 shape) and `dst-over` (the
           same fill, then maxmemory 512kb: only the destination shard is over budget). Redis 7.4:
           a DENYOOM mover (LMOVE, RPOPLPUSH, BLMOVE, BRPOPLPUSH) is refused before it changes
           anything when the server is over budget, SMOVE/RENAME/RENAMENX/MOVE have no DENYOOM and
           always run, and no command applies only half of a move. `edge` may leave a TomoKV shard
           just under budget, where a DENYOOM mover may run; it may never lose or duplicate the
           element.
watch      CD5.5. A watched key popped by a two-key LMPOP/ZMPOP/BLMPOP/BZMPOP aborts the watcher's
           EXEC. Controls: a pop that takes the OTHER key, and a pop of an empty key, commit it.
crash      CD5.6. The six aborting Z-T6 shapes (WATCH, a two-key pop of the watched key, then a
           CLIENT TRACKING read), N fresh-key iterations each, alternating same-owner/cross-owner.
           Each iteration requires a live server, the exact tracked read and an aborted watched
           EXEC, then pops the same key under a new WATCH: the round-5 root (an atomic-pop WATCH
           reservation that is never decided) shows as watch_reservation_coexist growth.
hash       CD5.3. Fields lapse while their shard is captured by BGSAVE (large co-located values
           stretch the capture). Reads must not serve lapsed fields, HINCRBY/HINCRBYFLOAT/HSETNX
           must treat them as absent, and their results must survive the capture. The window is
           proved per attempt (deadline passed, rdb_bgsave_in_progress 1 after the last command);
           an attempt that missed it is re-rolled on fresh state, at most three times.
placement  TM5.1. tests/execfix.py --self-test rejects a planted single-owner geometry, and on
           every leg its key selection (including the loss arm's final suffixed names) is proved
           to span two owners with DEBUG SHARDS.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from _lib import Conn, RespError, wait_ready

ROOT = Path(__file__).resolve().parent.parent
LEGS = [('2s', 0, 1, 0), ('2s', 1, 1, 0), ('2s', 0, 16, 0), ('2s', 1, 16, 0),
        ('1s', 0, 1, 0), ('1s', 1, 1, 0), ('1s', 0, 16, 1), ('1s', 1, 16, 1)]
PLACEMENTS = ('same-shard', 'same-owner', 'cross-owner')


class Failure(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


# ---- server lifetimes ---------------------------------------------------------------------------

class Server:
    """One owned lifetime on the lane's cores. stop() requires a clean exit, never a kill."""

    def __init__(self, a, label, oracle, mode='2s', atomic=0, databases=16, read_local=0):
        self.a, self.label, self.oracle = a, label, oracle
        self.port = a.port + int(oracle)
        self.dir = Path(tempfile.mkdtemp(prefix=f'{label}-', dir=a.output))
        self.log = self.dir / 'server.log'
        binary = str(Path(a.oracle if oracle else a.binary).resolve())
        argv = [binary, '--port', str(self.port), '--bind', '127.0.0.1', '--dir', str(self.dir),
                '--save', '', '--appendonly', 'no', '--enable-debug-command', 'yes']
        if oracle:
            argv += ['--databases', '16']
        else:
            argv += ['--shards', '16', '--databases', str(databases), '--net-io', a.engine,
                     '--atomic', str(atomic), '--read-local', str(read_local), '--key-lb', '0',
                     '--client-lb', '0', '--flip-auto', '0']
            argv += ['--ratio', a.ratio] if mode == '2s' else ['--thread-mode', 'fused']
        self.argv = ['taskset', '-c', a.cores] + argv
        self.proc = None

    def __enter__(self):
        with self.log.open('w') as log:
            self.proc = subprocess.Popen(self.argv, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, LC_ALL='C'))
        try:
            wait_ready('127.0.0.1', self.port, timeout=60, process=self.proc).close()
        except BaseException:
            self.proc.kill()
            self.proc.wait()
            raise
        return self

    def connect(self):
        return Conn('127.0.0.1', self.port, timeout=60)

    def quiesce(self):
        """Wait until every case connection has been reaped; only then is SIGTERM race-free."""
        deadline = time.monotonic() + 10
        clients = None
        while time.monotonic() < deadline:
            with contextlib.closing(self.connect()) as probe:
                clients = info_fields(probe, 'clients').get('connected_clients')
            if clients == '1':
                time.sleep(0.2)
                return []
            time.sleep(0.05)
        return [f'case connections were not reaped: connected_clients={clients}']

    def stop(self):
        if self.proc is None:
            return []
        problems = []
        if self.proc.poll() is None:
            try:
                problems += self.quiesce()
            except (OSError, EOFError, AssertionError) as error:
                problems.append(f'quiesce: {error!r}')
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
                problems.append('server needed SIGKILL after 60 s')
        if self.proc.returncode != 0:
            problems.append(f'server exit status {self.proc.returncode}')
        if not self.oracle and not problems:
            report = subprocess.run([sys.executable, str(ROOT / 'tests/shutdown_report.py'),
                                     str(self.log), 'clean'], capture_output=True, text=True)
            if report.returncode:
                problems.append('shutdown report: ' + (report.stdout + report.stderr).strip())
        self.proc = None
        for path in self.dir.iterdir():
            if path.name != 'server.log' and path.is_file():
                path.unlink()
        return problems

    def __exit__(self, *exc):
        problems = self.stop()
        if problems and exc[0] is None:
            raise Failure('; '.join(problems))
        return False


# ---- geometry -----------------------------------------------------------------------------------

def shards_of(c, keys):
    rows = c.must('DEBUG', 'SHARDS', *keys)
    require(isinstance(rows, list) and len(rows) == len(keys), f'DEBUG SHARDS returned {rows!r}')
    return [(int(row[0]), int(row[1])) for row in rows]


def placement_pair(c, prefix, placement, other=None):
    """(first, second) final names with the requested placement on this boot.

    `other`, when given, is a connection SELECTed into the destination database: the second
    name is then the SAME name in that database (MOVE), probed through that connection."""
    for start in range(0, 16384, 128):
        names = [f'{prefix}:{i}' for i in range(start, start + 128)]
        here = shards_of(c, names)
        if other is None:
            origin = here[0]
            pairs = [(names[0], name, origin, where) for name, where in zip(names[1:], here[1:])]
        else:
            there = shards_of(other, names)
            pairs = [(name, name, a, b) for name, a, b in zip(names, here, there)]
        for first, second, a, b in pairs:
            same_shard, same_owner = a[0] == b[0], a[1] == b[1]
            if ((placement == 'same-shard' and same_shard) or
                    (placement == 'same-owner' and same_owner and not same_shard) or
                    (placement == 'cross-owner' and not same_owner)):
                return first, second, [list(a), list(b)]
    raise Failure(f'required placement unavailable: {placement} for {prefix}')


def keys_on_shard(c, shard, prefix, count):
    out, start = [], 0
    while len(out) < count:
        names = [f'{prefix}:{i}' for i in range(start, start + 256)]
        out += [name for name, where in zip(names, shards_of(c, names)) if where[0] == shard]
        start += 256
        require(start < 1 << 20, f'no keys found on shard {shard}')
    return out[:count]


def info_fields(c, section):
    reply = c.must('INFO', section)
    return dict(line.split(':', 1) for line in reply.decode().split('\r\n') if ':' in line)


# ---- CD5.4: movers under maxmemory --------------------------------------------------------------

MOVERS = {
    'SMOVE': (False, 'set'), 'LMOVE': (True, 'list'), 'RPOPLPUSH': (True, 'list'),
    'BLMOVE': (True, 'list'), 'BRPOPLPUSH': (True, 'list'), 'RENAME': (False, 'string'),
    'RENAMENX': (False, 'string'), 'MOVE': (False, 'string'),
}


def mover_plan(verb, src, dst):
    kind = MOVERS[verb][1]
    if kind == 'set':
        return (('SADD', src, 'm1', 'm2', 'm3'), ('SMOVE', src, dst, 'm1'), 1,
                ([b'm1', b'm2', b'm3'], []), ([b'm2', b'm3'], [b'm1']), b'm1')
    if kind == 'list':
        left = verb in ('LMOVE', 'BLMOVE')
        args = {'LMOVE': ('LMOVE', src, dst, 'LEFT', 'RIGHT'),
                'BLMOVE': ('BLMOVE', src, dst, 'LEFT', 'RIGHT', '0.05'),
                'RPOPLPUSH': ('RPOPLPUSH', src, dst),
                'BRPOPLPUSH': ('BRPOPLPUSH', src, dst, '0.05')}[verb]
        moved = b'e1' if left else b'e3'
        rest = [b'e2', b'e3'] if left else [b'e1', b'e2']
        return (('RPUSH', src, 'e1', 'e2', 'e3'), args, moved,
                ([b'e1', b'e2', b'e3'], []), (rest, [moved]), moved)
    args = ('MOVE', src, '1') if verb == 'MOVE' else (verb, src, dst)
    return (('SET', src, 'payload'), args, b'OK' if verb == 'RENAME' else 1,
            (b'payload', None), (None, b'payload'), b'payload')


def fill_shard(c, shard, prefix):
    """L-T3: SET on the destination shard until 200/50/10/1-byte values are refused."""
    keys = iter(keys_on_shard(c, shard, prefix, 6000))
    stored, refusals = 0, []
    for size in (200, 50, 10, 1):
        while True:
            reply = c.cmd('SET', next(keys), 'v' * size)
            if isinstance(reply, RespError):
                require(str(reply).startswith('OOM '), f'fill: unexpected error {reply}')
                refusals.append(size)
                break
            stored += 1
    return stored, refusals


def oom_case(c, server, verb, placement, policy, trigger, prefix, emit):
    denyoom, kind = MOVERS[verb]
    c.must('CONFIG', 'SET', 'maxmemory', 0)
    c.must('FLUSHALL')
    other = None
    if verb == 'MOVE':
        other = server.connect()
        other.must('SELECT', 1)
    try:
        if server.oracle:
            src, where = f'{prefix}:src', None
            dst = src if verb == 'MOVE' else f'{prefix}:dst'
        else:
            src, dst, where = placement_pair(c, prefix, placement, other)
        seed, args, ok_reply, before_want, moved_want, element = mover_plan(verb, src, dst)
        c.must(*seed)
        src_conn, dst_conn = c, other or c

        def read():
            def one(conn, key):
                if kind == 'set':
                    return sorted(conn.must('SMEMBERS', key))
                if kind == 'list':
                    return conn.must('LRANGE', key, 0, -1)
                return conn.cmd('GET', key)
            return one(src_conn, src), one(dst_conn, dst)

        before = read()
        require(before == before_want, f'seed state {before!r}')
        c.must('CONFIG', 'SET', 'maxmemory-policy', policy)
        fill = None
        if trigger == 'over':
            c.must('CONFIG', 'SET', 'maxmemory', 1)
        else:
            c.must('CONFIG', 'SET', 'maxmemory', '1mb')
            shard = None if server.oracle else shards_of(dst_conn, [dst])[0][0]
            fill = (fill_shard(dst_conn, shard, f'{prefix}:fill') if shard is not None else
                    fill_global(c, f'{prefix}:fill'))
            if trigger == 'dst-over':
                # Halve the budget: the filled destination shard is now over it, while a
                # separate source shard holding three small elements is not.
                c.must('CONFIG', 'SET', 'maxmemory', '512kb')
        reply = c.cmd(*args)
        after = read()
        c.must('CONFIG', 'SET', 'maxmemory', 0)
    finally:
        if other:
            other.close()

    def count(state):
        total = 0
        for value in state:
            if isinstance(value, list):
                total += value.count(element)
            elif value == element:
                total += 1
        return total

    refused = isinstance(reply, RespError) and str(reply).startswith('OOM ')
    moved = reply == ok_reply and after == moved_want
    unchanged = refused and after == before
    if not denyoom:
        passed, expected = moved, 'runs: a mover without DENYOOM is never refused for memory'
    elif trigger in ('over', 'dst-over'):
        passed, expected = unchanged, 'refused before any change'
    else:
        passed, expected = moved or unchanged, 'refused unchanged or moved completely'
    passed = passed and count(after) == 1
    emit(case='CD5.4', verb=verb, placement=placement, policy=policy, trigger=trigger,
         locations=where, fill=fill, reply=reply, before=before, after=after,
         conserved=count(after) == 1, outcome='moved' if moved else 'refused' if unchanged else
         'BROKEN', expected=expected, passed=passed)
    return passed


def fill_global(c, prefix):
    """Redis has one budget: SET until refused (the oracle's half of the edge trigger)."""
    stored, refusals, index = 0, [], 0
    for size in (2000, 200, 10, 1):
        while True:
            reply = c.cmd('SET', f'{prefix}:{index}', 'v' * size)
            index += 1
            if isinstance(reply, RespError):
                refusals.append(size)
                break
            stored += 1
    return stored, refusals


def case_oom(c, server, leg, emit):
    verbs = [v for v in MOVERS if v != 'MOVE' or server.oracle or leg[2] > 1]
    placements = ('oracle',) if server.oracle else PLACEMENTS
    failures, checks = [], 0
    for policy in ('noeviction', 'volatile-lru'):
        for trigger in ('over', 'edge', 'dst-over'):
            for verb in verbs:
                for placement in placements:
                    prefix = f'txnfix4:{verb}:{policy}:{trigger}:{placement}'
                    checks += 1
                    if not oom_case(c, server, verb, placement, policy, trigger, prefix, emit):
                        failures.append(f'{verb} {placement} {policy} {trigger}')
    return checks, failures


# ---- CD5.5: multi-key pops and WATCH ------------------------------------------------------------

POPS = {
    'LMPOP': lambda m, k: ('LMPOP', 2, m, k, 'LEFT'),
    'ZMPOP': lambda m, k: ('ZMPOP', 2, m, k, 'MIN'),
    'BLMPOP': lambda m, k: ('BLMPOP', '0.05', 2, m, k, 'LEFT'),
    'BZMPOP': lambda m, k: ('BZMPOP', '0.05', 2, m, k, 'MIN'),
}


def seed_args(verb, key, count):
    if 'Z' in verb:
        return ('ZADD', key, *[x for i in range(count) for x in (i, f'v{i}')])
    return ('RPUSH', key, *[f'v{i}' for i in range(count)])


def read_args(verb, key):
    return ('ZRANGE', key, 0, -1) if 'Z' in verb else ('LRANGE', key, 0, -1)


def watched_exec(w):
    w.must('MULTI')
    w.must('PING')
    return w.cmd('EXEC')


def case_watch(c, server, leg, emit):
    failures, checks = [], 0
    with contextlib.closing(server.connect()) as w:
        for verb, pop in POPS.items():
            for placement in (('oracle',) if server.oracle else PLACEMENTS):
                for members in (1, 3):
                    prefix = f'txnfix4:{verb}:{placement}:{members}'
                    c.must('FLUSHALL')
                    if server.oracle:
                        other, key, where = f'{prefix}:other', f'{prefix}:key', None
                    else:
                        other, key, where = placement_pair(c, prefix, placement)
                    # Real pop of the watched key.
                    c.must(*seed_args(verb, key, members))
                    w.must('WATCH', key)
                    popped = c.cmd(*pop(other, key))
                    real = watched_exec(w)
                    left = c.must(*read_args(verb, key))
                    ok_real = (isinstance(popped, list) and popped[0] == key.encode() and
                               real is None and len(left) == members - 1)
                    # A pop that takes the OTHER key leaves the watched key unchanged.
                    c.must('FLUSHALL')
                    c.must(*seed_args(verb, other, 1))
                    c.must(*seed_args(verb, key, members))
                    w.must('WATCH', key)
                    popped_other = c.cmd(*pop(other, key))
                    foreign = watched_exec(w)
                    ok_foreign = (isinstance(popped_other, list) and
                                  popped_other[0] == other.encode() and foreign == [b'PONG'])
                    # An empty pop changes nothing.
                    c.must('DEL', other, key)
                    w.must('WATCH', key)
                    empty_pop = c.cmd(*pop(other, key))
                    empty = watched_exec(w)
                    ok_empty = empty_pop is None and empty == [b'PONG']
                    passed = ok_real and ok_foreign and ok_empty
                    checks += 3
                    emit(case='CD5.5', verb=verb, placement=placement, members=members,
                         locations=where, pop=popped, exec=real, left=left,
                         other_pop=popped_other, other_exec=foreign, empty_pop=empty_pop,
                         empty_exec=empty, passed=passed)
                    if not passed:
                        failures.append(f'{verb} {placement} members={members} real={ok_real} '
                                        f'foreign={ok_foreign} empty={ok_empty}')
    return checks, failures


# ---- CD5.6: WATCH + multi-key pop + CLIENT TRACKING ---------------------------------------------

# Z-T6's aborting scenarios: (name, family, tracking RESP, exec before the read, reseed, extra reads)
SCENARIOS = (
    ('mpop-watch-then-tracking', 'zset', 3, True, True, False),
    ('mpop-watch-tracking-noflush', 'zset', 3, True, False, False),
    ('mpop-watch-noexec-tracking', 'zset', 3, False, False, False),
    ('mpop-watch-tracking-resp2', 'zset', 2, True, False, False),
    ('lmpop-watch-then-tracking', 'list', 2, True, False, False),
    ('mpop-watch-tracking-otherkey', 'zset', 3, True, False, True),
)


def alive(server):
    try:
        with contextlib.closing(server.connect()) as probe:
            return probe.cmd('PING') == b'PONG'
    except (OSError, EOFError):
        return False


def case_crash(c, server, leg, emit, iterations):
    failures, checks = [], 0
    for name, family, resp, exec_first, reseed, otherkey in SCENARIOS:
        zset = family == 'zset'
        seed = (lambda k: ('ZADD', k, 1, 'a', 2, 'b', 3, 'c')) if zset else (
            lambda k: ('RPUSH', k, 'a', 'b', 'c'))
        pop = (lambda m, k: ('ZMPOP', 2, m, k, 'MIN')) if zset else (
            lambda m, k: ('LMPOP', 2, m, k, 'LEFT'))
        read = (lambda k: ('ZRANGE', k, 0, -1)) if zset else (lambda k: ('LRANGE', k, 0, -1))
        coexist = 0 if server.oracle else int(info_fields(c, 'stats')['watch_reservation_coexist'])
        bad = []
        died = False
        for iteration in range(iterations):
            placement = 'cross-owner' if iteration % 2 == 0 else 'same-owner'
            prefix = f'txnfix4:crash:{name}:{iteration}'
            c.must('FLUSHALL')
            if server.oracle:
                missing, key = f'{prefix}:missing', f'{prefix}:key'
            else:
                missing, key, _ = placement_pair(c, prefix, placement)
            with contextlib.closing(server.connect()) as w, \
                    contextlib.closing(server.connect()) as t, \
                    contextlib.closing(server.connect()) as w2:
                c.must(*seed(key))
                w.must('WATCH', key)
                popped = c.cmd(*pop(missing, key))
                outcome = watched_exec(w) if exec_first else 'later'
                if reseed:
                    c.must('FLUSHALL')
                    c.must(*seed(key))
                if resp == 3:
                    t.must('HELLO', 3)
                t.must('CLIENT', 'TRACKING', 'ON')
                if otherkey:
                    t.cmd('GET', f'{prefix}:unrelated')
                    t.cmd('GET', f'{prefix}:other')
                try:
                    observed = t.cmd(*read(key))
                except (OSError, EOFError) as error:
                    observed = repr(error)
                if not exec_first:
                    try:
                        outcome = watched_exec(w)
                    except (OSError, EOFError) as error:
                        outcome = repr(error)
                if not alive(server):
                    died = True
                else:
                    # Root probe: a second watched pop of the same key must not meet an
                    # undecided reservation left by the first.
                    w2.must('WATCH', key)
                    second = c.cmd(*pop(missing, key))
                    second_exec = watched_exec(w2)
            want = [b'a', b'b', b'c'] if reseed else [b'b', b'c']
            errors = []
            if died:
                errors.append('server died')
            if not (isinstance(popped, list) and popped[0] == key.encode()):
                errors.append(f'pop {popped!r}')
            if observed != want:
                errors.append(f'tracked read {observed!r}')
            if outcome is not None:
                errors.append(f'watched EXEC {outcome!r}')
            if not died and (not isinstance(second, list) or second_exec is not None):
                errors.append(f'second watched pop {second!r} -> {second_exec!r}')
            checks += 1
            if errors:
                bad.append((iteration, placement, errors))
            if died:
                break
        leaked = 0 if server.oracle or died else (
            int(info_fields(c, 'stats')['watch_reservation_coexist']) - coexist)
        passed = not bad and not died and leaked == 0
        emit(case='CD5.6', scenario=name, family=family, resp=resp, exec_first=exec_first,
             reseed=reseed, otherkey=otherkey, iterations=iterations, completed=checks,
             died=died, coexisting_reservations=leaked, first_failures=bad[:3],
             failed_iterations=len(bad), passed=passed)
        if not passed:
            failures.append(f'{name}: died={died} failed={len(bad)} coexist={leaked}')
        if died:
            break
    return checks, failures


# ---- CD5.3: hash field TTL during a snapshot capture --------------------------------------------

def server_ms(c):
    seconds, micros = c.must('TIME')
    return int(seconds) * 1000 + int(micros) // 1000


def hash_reads(c, key):
    return dict(
        hget=c.cmd('HGET', key, 'f'), hmget=c.cmd('HMGET', key, 'f', 'keep'),
        hexists=c.cmd('HEXISTS', key, 'f'), hstrlen=c.cmd('HSTRLEN', key, 'f'),
        hgetall=c.cmd('HGETALL', key), hkeys=c.cmd('HKEYS', key), hvals=c.cmd('HVALS', key),
        hscan=c.cmd('HSCAN', key, 0, 'COUNT', 100), hrandfield=c.cmd('HRANDFIELD', key, -5),
        hlen=c.cmd('HLEN', key), httl=c.cmd('HTTL', key, 'FIELDS', 2, 'f', 'keep'))


def hash_writes(c, key):
    return dict(
        hincrby=c.cmd('HINCRBY', key, 'n', 1), hincrbyfloat=c.cmd('HINCRBYFLOAT', key, 'g', '1.5'),
        hsetnx=c.cmd('HSETNX', key, 'x', 'new'), hpttl=c.cmd('HPTTL', key, 'FIELDS', 1, 'n'))


def hash_after(c, key):
    final = c.cmd('HGETALL', key)
    final = ({k.decode(): v.decode() for k, v in zip(final[0::2], final[1::2])}
             if isinstance(final, list) else final)
    return dict(hgetall=final, hlen=c.cmd('HLEN', key), hget_f=c.cmd('HGET', key, 'f'),
                hpttl=c.cmd('HPTTL', key, 'FIELDS', 3, 'n', 'x', 'g'))


def capture_attempt(c, server, attempt, emit, bigmb, lapse_ms):
    """One BGSAVE whose capture of the hash shard outlives the field deadlines.

    `pre` exists before the cut: its reads must filter, and its writes (which first wait for the
    key's pre-image) must still treat lapsed fields as absent. `post` is born inside the capture,
    so its writes need no pre-image and execute at once, inside the window."""
    c.must('FLUSHALL')
    c.must('DEBUG', 'SET-ACTIVE-EXPIRE', 0)
    pre, post = f'txnfix4:hash:{attempt}:pre', f'txnfix4:hash:{attempt}:post'
    if server.oracle:
        bigs = [f'txnfix4:big:{attempt}:{i}' for i in range(2)]
    else:
        shard = shards_of(c, [pre])[0][0]
        post = keys_on_shard(c, shard, f'txnfix4:hash:{attempt}:post', 1)[0]
        bigs = keys_on_shard(c, shard, f'txnfix4:big:{attempt}', 2)
    for big in bigs:
        c.must('SETRANGE', big, bigmb * 1024 * 1024 - 1, 'x')
    fields = ('f', 'v', 'n', '5', 'x', 'old', 'g', '10', 'keep', 'k')
    c.must('HSET', pre, *fields)
    c.must('HPEXPIRE', pre, lapse_ms, 'FIELDS', 4, 'f', 'n', 'x', 'g')
    require(c.must('BGSAVE') in (b'Background saving started', b'OK'), 'BGSAVE refused')
    c.must('HSET', post, *fields)
    c.must('HPEXPIRE', post, lapse_ms // 2, 'FIELDS', 4, 'f', 'n', 'x', 'g')
    deadline = max(c.must('HPEXPIRETIME', key, 'FIELDS', 1, 'f')[0] for key in (pre, post))
    # Wait past both deadlines inside the capture (owner clocks are per pass, hence the margin);
    # a capture that ended first is a miss and is re-rolled.
    while server_ms(c) <= deadline + 10:
        time.sleep(0.001)
    opened = info_fields(c, 'persistence')['rdb_bgsave_in_progress'] == '1'
    reads = {'post': hash_reads(c, post), 'pre': hash_reads(c, pre)}
    writes = {'post': hash_writes(c, post)}
    still = info_fields(c, 'persistence')['rdb_bgsave_in_progress'] == '1'
    writes['pre'] = hash_writes(c, pre)
    for _ in range(1200):
        if info_fields(c, 'persistence')['rdb_bgsave_in_progress'] == '0':
            break
        time.sleep(0.05)
    status = info_fields(c, 'persistence')['rdb_last_bgsave_status']
    after = {'post': hash_after(c, post), 'pre': hash_after(c, pre)}
    for big in bigs:
        c.must('DEL', big)
    c.must('DEBUG', 'SET-ACTIVE-EXPIRE', 1)
    window = opened and still
    want_reads = dict(hget=None, hmget=[None, b'k'], hexists=0, hstrlen=0,
                      hgetall=[b'keep', b'k'], hkeys=[b'keep'], hvals=[b'k'],
                      hscan=[b'0', [b'keep', b'k']], hrandfield=[b'keep'] * 5, hlen=1,
                      httl=[-2, -1])
    if server.oracle:
        # Redis HLEN counts lapsed fields not yet reclaimed (known CD4.13 difference).
        want_reads.pop('hlen')
    want_writes = dict(hincrby=1, hincrbyfloat=b'1.5', hsetnx=1, hpttl=[-1])
    want_after = dict(hgetall={'keep': 'k', 'n': '1', 'x': 'new', 'g': '1.5'},
                      hlen=4, hget_f=None, hpttl=[-1, -1, -1])
    wrong = {}
    for which in ('post', 'pre'):
        wrong.update({f'{which}_{k}': v for k, v in reads[which].items()
                      if k in want_reads and v != want_reads[k]})
        wrong.update({f'{which}_{k}': v for k, v in writes[which].items() if v != want_writes[k]})
        wrong.update({f'{which}_after_{k}': v for k, v in after[which].items()
                      if v != want_after[k]})
    if status != 'ok':
        wrong['rdb_last_bgsave_status'] = status
    emit(case='CD5.3', attempt=attempt, keys=[pre, post], bigs=bigs, bigmb=bigmb,
         lapse_ms=lapse_ms, deadline=deadline, capture_open_at_deadline=opened,
         capture_open_after_post_writes=still, reads=reads, writes=writes, after=after,
         wrong=wrong, window=window, passed=window and not wrong)
    return window, wrong


def case_hash(c, server, leg, emit):
    for attempt, (bigmb, lapse) in enumerate(((128, 100), (192, 120), (256, 150))):
        window, wrong = capture_attempt(c, server, attempt, emit, bigmb, lapse)
        if wrong or window:
            return 1, [f'attempt {attempt}: {sorted(wrong)}'] if wrong else []
    return 1, ['no attempt kept the hash shard captured past the field deadline']


# ---- TM5.1: execfix two-owner geometry ----------------------------------------------------------

def load_execfix(host, port):
    path = ROOT / 'tests/execfix.py'
    spec = importlib.util.spec_from_file_location('txnfix4_execfix', path)
    module = importlib.util.module_from_spec(spec)
    saved = sys.argv
    try:
        sys.argv = [str(path), host, str(port)]
        spec.loader.exec_module(module)
    finally:
        sys.argv = saved
    return module


class PlantedGeometry:
    """Serverless DEBUG SHARD(S) answers: sixteen shards, all on one owner or on two owners."""

    def __init__(self, owners):
        self.owners = owners

    def command(self, *args):
        def shard(key):
            return sum(key.encode()) % 16
        if args[:2] == ('DEBUG', 'SHARD'):
            return shard(args[2])
        if args[:2] == ('DEBUG', 'SHARDS'):
            return [[shard(key), 6 + shard(key) % self.owners] for key in args[2:]]
        raise AssertionError(f'planted geometry received {args!r}')


def planted(helper):
    """'refused' when the helper rejects a planted single-owner placement."""
    try:
        selected = helper(PlantedGeometry(1))
    except AssertionError:
        return 'refused'
    except Exception as error:  # noqa: BLE001 - a missing helper is a failed witness
        return f'{type(error).__name__}: {error}'
    return f'accepted {selected!r}'[:300]


def case_placement(c, server, leg, emit):
    execfix = load_execfix('127.0.0.1', server.port)
    controls = {
        'two_owner_keys': planted(lambda g: execfix.two_owner_keys(g, 'planted')),
        'two_owner_keys/3': planted(lambda g: execfix.two_owner_keys(g, 'planted', 3)),
        'loss-arm final names': planted(
            lambda g: execfix.owner_pairs(g, 'planted:list', execfix.ROUNDS)),
    }
    failures = [f'planted single owner: {name}: {verdict}'
                for name, verdict in controls.items() if verdict != 'refused']
    selftest = subprocess.run([sys.executable, str(ROOT / 'tests/execfix.py'), '--self-test'],
                              capture_output=True, text=True, timeout=120)
    if selftest.returncode:
        failures.append('execfix --self-test: ' + (selftest.stdout + selftest.stderr)[-300:])
    selections, same, pairs = {}, [], []
    conn = execfix.Conn()
    try:
        for count in (2, 3):
            keys = execfix.two_owner_keys(conn, f'tm51:{count}', count)
            rows = shards_of(c, keys)
            selections[f'two_owner_keys/{count}'] = (keys, rows)
            if len({row[1] for row in rows}) < 2 or len({row[0] for row in rows}) != count:
                failures.append(f'two_owner_keys({count}) {keys} {rows}')
        if hasattr(execfix, 'owner_pairs'):
            pairs = execfix.owner_pairs(conn, 'tm51:loss:list', execfix.ROUNDS)
            rows = shards_of(c, [k for pair in pairs for k in pair])
            same = [pairs[i // 2] for i in range(0, len(rows), 2) if rows[i][1] == rows[i + 1][1]]
            if len(pairs) != execfix.ROUNDS or same:
                failures.append(f'loss-arm pairs on one owner: {same[:3]}')
    finally:
        conn.close()
    emit(case='TM5.1', planted_single_owner=controls,
         selftest=(selftest.stdout + selftest.stderr).strip().splitlines()[-3:],
         selections=selections, loss_pairs=len(pairs), loss_pairs_one_owner=len(same),
         passed=not failures)
    return len(controls) + 3, failures


# ---- driver -------------------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--case', choices=('oom', 'watch', 'crash', 'hash', 'placement'), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--iterations', type=int, default=200)
    p.add_argument('--legs', default='all', help='comma-separated leg indices (diagnostics)')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__), ROOT / 'tests/execfix.py', ROOT / 'tests/_lib.py']
    (a.output / 'witness.json').write_text(json.dumps(dict(
        case=a.case, engine=a.engine, cores=a.cores, port=a.port, iterations=a.iterations,
        binary=str(Path(a.binary).resolve()),
        binary_sha256=hashlib.sha256(Path(a.binary).read_bytes()).hexdigest(),
        oracle_sha256=hashlib.sha256(Path(a.oracle).read_bytes()).hexdigest(),
        sources={str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in sources}), indent=2) + '\n')
    legs = [(f'tomo-{m}-a{at}-db{db}-rl{rl}', False, (m, at, db, rl))
            for m, at, db, rl in LEGS]
    if a.legs != 'all':
        legs = [legs[int(i)] for i in a.legs.split(',')]
    if a.case != 'placement':
        legs.append(('redis74', True, ('-', 0, 16, 0)))
    results, total_failures = [], 0
    for label, oracle, leg in legs:
        log_path = a.output / f'{label}.jsonl'
        started = time.monotonic()
        failures, checks = [], 0
        with log_path.open('w') as log:
            def emit(**values):
                log.write(json.dumps(values, default=repr, sort_keys=True) + '\n')
                log.flush()
            try:
                mode, atomic, databases, read_local = leg
                with Server(a, label, oracle, mode, atomic, databases, read_local) as server:
                    with contextlib.closing(server.connect()) as c:
                        if a.case == 'oom':
                            checks, failures = case_oom(c, server, leg, emit)
                        elif a.case == 'watch':
                            checks, failures = case_watch(c, server, leg, emit)
                        elif a.case == 'crash':
                            checks, failures = case_crash(c, server, leg, emit,
                                                          2 if oracle else a.iterations)
                        elif a.case == 'hash':
                            checks, failures = case_hash(c, server, leg, emit)
                        else:
                            checks, failures = case_placement(c, server, leg, emit)
            except Exception as error:  # noqa: BLE001 - every leg must leave its own receipt
                failures = failures + [f'{type(error).__name__}: {error}']
                emit(event='exception', traceback=traceback.format_exc())
            emit(event='summary', label=label, checks=checks, failures=failures,
                 seconds=round(time.monotonic() - started, 3), passed=not failures)
        results.append(dict(label=label, checks=checks, failures=failures, passed=not failures))
        total_failures += bool(failures)
        print(label, 'PASS' if not failures else 'FAIL', checks, '; '.join(failures)[:2000],
              flush=True)
        (a.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'txnfix4 {a.case}: {len(results) - total_failures}/{len(results)} legs passed', flush=True)
    return 1 if total_failures else 0


if __name__ == '__main__':
    sys.exit(main())
