#!/usr/bin/env python3
"""Directed maxmemrace row: CONFIG SET maxmemory reaches every owner before its +OK.

Redis 7.4 admits every command issued after `CONFIG SET maxmemory <n>` replies +OK under
the new limit. The publishing owner (the owner of shard 0) applies a live config at its next
pass boundary, so the pass that executes its own CONFIG fragment keeps the old limit. This
row keeps that owner X inside one long drain while the CONFIG completes, then issues SET on
the connection that received the +OK:

  1. b1 pipelines 20 `LPOS big <last>` scans of a list on shard 0 (occupies X);
  2. a, on an IO thread that is not X, sends CONFIG SET maxmemory <new>;
  3. b2, on a's IO thread, pipelines 60 more scans; they queue behind the CONFIG fragments
     in the same producer channel, so X executes the fragments mid-drain;
  4. a reads +OK and immediately sends SET of a key on another of X's shards.

A third connection on a's IO thread pipelines PINGs (IO-local) throughout, so that thread
polls its completions instead of parking until X's end-of-pass submit wakes it.

Cases: lift 1 -> 0 under noeviction and allkeys-lru (the SET must be admitted) and tighten
0 -> 1 under noeviction (the SET must be refused with OOM). CONCURRENT-CONVERGENCE races
two clients' conflicting CONFIG SET maxmemory pipelines from different IO threads, then
requires a SET on every shard to admit or refuse exactly as CONFIG GET's final value says.

Non-vacuity, required on every candidate trial: X still owed scan replies after the SET was
written (the SET entered its channel while X was inside the busy drain), and every scan found
the list. Shard 0 carries 6000 padding keys and the settle directly precedes step 1, so the
old allkeys-lru limit rarely evicts the list first. A trial whose window did not open is
re-armed on fresh state, at most three attempts; the assertion is never relaxed and a trial
that never opens its window fails the leg. Candidate legs: 1s/2s x uring/epoll x atomic 0/1 x read-local
0/1 x databases 1/16, plus the fused shadow scheduler (--reorder 1) for every 1s product.
The Redis oracle runs the same wire sequence without geometry (its allkeys-lru limit may evict the list; that is not asserted there).
No rates or latencies are asserted.
"""
import argparse
import contextlib
import itertools
import json
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

OOM = b"-OOM command not allowed when used memory > 'maxmemory'."
LIST_LENGTH = 20000
PAD_KEYS = 6000
ARMING_ATTEMPTS = 3
OCCUPY_FIRST = 20
OCCUPY_TASKS = 60
CASES = ('LIFT-NOEVICTION', 'LIFT-ALLKEYS-LRU', 'TIGHTEN-NOEVICTION', 'CONCURRENT-CONVERGENCE')
RACE_SETS = 100


def encode(*args):
    out = [b'*%d\r\n' % len(args)]
    for arg in args:
        arg = arg if isinstance(arg, bytes) else str(arg).encode()
        out.append(b'$%d\r\n%s\r\n' % (len(arg), arg))
    return b''.join(out)


class Conn:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=20)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b''

    def close(self):
        self.sock.close()

    def send(self, *frames):
        self.sock.sendall(b''.join(frames))

    def _fill(self):
        data = self.sock.recv(1 << 16)
        if not data:
            raise EOFError('server closed the connection')
        self.buf += data

    def read(self):
        while b'\r\n' not in self.buf:
            self._fill()
        line, self.buf = self.buf.split(b'\r\n', 1)
        tag = line[:1]
        if tag in (b'+', b'-'):
            return line
        if tag == b':':
            return int(line[1:])
        if tag == b'_':
            return None
        if tag == b'$':
            n = int(line[1:])
            if n < 0:
                return None
            while len(self.buf) < n + 2:
                self._fill()
            value, self.buf = self.buf[:n], self.buf[n + 2:]
            return value
        if tag == b'*':
            n = int(line[1:])
            return None if n < 0 else [self.read() for _ in range(n)]
        raise ValueError(line)

    def cmd(self, *args):
        self.send(encode(*args))
        return self.read()


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


@contextlib.contextmanager
def server(argv, cores, port, directory):
    assert not port_open(port), f'port {port} already accepts connections'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'argv.json').write_text(json.dumps(argv) + '\n')
    env = dict(os.environ, LC_ALL='C')
    with (directory / 'server.log').open('w') as log:
        proc = subprocess.Popen(['taskset', '-c', cores, *argv], stdout=log,
                                stderr=subprocess.STDOUT, env=env)
    try:
        deadline = time.monotonic() + 30
        while not port_open(port):
            assert proc.poll() is None, (directory / 'server.log').read_text()[-2000:]
            assert time.monotonic() < deadline, 'server never listened'
            time.sleep(0.02)
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        deadline = time.monotonic() + 5
        while port_open(port) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not port_open(port), f'port {port} still accepts after stop'


class Geometry:
    """Keys and connections for the recipe, proved on this boot (arbitrary for Redis)."""

    def __init__(self, port, oracle, transcript):
        self.port, self.oracle = port, oracle
        self.conns = []
        self.ctl = self.connect()
        if oracle:
            self.owner = self.io = None
            self.big, self.witness = 'mmr:big', 'mmr:witness'
            self.pads = [f'mmr:pad:{i}' for i in range(PAD_KEYS)]
            self.a, self.b2, self.b1 = self.connect(), self.connect(), self.ctl
            self.keeper = self.connect()
            self.shard_keys = [f'mmr:probe:{i}' for i in range(16)]
            self.racers = (self.connect(), self.connect())
            return
        keys = [f'mmr:{i}' for i in range(131072)]
        placement = {}
        for base in range(0, len(keys), 4096):
            rows = self.ctl.cmd('DEBUG', 'SHARDS', *keys[base:base + 4096])
            assert isinstance(rows, list), rows
            for key, (sid, worker) in zip(keys[base:base + 4096], rows):
                placement[key] = (sid, worker)
        owner = {sid: worker for sid, worker in placement.values()}
        self.owner = owner[0]
        x_shards = sorted(sid for sid, worker in owner.items() if worker == self.owner)
        shard0 = [k for k, (sid, _) in placement.items() if sid == 0]
        assert len(shard0) > PAD_KEYS + 1, len(shard0)
        self.big, self.pads = shard0[0], shard0[1:1 + PAD_KEYS]
        # Prefer another of X's shards, so the witness is not the shard being scanned.
        others = [k for k, (sid, _) in placement.items() if sid in x_shards and sid != 0]
        self.witness = others[0] if others else shard0[-1]
        by_io = {}
        for _ in range(96):
            c = self.connect()
            io = c.cmd('DEBUG', 'IO-THREAD')
            assert isinstance(io, int), io
            by_io.setdefault(io, []).append(c)
        # A fused X cannot parse while its own owner turn runs, so a/b2 share another IO.
        choice = sorted((io for io, cs in by_io.items() if len(cs) >= 3 and io != self.owner),
                        key=lambda io: (-len(by_io[io]), io))
        assert choice, ('no IO thread with three connections apart from the shard-0 owner',
                        sorted(by_io))
        self.io = choice[0]
        self.a, self.b2, self.keeper = by_io[self.io][:3]
        self.b1 = self.ctl
        # One key on every shard, and two racing connections on two different IO threads.
        firsts = {}
        for key, (sid, _) in placement.items():
            firsts.setdefault(sid, key)
        self.shard_keys = [firsts[sid] for sid in sorted(firsts)]
        ios = sorted(io for io in by_io if io != self.io)
        self.racers = (by_io[ios[0]][0], by_io[ios[-1]][-1])
        transcript.append(dict(geometry=dict(
            shard0_owner=self.owner, owner_shards=x_shards, big=self.big, witness=self.witness,
            witness_shard=placement[self.witness][0], ab2_io_thread=self.io,
            b1_io_thread=self.ctl.cmd('DEBUG', 'IO-THREAD'))))

    def connect(self):
        c = Conn(self.port)
        self.conns.append(c)
        return c

    def close(self):
        for c in self.conns:
            c.close()


def prepare(g, policy):
    """maxmemory 0, policy, non-empty shards, the scanned list and shard-0 padding."""
    assert g.ctl.cmd('CONFIG', 'SET', 'maxmemory', '0') == b'+OK'
    assert g.ctl.cmd('CONFIG', 'SET', 'maxmemory-policy', policy) == b'+OK'
    frames = [encode('SET', f'mmr:fill:{i}', 'v' * 64) for i in range(256)]
    frames += [encode('SET', key, 'p') for key in g.pads]
    g.ctl.send(*frames)
    for _ in frames:
        assert g.ctl.read() == b'+OK'
    assert g.ctl.cmd('DEL', g.big) in (0, 1)
    for base in range(0, LIST_LENGTH, 1000):
        g.ctl.send(encode('RPUSH', g.big, *range(base, base + 1000)))
    for base in range(0, LIST_LENGTH, 1000):
        assert g.ctl.read() == base + 1000


def settle(g, maxmemory, transcript):
    """Apply the old limit and prove it on X's witness shard before the trial."""
    assert g.ctl.cmd('CONFIG', 'SET', 'maxmemory', maxmemory) == b'+OK'
    # The SET is itself an X task, so X has crossed a pass boundary after the commit.
    reply = g.ctl.cmd('SET', g.witness, 'settle')
    want = b'+OK' if maxmemory == '0' else OOM
    if g.oracle and maxmemory == '1':
        policy = g.ctl.cmd('CONFIG', 'GET', 'maxmemory-policy')
        if policy == [b'maxmemory-policy', b'allkeys-lru']:
            # Redis 7.4 performEvictions() may return EVICT_RUNNING. Only
            # EVICT_FAIL rejects DENYOOM commands, so +OK is legal while the
            # incremental eviction cycle still has keys. Wait for its end;
            # candidate setup and the post-CONFIG assertion stay strict.
            deadline = time.monotonic() + 5
            admitted = 0
            while reply == b'+OK' and time.monotonic() < deadline:
                admitted += 1
                time.sleep(.001)
                reply = g.ctl.cmd('SET', g.witness, 'settle')
            transcript.append(dict(setup='Redis incremental allkeys-lru eviction',
                                   admitted_while_evicting=admitted,
                                   final_reply=reply.decode(errors='replace')))
    assert reply == want, ('settled limit not in effect', maxmemory, reply)


def convergence(g, transcript):
    """Two clients race conflicting CONFIG SETs; afterwards CONFIG GET and every shard agree."""
    assert g.ctl.cmd('CONFIG', 'SET', 'maxmemory', '0') == b'+OK'
    assert g.ctl.cmd('CONFIG', 'SET', 'maxmemory-policy', 'noeviction') == b'+OK'
    g.ctl.send(*[encode('SET', key, 'v') for key in g.shard_keys])
    for _ in g.shard_keys:
        assert g.ctl.read() == b'+OK'
    first, second = g.racers
    first.send(*[encode('CONFIG', 'SET', 'maxmemory', ('0', '1')[i & 1]) for i in range(RACE_SETS)])
    second.send(*[encode('CONFIG', 'SET', 'maxmemory', ('1', '0')[i & 1]) for i in range(RACE_SETS)])
    replies = [first.read() for _ in range(RACE_SETS)] + [second.read() for _ in range(RACE_SETS)]
    final = g.ctl.cmd('CONFIG', 'GET', 'maxmemory')
    assert isinstance(final, list) and len(final) == 2, final
    value = final[1].decode()
    want = b'+OK' if value == '0' else OOM
    # Every shard's owner must refuse or admit according to the value CONFIG GET reports.
    g.ctl.send(*[encode('SET', key, 'w') for key in g.shard_keys])
    got = [g.ctl.read() for _ in g.shard_keys]
    record = dict(case='CONCURRENT-CONVERGENCE', policy='noeviction', race_sets=2 * RACE_SETS,
                  config_replies_ok=sum(1 for r in replies if r == b'+OK'), final_maxmemory=value,
                  shard_replies={k: r.decode(errors='replace') for k, r in zip(g.shard_keys, got)},
                  mismatched=[k for k, r in zip(g.shard_keys, got) if r != want])
    record['window_open'] = True     # no window: a convergence property, asserted on every leg
    record['passed'] = record['config_replies_ok'] == 2 * RACE_SETS and not record['mismatched']
    transcript.append(record)
    return record


def trial(g, case, transcript):
    if case == 'CONCURRENT-CONVERGENCE':
        return convergence(g, transcript)
    policy = 'allkeys-lru' if case == 'LIFT-ALLKEYS-LRU' else 'noeviction'
    old, new = ('0', '1') if case.startswith('TIGHTEN') else ('1', '0')
    prepare(g, policy)
    scan = encode('LPOS', g.big, LIST_LENGTH - 1)
    # A parked IO thread is woken by X's message only when X submits at its pass end, which
    # would hold the +OK until X left the drain. Keep a's IO thread polling with IO-local PINGs.
    stop = threading.Event()
    pings = [0]

    def keep_awake():
        frame = encode('PING') * 32
        while not stop.is_set():
            g.keeper.send(frame)
            for _ in range(32):
                assert g.keeper.read() == b'+PONG'
            pings[0] += 32

    keeper = threading.Thread(target=keep_awake, daemon=True)
    keeper.start()
    time.sleep(0.002)
    try:
        # Settle last: under allkeys-lru the old limit starts evicting shard 0 at once, so the
        # occupation follows the settle's proof directly.
        settle(g, old, transcript)
        t0 = time.monotonic()
        g.b1.send(*([scan] * OCCUPY_FIRST))                    # occupy the shard-0 owner
        time.sleep(0.001)
        g.a.send(encode('CONFIG', 'SET', 'maxmemory', new))
        time.sleep(0.0005)
        g.b2.send(*([scan] * OCCUPY_TASKS))                    # behind the fragments, same IO
        config_reply = g.a.read()
        t_ok = time.monotonic()
        g.a.send(encode('SET', g.witness, 'after-ok'))
        t_sent = time.monotonic()
        # Every reply here is one line (+OK, -OOM ..., :n, $-1/_). Read by readiness so the
        # arrival order is observed rather than imposed by the reader.
        names = {g.b1.sock: 'b1', g.b2.sock: 'b2', g.a.sock: 'a'}
        conns = {'b1': g.b1, 'b2': g.b2, 'a': g.a}
        pending = {'b1': OCCUPY_FIRST, 'b2': OCCUPY_TASKS, 'a': 1}
        replies = {'b1': [], 'b2': [], 'a': []}
        events = []
        while any(pending.values()):
            for n, c in conns.items():
                while pending[n] and b'\r\n' in c.buf:
                    line, c.buf = c.buf.split(b'\r\n', 1)
                    replies[n].append(line)
                    pending[n] -= 1
                    events.append((n, time.monotonic()))
            if not any(pending.values()):
                break
            readable, _, _ = select.select([c.sock for n, c in conns.items() if pending[n]], [], [], 30)
            assert readable, ('reply timeout', pending)
            for sock in readable:
                data = sock.recv(1 << 16)
                assert data, 'server closed the connection'
                conns[names[sock]].buf += data
    finally:
        stop.set()
        keeper.join(30)
    assert not keeper.is_alive(), 'keeper did not stop'
    set_reply = replies['a'][0]
    want = OOM if case.startswith('TIGHTEN') else b'+OK'
    ms = lambda t: round((t - t0) * 1000, 3)
    found = b':%d' % (LIST_LENGTH - 1)
    record = dict(case=case, policy=policy, transition=f'{old}->{new}',
                  config_reply=config_reply.decode(errors='replace'), ok_ms=ms(t_ok),
                  set_sent_ms=ms(t_sent), set_reply=set_reply.decode(errors='replace'),
                  expected=want.decode(), set_reply_ms=ms(next(t for n, t in events if n == 'a')),
                  last_scan_ms=ms(max(t for n, t in events if n != 'a')),
                  b1_last_ms=ms(max(t for n, t in events if n == 'b1')),
                  b2_first_ms=ms(min(t for n, t in events if n == 'b2')),
                  b2_replies_after_set_sent=sum(1 for n, t in events if n == 'b2' and t > t_sent),
                  scans_found=sum(1 for r in replies['b1'] + replies['b2'] if r == found),
                  keeper_pings=pings[0],
                  scan_other=sorted({r.decode(errors='replace')
                                     for r in replies['b1'] + replies['b2'] if r != found}))
    # Non-vacuity: X still owed scan replies after the SET was written, and every scan was real.
    record['window_open'] = (record['b2_replies_after_set_sent'] > 0 and
                             record['scans_found'] == OCCUPY_FIRST + OCCUPY_TASKS)
    record['passed'] = config_reply == b'+OK' and set_reply == want
    transcript.append(record)
    return record


def run_target(args, label, argv, oracle):
    directory = args.output / label
    transcript = []
    result = dict(label=label, argv=argv, oracle=oracle, trials=[])
    try:
        with server(argv, args.cores, args.port, directory):
            g = Geometry(args.port, oracle, transcript)
            try:
                for case in CASES:
                    for _ in range(args.trials):
                        # Re-arm on fresh state, bounded, when the window did not open (e.g. the
                        # old allkeys-lru limit evicted the scanned list first). The assertion is
                        # never relaxed; a trial that never opens its window fails the leg.
                        for attempt in range(1, ARMING_ATTEMPTS + 1):
                            record = trial(g, case, transcript)
                            record['attempt'] = attempt
                            if record['window_open']:
                                break
                            result.setdefault('rearmed', []).append(dict(case=case, attempt=attempt))
                        result['trials'].append(record)
            finally:
                g.close()
    except Exception:
        result['exception'] = traceback.format_exc()
    (directory / 'transcript.json').write_text(json.dumps(transcript, indent=1) + '\n')
    trials = result['trials']
    complete = 'exception' not in result and len(trials) == len(CASES) * args.trials
    result['complete'] = complete
    result['assertions_passed'] = complete and all(t['passed'] for t in trials)
    result['window_open'] = bool(trials) and all(t['window_open'] for t in trials)
    # A candidate leg that never held the owner busy proves nothing, in either direction.
    result['passed'] = result['assertions_passed'] and (oracle or result['window_open'])
    return result


def candidate_argv(args, mode, engine, atomic, read_local, databases, reorder, data):
    argv = [str(Path(args.binary).resolve()), '--port', str(args.port), '--bind', '127.0.0.1',
            '--shards', '16', '--save', '', '--appendonly', 'no', '--enable-debug-command', 'yes',
            '--dir', str(data), '--net-io', engine, '--atomic', str(atomic),
            '--read-local', str(read_local), '--databases', str(databases),
            '--key-lb', '0', '--client-lb', '0', '--reorder', str(reorder)]
    argv += ['--ratio', args.ratio] if mode == '2s' else ['--thread-mode', '1s']
    return argv


def geometries(args):
    """Every requested product; --reorder 1 (the fused shadow scheduler) only in 1s."""
    for mode, engine, atomic, read_local, databases, reorder in itertools.product(
            args.modes, args.engines, args.atomics, args.read_locals, args.databases, args.reorders):
        if reorder and mode != '1s':
            continue
        yield mode, engine, atomic, read_local, databases, reorder


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle')
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--trials', type=int, default=3)
    p.add_argument('--modes', nargs='+', default=['2s', '1s'])
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--atomics', nargs='+', type=int, default=[0, 1])
    p.add_argument('--read-locals', nargs='+', type=int, default=[0, 1])
    p.add_argument('--databases', nargs='+', type=int, default=[1, 16])
    p.add_argument('--reorders', nargs='+', type=int, default=[0, 1])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--expect-fail', action='store_true',
                   help='control mode: succeed only if the oracle passes and every candidate leg '
                        'fails an assertion with the window open on every trial')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    if args.oracle:
        data = args.output / 'oracle' / 'data'
        data.mkdir(parents=True, exist_ok=True)
        argv = [str(Path(args.oracle).resolve()), '--port', str(args.port), '--bind', '127.0.0.1',
                '--save', '', '--appendonly', 'no', '--dir', str(data)]
        results.append(run_target(args, 'oracle', argv, True))
    for mode, engine, atomic, read_local, databases, reorder in geometries(args):
        label = f'{mode}-{engine}-atomic{atomic}-rl{read_local}-db{databases}' + \
            ('-reorder1' if reorder else '')
        data = args.output / label / 'data'
        data.mkdir(parents=True, exist_ok=True)
        argv = candidate_argv(args, mode, engine, atomic, read_local, databases, reorder, data)
        results.append(run_target(args, label, argv, False))
    summary = dict(binary=str(Path(args.binary).resolve()), oracle=args.oracle, trials=args.trials,
                   cases=CASES, results=[{k: v for k, v in r.items() if k != 'trials'} | dict(
                       failed_trials=[t for t in r['trials'] if not t['passed']][:3])
                       for r in results])
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    for r in results:
        bad = sum(1 for t in r['trials'] if not t['passed'])
        closed = sum(1 for t in r['trials'] if not t['window_open'])
        print(f"{r['label']}: passed={r['passed']} assertion_failures={bad}/{len(r['trials'])} "
              f"window_closed={closed} rearmed={len(r.get('rearmed', []))}"
              + (' EXCEPTION' if 'exception' in r else ''), flush=True)
    oracle_ok = all(r['passed'] for r in results if r['oracle'])
    candidates = [r for r in results if not r['oracle']]
    if args.expect_fail:
        controls = all(r['complete'] and r['window_open'] and not r['assertions_passed']
                       for r in candidates)
        return 0 if oracle_ok and controls and candidates else 1
    return 0 if oracle_ok and candidates and all(r['passed'] for r in candidates) else 1


if __name__ == '__main__':
    sys.exit(main())
