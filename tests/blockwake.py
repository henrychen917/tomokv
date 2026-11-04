#!/usr/bin/env python3
"""blockwake: blocking-registry defects and their wakes. Correctness rows; no rates.

One invocation runs one CASE on fresh servers in one --mode/--engine leg:

  cancel   F6a. A push must never be served to a waiter whose client was already killed or
           unblocked. The owner is kept busy (two pipelined INCR hogs on its keys) so that its
           blocking sweep -- the only place PRE honours a cancel -- runs on its 10 ms beat, and
           the push reaches service() first. Every trial: W blocks; C kills or unblocks W and gets
           its reply; C pushes one element; 20 ms later the element must still be in the key
           (Redis 7.4 keeps it: CLIENT KILL frees the client before replying), and an unblocked
           W must receive the unblock reply, not the element. Variants cover BLPOP, BZPOPMIN,
           BLMOVE (the element must not move to the dead worker's destination) and XREADGROUP
           (the entry must not enter the dead consumer's PEL). The same trial loop runs against
           the Redis 7.4 oracle, which must show no deviation either.

No reply is retried. Every variant's anti-vacuity condition is printed with its verdict.
"""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import Conn, RespError, encode, info, topology, wait_ready  # noqa: E402
from _gate_process import stop_process  # noqa: E402


# ------------------------------------------------------------------------------------------------
# boots
# ------------------------------------------------------------------------------------------------

class Boot:
    """One owned server child (TomoKV in the gate geometry, or the Redis 7.4 oracle)."""

    def __init__(self, a, label, extra=(), redis=False):
        self.a, self.label, self.redis = a, label, redis
        self.directory = (a.output / label).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        listening = subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{a.port}'],
                                            text=True).strip()
        if listening:
            raise AssertionError(f'port {a.port} is already listening: {listening}')
        if redis:
            argv = ['taskset', '-c', a.cores, str(a.oracle), '--bind', '127.0.0.1',
                    '--port', str(a.port), '--save', '', '--appendonly', 'no',
                    '--dir', str(self.directory), '--enable-debug-command', 'yes']
        else:
            argv = ['taskset', '-c', a.cores, str(Path(a.binary).resolve()), '--bind', '127.0.0.1',
                    '--port', str(a.port), '--save', '', '--appendonly', 'no',
                    '--dir', str(self.directory), '--thread-mode', a.mode, '--shards', '16',
                    '--net-io', a.engine, '--enable-debug-command', 'yes', '--hz', '1',
                    '--dynamic-hz', 'no', '--key-lb', '0', '--client-lb', '0']
            if a.mode == '2s':
                argv += ['--ratio', a.ratio, '--flip-auto', '0']
        argv += list(extra)
        self.argv = argv
        (self.directory / 'argv.json').write_text(json.dumps(argv) + '\n')
        self.log = (self.directory / 'server.log').open('w')
        self.process = subprocess.Popen(argv, stdout=self.log, stderr=subprocess.STDOUT,
                                        env=dict(os.environ, LC_ALL='C'))
        self.admin = None
        self.exit = None

    def __enter__(self):
        try:
            self.admin = wait_ready('127.0.0.1', self.a.port, process=self.process, timeout=60)
            if not self.redis:
                server = info(self.admin, 'server')
                want = dict(thread_mode=self.a.mode, net_io=self.a.engine, shards='16')
                for field, value in want.items():
                    if server.get(field) != value:
                        raise AssertionError(f'INFO server {field}={server.get(field)!r}, '
                                             f'wanted {value!r}')
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        if self.admin:
            self.admin.close()
        forced = stop_process(self.process)
        self.log.close()
        self.exit = dict(rc=self.process.returncode, forced=forced)
        return False

    def clean_exit(self):
        return self.exit is not None and not self.exit['forced'] and self.exit['rc'] == 0

    def conn(self, timeout=10):
        return Conn('127.0.0.1', self.a.port, timeout=timeout)


def io_thread(conn):
    reply = conn.must('DEBUG', 'IO-THREAD')
    if not isinstance(reply, int):
        raise AssertionError(f'DEBUG IO-THREAD returned {reply!r}')
    return reply


def keys_on(admin, prefix, want, owner=None, not_owner=None, shard=None, limit=200000):
    """`want` key names that DEBUG SHARDS places on the requested owner (or shard)."""
    found, index = [], 0
    while len(found) < want:
        if index >= limit:
            raise AssertionError(f'{prefix}: only {len(found)} of {want} keys in {limit} probes')
        names = [f'{prefix}:{i}' for i in range(index, index + 512)]
        index += 512
        for name, (sid, tid) in zip(names, admin.must('DEBUG', 'SHARDS', *names)):
            if owner is not None and tid != owner:
                continue
            if not_owner is not None and tid == not_owner:
                continue
            if shard is not None and sid != shard:
                continue
            found.append(name)
            if len(found) == want:
                break
    return found


def shard_owner(admin, key):
    (sid, tid), = admin.must('DEBUG', 'SHARDS', key)
    return sid, tid


def stat(conn, field, section='stats'):
    table = info(conn, section)
    if field not in table:
        raise AssertionError(f'INFO {section} has no {field}')
    return int(table[field])


def wait_flag(admin, client_id, flag='b', timeout=5.0):
    """Wait until CLIENT LIST shows `flag` for client_id (a Parked waiter shows flags=b)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = admin.must('CLIENT', 'LIST', 'ID', client_id)
        text = row.decode() if isinstance(row, bytes) else ''
        fields = dict(part.split('=', 1) for part in text.split() if '=' in part)
        if flag in fields.get('flags', ''):
            return True
        time.sleep(0.0005)
    raise AssertionError(f'client {client_id} never showed flags={flag}')


# ------------------------------------------------------------------------------------------------
# load: pipelined INCR hogs that keep one owner busy
# ------------------------------------------------------------------------------------------------

def mset8_frame(keys, depth):
    out = []
    for i in range(depth):
        args = ['MSET']
        for k in keys:
            args += [k, f'v{i}']
        out.append(encode(*args))
    return b''.join(out)


def hog(port, key, depth, stop, report, mset8_keys=None):
    try:
        conn = Conn('127.0.0.1', port, timeout=30)
        if mset8_keys is not None:
            frame = mset8_frame(mset8_keys, depth)
            expect = depth  # MSET replies +OK per command
        else:
            frame = encode('INCR', key) * depth
            expect = depth
        sent = done = 0
        conn.raw(frame)
        sent += depth
        while not stop.is_set():
            conn.raw(frame)
            sent += depth
            for _ in range(depth):
                reply = conn.read()
                if mset8_keys is None and not isinstance(reply, int):
                    raise AssertionError(f'INCR {key} returned {reply!r}')
            done += depth
        for _ in range(sent - done):
            conn.read()
            done += 1
        conn.close()
        report.send(dict(key=key, ops=done, expect=expect))
    except BaseException as error:
        report.send(dict(key=key, error=repr(error)))
    finally:
        report.close()


class Hogs:
    def __init__(self, port, keys, depth=128, mset8=None):
        context = multiprocessing.get_context('fork')
        self.stop = context.Event()
        self.children = []
        items = mset8 if mset8 is not None else [(k, None) for k in keys]
        for tag, keyset in items:
            parent, child = context.Pipe()
            proc = context.Process(target=hog, args=(port, tag, depth, self.stop, child, keyset))
            proc.start()
            child.close()
            self.children.append((proc, parent))

    def finish(self):
        self.stop.set()
        rows = []
        for proc, pipe in self.children:
            rows.append(pipe.recv() if pipe.poll(30) else dict(error='hog did not report'))
            proc.join(10)
        return rows


# ------------------------------------------------------------------------------------------------
# F6a: cancel
# ------------------------------------------------------------------------------------------------

CANCEL_VARIANTS = ('blpop-kill', 'blpop-unblock', 'blpop-unblock-error',
                   'bzpopmin-kill', 'blmove-kill', 'xreadgroup-kill')


def cancel_trial(boot, admin, variant, keys, owner, trial):
    """One kill/unblock-then-push trial. Returns the deviations seen (empty: Redis behaviour)."""
    key, aux = keys
    deviations = []
    for _ in range(64):
        w = boot.conn(timeout=5)
        if owner is None or io_thread(w) != owner:
            break  # in 1s the waiter's own thread must not be the key's owner
        w.close()
    else:
        raise AssertionError('no waiter connection off the owner thread')
    wid = w.must('CLIENT', 'ID')
    if variant.startswith('xreadgroup'):
        admin.must('XGROUP', 'CREATE', key, 'g', '$', 'MKSTREAM')
        w.send('XREADGROUP', 'GROUP', 'g', 'c1', 'COUNT', '1', 'BLOCK', '0', 'STREAMS', key, '>')
    elif variant.startswith('bzpopmin'):
        w.send('BZPOPMIN', key, '0')
    elif variant.startswith('blmove'):
        w.send('BLMOVE', key, aux, 'LEFT', 'RIGHT', '0')
    else:
        w.send('BLPOP', key, '0')
    wait_flag(admin, wid)
    if variant.endswith('kill'):
        reply = admin.must('CLIENT', 'KILL', 'ID', wid)
    elif variant.endswith('unblock-error'):
        reply = admin.must('CLIENT', 'UNBLOCK', wid, 'ERROR')
    else:
        reply = admin.must('CLIENT', 'UNBLOCK', wid)
    if reply != 1:
        raise AssertionError(f'{variant}: kill/unblock replied {reply!r}')
    element = f'job:{trial}'
    if variant.startswith('xreadgroup'):
        pushed = admin.must('XADD', key, '*', 'f', element)
    elif variant.startswith('bzpopmin'):
        pushed = admin.must('ZADD', key, '1', element)
    else:
        pushed = admin.must('LPUSH', key, element)
    if not pushed:
        raise AssertionError(f'{variant}: push replied {pushed!r}')
    if variant.endswith('kill'):
        try:
            got = w.read()
            deviations.append(f'killed waiter received {got!r}')
        except (EOFError, ConnectionResetError, OSError):
            pass
    else:
        got = w.read()
        if variant.endswith('unblock-error'):
            if not (isinstance(got, RespError) and str(got).startswith('UNBLOCKED')):
                deviations.append(f'unblocked waiter received {got!r}, wanted -UNBLOCKED')
        elif got is not None:
            deviations.append(f'unblocked waiter received {got!r}, wanted nil')
    w.close()
    time.sleep(0.020)
    if variant.startswith('xreadgroup'):
        pending = admin.must('XPENDING', key, 'g')
        if not isinstance(pending, list) or pending[0] != 0:
            deviations.append(f'XPENDING {pending!r}: the entry entered a cancelled consumer PEL')
        if admin.must('XLEN', key) != 1:
            deviations.append('XLEN is not 1')
    elif variant.startswith('bzpopmin'):
        if admin.must('ZCARD', key) != 1:
            deviations.append('ZCARD is not 1: the element was popped for a cancelled waiter')
    else:
        left = admin.must('LLEN', key)
        if left != 1:
            deviations.append(f'LLEN {left}: the element was popped for a cancelled waiter')
        if variant.startswith('blmove') and admin.must('LLEN', aux) != 0:
            deviations.append('the element moved to a killed BLMOVE waiter destination')
    admin.must('DEL', key, aux)
    return deviations


def run_cancel(a, boot, redis):
    admin = boot.admin
    result = dict(target='redis' if redis else 'tomokv', trials=0, deviations=[], variants={})
    if redis:
        owner = None
        pool = [f'bw:q:{i}' for i in range(4 * a.trials)]
        hog_keys = ['bw:hog:0', 'bw:hog:1']
    else:
        # The waited key's owner; the hogs' keys live on the same owner.
        probe = keys_on(admin, 'bw:own', 1)[0]
        _, owner = shard_owner(admin, probe)
        pool = keys_on(admin, 'bw:q', 4 * a.trials, owner=owner)
        hog_keys = keys_on(admin, 'bw:hog', 2, owner=owner)
        result['owner'] = owner
    hogs = Hogs(a.port, hog_keys)
    try:
        time.sleep(0.2)
        for trial in range(a.trials):
            variant = CANCEL_VARIANTS[trial % len(CANCEL_VARIANTS)]
            keys = (pool[2 * trial], pool[2 * trial + 1])
            seen = cancel_trial(boot, admin, variant, keys, None if redis else owner, trial)
            row = result['variants'].setdefault(variant, dict(trials=0, deviating=0))
            row['trials'] += 1
            result['trials'] += 1
            if seen:
                row['deviating'] += 1
                if len(result['deviations']) < 24:
                    result['deviations'].append(dict(trial=trial, variant=variant, seen=seen))
    finally:
        result['hogs'] = hogs.finish()
    if any('error' in h for h in result['hogs']):
        raise AssertionError(f"hog failed: {result['hogs']}")
    return result


def case_cancel(a):
    legs = []
    with Boot(a, f'cancel-{a.mode}-{a.engine}') as boot:
        legs.append(run_cancel(a, boot, redis=False))
    legs[-1]['server_exit'] = boot.exit
    if a.oracle:
        with Boot(a, 'cancel-redis', redis=True) as boot:
            legs.append(run_cancel(a, boot, redis=True))
        legs[-1]['server_exit'] = boot.exit
    reasons = []
    for leg in legs:
        bad = sum(v['deviating'] for v in leg['variants'].values())
        if leg['trials'] != a.trials:
            reasons.append(f"{leg['target']}: {leg['trials']} of {a.trials} trials ran")
        if bad:
            reasons.append(f"{leg['target']}: {bad} of {leg['trials']} trials deviated from Redis")
        if leg['server_exit']['forced'] or leg['server_exit']['rc'] != 0:
            reasons.append(f"{leg['target']}: server exit {leg['server_exit']}")
    return dict(case='cancel', legs=legs, reasons=reasons)


# ------------------------------------------------------------------------------------------------
# F6b: a still-registering front waiter must not strand the parked waiters behind it
# ------------------------------------------------------------------------------------------------

def preload(conn, key, count):
    batch = 8192
    for start in range(0, count, batch):
        n = min(batch, count - start)
        conn.raw(encode('RPUSH', key, *[str((start + i) * 7919 % 1000003) for i in range(n)]))
        if not isinstance(conn.read(), int):
            raise AssertionError(f'RPUSH {key} failed')


def conns_off(boot, avoid, count):
    """`count` connections whose IO thread is not in `avoid` (an owner busy in a long command
    cannot parse for its own connections in 1s)."""
    out, extra = [], []
    for _ in range(64 * count):
        c = boot.conn(timeout=10)
        if io_thread(c) in avoid:
            extra.append(c)
            continue
        out.append(c)
        if len(out) == count:
            break
    for c in extra:
        c.close()
    if len(out) != count:
        raise AssertionError(f'could not place {count} connections off threads {avoid}')
    return out


def read_by(conn, deadline):
    """One reply, or None if nothing arrives by the monotonic deadline (the hang witness)."""
    left = deadline - time.monotonic()
    if left <= 0:
        return 'timeout', None
    conn.sock.settimeout(left)
    try:
        return 'reply', conn.read()
    except (socket.timeout, TimeoutError):
        return 'timeout', None


def strand_trial(boot, admin, k, m, big_a, big_b, conns, trial):
    pa, pb, w1, w2, w3 = conns
    for c in conns:
        c.sock.settimeout(10)
    record = dict(trial=trial)
    pa.send('SORT', big_a, 'LIMIT', '0', '1')        # A busy: W1's probe of k waits
    time.sleep(0.005)
    w1.send('BLPOP', k, m, '0')                      # B probes m at once
    time.sleep(0.005)
    t_b0 = time.monotonic()
    pb.send('SORT', big_b, 'LIMIT', '0', '1')        # B busy: W1's registration of m waits
    if not isinstance(pa.read(), list):
        raise AssertionError('SORT on A failed')
    time.sleep(0.020)                                # A probes k, then registers W1 on k
    for c, want in ((w2, 1), (w3, 2)):
        c.send('BLPOP', k, '0')
        deadline = time.monotonic() + 2
        while stat(admin, 'blocked_clients', 'clients') < want:
            if time.monotonic() > deadline:
                raise AssertionError(f'follower {want} never parked')
            time.sleep(0.0005)
    blocked = stat(admin, 'blocked_clients', 'clients')
    waiters = stat(admin, 'blocking_waiters')
    b_done = bool(select.select([pb.sock], [], [], 0)[0])
    pushed = admin.must('RPUSH', k, 'a', 'b', 'c')
    # The window: W1 has its k alias on A but is not parked (still registering on B, whose SORT
    # has not answered), and W2/W3 are parked behind it when the push lands.
    record.update(blocked_at_push=blocked, waiters_at_push=waiters, pushed=pushed,
                  b_done_before_push=b_done)
    if not isinstance(pb.read(), list):
        raise AssertionError('SORT on B failed')
    t_b1 = time.monotonic()
    record['b_busy_ms'] = round((t_b1 - t_b0) * 1000, 1)
    record['window_open'] = blocked == 2 and waiters == 3 and not b_done
    replies = {}
    for name, c in (('w1', w1), ('w2', w2), ('w3', w3)):
        kind, value = read_by(c, t_b1 + 0.5)
        replies[name] = dict(kind=kind, value=repr(value),
                             ms_after_b=round((time.monotonic() - t_b1) * 1000, 1))
    record['replies'] = replies
    record['llen'] = admin.must('LLEN', k)
    stranded = [n for n, r in replies.items() if r['kind'] == 'timeout']
    record['stranded'] = stranded
    return record, stranded


def case_strand(a):
    reasons, trials = [], []
    with Boot(a, f'strand-{a.mode}-{a.engine}') as boot:
        admin = boot.admin
        topo = topology(admin)
        owners = topo.owners
        if len(owners) < 2:
            raise AssertionError(f'need two owners, have {owners}')
        own_a, own_b = owners[0], owners[1]
        k_pool = keys_on(admin, 'bw:k', a.repeats * 4, owner=own_a)
        m = keys_on(admin, 'bw:m', 1, owner=own_b)[0]
        big_a = keys_on(admin, 'bw:bigA', 1, owner=own_a)[0]
        big_b = keys_on(admin, 'bw:bigB', 1, owner=own_b)[0]
        preload(admin, big_a, a.big_a)
        preload(admin, big_b, a.big_b)
        opened = attempts = 0
        # A window that did not open is re-rolled on a fresh key (bounded); every attempt is
        # still judged for correctness, and too few opened windows is a vacuous FAIL.
        while opened < a.repeats and attempts < a.repeats + 6:
            attempts += 1
            conns = conns_off(boot, {own_a, own_b}, 5)
            try:
                record, stranded = strand_trial(boot, admin, k_pool[attempts], m, big_a, big_b,
                                                conns, attempts)
                record.update(owner_a=own_a, owner_b=own_b)
                opened += record['window_open']
                trials.append(record)
                print(json.dumps(record), flush=True)
                if stranded:
                    reasons.append(f"trial {record['trial']}: {stranded} never served while "
                                   f"LLEN={record['llen']} (the key holds data)")
                elif record['llen'] != 0:
                    reasons.append(f"trial {record['trial']}: LLEN {record['llen']} after serving")
                elif "b'a'" not in record['replies']['w1']['value']:
                    reasons.append(f"trial {record['trial']}: W1 got "
                                   f"{record['replies']['w1']['value']}, wanted the first element")
            finally:
                for c in conns:
                    c.close()
                # Release whatever a PRE hang left blocked before the next attempt.
                listing = admin.must('CLIENT', 'LIST', 'TYPE', 'normal').decode()
                for row in listing.splitlines():
                    fields = dict(p.split('=', 1) for p in row.split() if '=' in p)
                    if 'b' in fields.get('flags', ''):
                        admin.must('CLIENT', 'UNBLOCK', fields['id'])
                admin.must('DEL', k_pool[attempts])
    if opened < a.repeats:
        reasons.append(f'vacuous: the registering window opened in {opened} of {attempts} attempts')
    if not boot.clean_exit():
        reasons.append(f'server exit {boot.exit}')
    return dict(case='strand', trials=trials, reasons=reasons, server_exit=boot.exit)


# ------------------------------------------------------------------------------------------------
# F8: a resumed BLMOVE refused by the saturated atomic window must be rung by the credit doorbell
# ------------------------------------------------------------------------------------------------

def case_f8(a):
    reasons, rounds = [], []
    with Boot(a, f'f8-{a.mode}-{a.engine}', extra=['--atomic', '1']) as boot:
        admin = boot.admin
        topo = topology(admin)
        io_threads = sorted(t for t, role in topo.roles.items()
                            if role == ('fused' if a.mode == '1s' else 'io'))
        if len(io_threads) < 2:
            raise AssertionError(f'need two IO threads: {topo.roles}')
        # One probe connection alone on an IO thread; MSET8 hogs on every other IO thread keep the
        # 256-credit window saturated so the woken BLMOVE's resume is refused (Backpressure).
        probe_io = io_threads[0]
        probe = None
        for _ in range(200):
            c = boot.conn()
            if io_thread(c) == probe_io:
                probe = c
                break
            c.close()
        if probe is None:
            raise AssertionError('no probe connection on the chosen IO thread')
        feeder = boot.conn()
        # src and dst on two different owners so the resumed move is a cross-shard atomic group.
        src = keys_on(admin, 'bw:src', 1, owner=topo.owners[0])[0]
        dst = keys_on(admin, 'bw:dst', 1, owner=topo.owners[1])[0]
        # eight distinct-shard keys per hog group -> every MSET8 is an admitted cross-shard group.
        hog_sets = []
        for g in range(a.hogs * (len(io_threads) - 1)):
            ks, shards, i = [], set(), 0
            while len(ks) < 8:
                name = f'bw:hog:{g}:{i}'; i += 1
                sid, _ = shard_owner(admin, name)
                if sid not in shards:
                    shards.add(sid); ks.append(name)
            hog_sets.append((f'hog{g}', ks))
        hogs = Hogs(a.port, [], depth=32, mset8=hog_sets)
        try:
            time.sleep(0.3)
            before = stat(admin, 'atomic_window_stalls')
            for r in range(a.rounds):
                admin.must('DEL', src, dst)
                probe.send('BLMOVE', src, dst, 'LEFT', 'RIGHT', '0')
                deadline = time.monotonic() + 2
                while stat(admin, 'blocked_clients', 'clients') < 1:
                    if time.monotonic() > deadline:
                        raise AssertionError('BLMOVE never blocked')
                    time.sleep(0.0005)
                t0 = time.monotonic()
                feeder.must('LPUSH', src, f'e{r}')
                probe.sock.settimeout(2)
                reply = probe.read()
                dt_ms = (time.monotonic() - t0) * 1000
                rounds.append(dict(round=r, ms=round(dt_ms, 2), reply=repr(reply)))
                if reply != b'e' + str(r).encode() and reply != f'e{r}'.encode():
                    reasons.append(f'round {r}: BLMOVE returned {reply!r}')
                if dt_ms >= a.max_ms:
                    reasons.append(f'round {r}: BLMOVE wake {dt_ms:.1f} ms >= {a.max_ms} ms')
            after = stat(admin, 'atomic_window_stalls')
            stalls = after - before
            if stalls <= 0:
                reasons.append('vacuous: atomic_window_stalls did not grow (window never refused)')
        finally:
            hog_rows = hogs.finish()
            probe.close(); feeder.close()
        slow = sorted(rounds, key=lambda r: -r['ms'])[:8]
        print(json.dumps(dict(stalls=after - before, max_ms=max(r['ms'] for r in rounds),
                              ge_max=sum(r['ms'] >= a.max_ms for r in rounds), slow=slow)), flush=True)
    if not boot.clean_exit():
        reasons.append(f'server exit {boot.exit}')
    return dict(case='f8', rounds=rounds, window_stalls=after - before,
                max_ms=max(r['ms'] for r in rounds) if rounds else None, reasons=reasons)


CASES = dict(cancel=case_cancel, strand=case_strand, f8=case_f8)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('case', choices=tuple(CASES))
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--oracle', type=Path, help='Redis 7.4 redis-server (cancel compares with it)')
    p.add_argument('--cores', required=True, help="server CPUs (the slot's eight)")
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--engine', choices=('uring', 'epoll'), required=True)
    p.add_argument('--trials', type=int, default=204)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--big-a', type=int, default=150000, help='list length whose SORT stalls A')
    p.add_argument('--big-b', type=int, default=1000000, help='list length whose SORT stalls B')
    p.add_argument('--rounds', type=int, default=120, help='f8 BLMOVE wake rounds')
    p.add_argument('--hogs', type=int, default=4, help='f8 MSET8 hogs per non-probe IO thread')
    p.add_argument('--max-ms', type=float, default=20.0, help='f8 wake-latency bound')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert 1024 <= a.port < 32768
    os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=True)
    try:
        result = CASES[a.case](a)
    except BaseException:
        result = dict(case=a.case, reasons=['error: ' + traceback.format_exc()])
    result.update(mode=a.mode, engine=a.engine, binary=str(a.binary),
                  passed=not result['reasons'])
    (a.output / f'{a.case}-{a.mode}-{a.engine}.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(case=a.case, mode=a.mode, engine=a.engine, passed=result['passed'],
                          reasons=result['reasons'])), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
