#!/usr/bin/env python3
"""Strict PS4.1-.5/.7-.9 regressions, adapted from round4-read/tests/persist.

Each invocation owns its processes and fresh data. No shared audit paths/binaries.
Timing receipts include host load and per-CPU activity; --observe records timing
without applying the gate's latency assertion (never used by a gate row).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import statistics
import struct
import subprocess
import threading
import time


def cpus(text):
    result = []
    for part in text.split(','):
        lo, _, hi = part.partition('-')
        result.extend(range(int(lo), int(hi or lo) + 1))
    return result


def clean(value):
    if isinstance(value, bytes):
        return value.decode(errors='backslashreplace') if len(value) < 1000 else {'bytes': len(value)}
    if isinstance(value, (list, tuple)):
        return [clean(x) for x in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    return value


def emit(event, **fields):
    row = dict(event=event, **clean(fields))
    print(json.dumps(row), flush=True)
    with (ARGS.artifacts / 'events.jsonl').open('a') as out:
        out.write(json.dumps(row) + '\n')


def load():
    return dict(loadavg=Path('/proc/loadavg').read_text().strip(),
                cpu_stat=[line for line in Path('/proc/stat').read_text().splitlines()
                          if line.split()[0] in {f'cpu{i}' for i in cpus(ARGS.cores)}],
                processes=subprocess.check_output(
                    ['ps', '-eo', 'pid,psr,pcpu,comm', '--sort=-pcpu'], text=True).splitlines()[:25])


def summary(values):
    ordered = sorted(values)
    assert ordered
    return dict(n=len(values), p50=statistics.median(ordered),
                p99=ordered[min(len(ordered) - 1, (len(ordered) * 99 + 99) // 100 - 1)],
                max=ordered[-1])


class Client:
    def __init__(self, port, timeout=4, context=None):
        self.s = socket.create_connection(('127.0.0.1', port), timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if context:
            self.s = context.wrap_socket(self.s, server_hostname='localhost')
        self.f = self.s.makefile('rb')

    @staticmethod
    def wire(args):
        args = [x if isinstance(x, bytes) else str(x).encode() for x in args]
        return b'*%d\r\n' % len(args) + b''.join(b'$%d\r\n' % len(x) + x + b'\r\n' for x in args)

    def send(self, *args):
        self.s.sendall(self.wire(args))

    def read(self):
        line = self.f.readline()
        if not line:
            raise EOFError('server closed connection')
        tag, body = line[:1], line[1:-2]
        if tag == b'+':
            return body
        if tag == b'-':
            raise RuntimeError(body.decode())
        if tag == b':':
            return int(body)
        if tag == b'$':
            n = int(body)
            if n < 0:
                return None
            data = self.f.read(n)
            assert len(data) == n and self.f.read(2) == b'\r\n'
            return data
        if tag == b'*':
            n = int(body)
            return None if n < 0 else [self.read() for _ in range(n)]
        raise AssertionError(line)

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def info(self):
        return dict(line.split(':', 1) for line in self.cmd('INFO', 'persistence').decode().splitlines()
                    if ':' in line)

    def close(self):
        self.f.close()
        self.s.close()


class Server:
    count = 0

    def __init__(self, extra=(), data=None, single=False, fsize=None, defaults=False):
        Server.count += 1
        self.data = data or ARGS.artifacts / 'data'
        self.data.mkdir(parents=True, exist_ok=True)
        self.logpath = ARGS.artifacts / f'server-{Server.count}.log'
        self.log = self.logpath.open('wb')
        self.clients = []
        self.stopped = False
        assert not self.listening(), f'port {ARGS.port} occupied'
        argv = ['taskset', '-c', ARGS.cores, str(ARGS.binary), '--bind', '127.0.0.1',
                '--port', str(ARGS.port), '--save', '', '--appendonly', 'no',
                '--dir', str(self.data), '--protected-mode', 'no']
        if not ARGS.oracle and not defaults:
            argv += ['--shards', '16', '--thread-mode', ARGS.mode, '--net-io', ARGS.engine,
                     '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0',
                     '--read-local', '0', '--reorder', '0', '--enable-debug-command', 'yes']
            if single:
                argv += ['--place', 'ifid@' + str(cpus(ARGS.cores)[0])]
            elif ARGS.mode == '2s':
                argv += ['--ratio', ARGS.ratio]
        argv += list(extra)

        def limits():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if fsize is not None:
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
                signal.signal(signal.SIGXFSZ, signal.SIG_IGN)

        env = dict(os.environ)
        env.pop('TOMO_AOF_ACK_WINDOW', None)
        self.p = subprocess.Popen(argv, stdout=self.log, stderr=subprocess.STDOUT,
                                  preexec_fn=limits, env=env)
        emit('spawn', pid=self.p.pid, argv=argv, fsize=fsize, load=load())
        self.ready = False
        deadline = time.monotonic() + 8
        while self.p.poll() is None and time.monotonic() < deadline:
            try:
                c = Client(ARGS.port, .3)
                try:
                    self.ready = c.cmd('PING') == b'PONG'
                finally:
                    c.close()
                if self.ready:
                    break
            except (OSError, EOFError, RuntimeError):
                pass
            time.sleep(.01)
        emit('boot', ready=self.ready, exit=self.p.poll(), log=str(self.logpath))

    def listening(self):
        return subprocess.check_output(['ss', '-ltnH', f'sport = :{ARGS.port}']).strip()

    def client(self, timeout=4):
        assert self.ready, self.logpath.read_text(errors='replace')[-2000:]
        c = Client(ARGS.port, timeout)
        self.clients.append(c)
        return c

    def stop(self, sig=signal.SIGTERM):
        if self.stopped:
            return
        self.stopped = True
        escalated = False
        if self.p.poll() is None:
            self.p.send_signal(sig)
            try:
                self.p.wait(timeout=4)
            except subprocess.TimeoutExpired:
                escalated = True
                self.p.kill()
                self.p.wait(timeout=4)
        for c in self.clients:
            c.close()
        self.log.close()
        deadline = time.monotonic() + 4
        while self.listening() and time.monotonic() < deadline:
            time.sleep(.01)
        emit('stop', exit=self.p.returncode, escalated=escalated)
        assert not self.listening(), 'owned listener did not close'
        assert not escalated, 'owned server did not respond to SIGTERM'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def aof(policy=None):
    policy = policy or ARGS.policy
    return ['--appendonly', 'no'] if policy == 'off' else [
        '--appendonly', 'yes', '--appendfsync', policy, '--auto-aof-rewrite-percentage', '0']


def wait_rewrite(c, counter='aof_rewrites', count=1):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        info = c.info()
        # Redis's counter is total_rewrites, TomoKV's is aof_rewrites.
        actual = info.get(counter, info.get('aof_rewrites', info.get('aof_current_rewrite_time_sec', '0')))
        if int(actual) >= count and info['aof_rewrite_in_progress'] == '0' and \
                info.get('aof_rewrite_scheduled', '0') == '0':
            return info
        time.sleep(.01)
    raise AssertionError(info)


def snapshot():
    with Server() as s:
        c = s.client()
        assert c.cmd('SET', 'saved', 'original') == b'OK'
        assert c.cmd('SAVE') == b'OK'
    with Server(aof('always')) as s:
        c = s.client()
        first = c.cmd('GET', 'saved')
        emit('first_aof_boot', saved=first)
        assert first == (None if ARGS.oracle else b'original')
        assert c.cmd('SET', 'new', 'later') == b'OK'
    with Server(aof('always')) as s:
        c = s.client()
        second = c.cmd('GET', 'saved')
        emit('second_aof_boot', saved=second)
        assert second == first, 'PS4.1: boot changed the snapshot-derived dataset'
        assert c.cmd('GET', 'new') == b'later'


def filename():
    for i, name in enumerate(('has space.aof', 'quote"slash\\.aof', "single'quote.aof", 'tabs\tlines\n.aof')):
        data = ARGS.artifacts / f'filename-{i}'
        opt = aof('always') + ['--appendfilename', name]
        with Server(opt, data=data) as s:
            c = s.client()
            assert c.cmd('SET', 'k', 'value') == b'OK'
            assert isinstance(c.cmd('BGREWRITEAOF'), bytes)
            wait_rewrite(c)
            manifest = next(data.rglob('*.manifest'))
            emit('manifest', name=name, text=manifest.read_text())
        with Server(opt, data=data) as s:
            assert s.client().cmd('GET', 'k') == b'value', 'PS4.2: quoted name did not replay'


def large():
    with Server(aof('always'), single=(ARGS.mode == '1s')) as s:
        c = s.client()
        for size in (70000, 3 * 1024 * 1024, 5 * 1024 * 1024):
            value = b'b' * size
            assert c.cmd('SET', 'big', value) == b'OK', 'PS4.3: recording did not progress'
            assert c.cmd('GET', 'big') == value
            emit('large_reply', size=size)
        assert s.client().cmd('PING') == b'PONG'
    with Server(aof('always'), single=(ARGS.mode == '1s')) as s:
        assert s.client().cmd('STRLEN', 'big') == 5 * 1024 * 1024


def large_placed():
    assert ARGS.mode == '1s'
    with Server(aof()) as s:
        c = s.client()
        keys = [f'writer:{i}' for i in range(256)]
        owners = c.cmd('DEBUG', 'SHARDS', *keys)
        writer = len(cpus(ARGS.cores)) - 1
        key = next((key for key, (_, owner) in zip(keys, owners) if owner == writer), None)
        assert key is not None, 'writer-owned shard was never armed'
        emit('writer_shard', key=key, writer=writer)
        assert c.cmd('SET', key, b'v' * (5 * 1024 * 1024)) == b'OK'
        assert s.client().cmd('STRLEN', key) == 5 * 1024 * 1024


def error():
    with Server(aof('always'), fsize=128 * 1024) as s:
        c = s.client()
        assert c.cmd('SET', 'before', 'ok') == b'OK'
        c.send('SET', 'full', b'z' * 200000)
        try:
            reply = c.read()
            raise AssertionError(f'failed write acknowledged: {reply!r}')
        except (EOFError, OSError):
            pass
        try:
            s.p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise AssertionError('PS4.4: always write failure left clients waiting forever')
        emit('write_error_exit', code=s.p.returncode, log=s.logpath.read_text(errors='replace'))
        assert s.p.returncode == 1


def tickets():
    opt = aof('always') + ([] if ARGS.oracle else ['--atomic', '1' if ARGS.case == 'tickets' else '0'])
    keys = [f'group:{i}' for i in range(32)]
    for boot in range(4):
        with Server(opt) as s:
            c = s.client()
            before = c.cmd('MGET', *keys)
            assert before == ([None] * len(keys) if boot == 0 else [f'value:{boot-1}'.encode()] * len(keys))
            if boot < 3:
                if ARGS.case == 'exec_tickets':
                    assert c.cmd('MULTI') == b'OK'
                    for key in keys:
                        assert c.cmd('SET', key, f'value:{boot}') == b'QUEUED'
                    assert c.cmd('EXEC') == [b'OK'] * len(keys)
                else:
                    assert c.cmd('MSET', *[x for key in keys for x in (key, f'value:{boot}')]) == b'OK'
            emit('ticket_boot', boot=boot, info=c.info())


def resurrection():
    opt = aof('always') + ['--atomic', '1']
    old = [f'oldgroup:{i}' for i in range(32)]
    new = [f'newgroup:{i}' for i in range(32)]
    with Server(opt) as s:
        c = s.client()
        assert c.cmd('DEBUG', 'AOF-STOP-AFTER-GROUP-FRAGMENTS', 1) == b'OK'
        c.send('MSET', *[x for key in old for x in (key, 'uncommitted')])
        try:
            c.read()
            raise AssertionError('directed torn group was acknowledged')
        except (EOFError, OSError):
            pass
        s.p.wait(timeout=4)
        assert s.p.returncode == -signal.SIGKILL, 'torn-group window never opened'
        emit('torn_group_armed', exit=s.p.returncode)
    for boot in (2, 3, 4):
        with Server(opt) as s:
            c = s.client()
            values = c.cmd('MGET', *old)
            emit('torn_group_replay', boot=boot, values=values, info=c.info())
            assert values == [None] * len(old), 'PS4.5: unacknowledged group resurrected'
            if boot == 2:
                assert c.cmd('MSET', *[x for key in new for x in (key, 'committed')]) == b'OK'
            else:
                assert c.cmd('MGET', *new) == [b'committed'] * len(new)


def off_writer(s):
    # Read the actual placement: roles can interleave across L3 domains.
    probe = s.client()
    roles = [line.split() for line in probe.cmd('DEBUG', 'LBSIGNALS').decode().splitlines()
             if line.startswith('thread ')]
    writer = max(int(row[1]) for row in roles if row[2] in ('io', 'fused'))
    assert writer > 0
    for _ in range(128):
        c = s.client()
        owner = c.cmd('DEBUG', 'IO-THREAD')
        assert isinstance(owner, int)
        if owner != writer:
            emit('off_writer', owner=owner, writer=writer)
            return c
        c.close()
        s.clients.remove(c)
    raise AssertionError('off-writer connection was never armed')


def tlswake():
    """Report-only PFPERSIS.1 shape from docs/round4/pf-persist-tls/shapes.py.

    TLS 1.3, depth 32, 1/4/16 KiB, eight batches, idle then 1 ms PINGs.
    """
    import ssl
    selected = cpus(ARGS.cores)
    assert len(selected) >= 2 and ARGS.tls_port is not None
    assert not subprocess.check_output(['ss', '-ltnH', f'sport = :{ARGS.tls_port}']).strip()
    cert, key = ARGS.artifacts / 'cert.pem', ARGS.artifacts / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    place = f'ifid@{selected[0]}'
    if ARGS.mode == '2s':
        place += f',ex@{selected[1]}'
    extra = ['--place', place, '--tls-port', str(ARGS.tls_port), '--tls-cert-file', str(cert),
             '--tls-key-file', str(key), '--tls-auth-clients', 'no', '--tls-protocols', 'TLSv1.3']
    for rep in range(3):
        with Server(extra) as s:
            plain, poke = s.client(), s.client()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
            c = Client(ARGS.tls_port, context=ctx)
            s.clients.append(c)
            for size in (1024, 4096, 16384):
                assert plain.cmd('SET', 'tlskey', b'x' * size) == b'OK'
                for poked in (False, True):
                    stop, errors = threading.Event(), []
                    def pokes():
                        try:
                            while not stop.is_set():
                                assert poke.cmd('PING') == b'PONG'
                                stop.wait(.001)
                        except BaseException as error:
                            errors.append(repr(error))
                    worker = threading.Thread(target=pokes) if poked else None
                    before = load()
                    if worker:
                        worker.start()
                    values = []
                    try:
                        for _ in range(8):
                            start = time.perf_counter()
                            c.s.sendall(c.wire(('GET', 'tlskey')) * 32)
                            for _ in range(32):
                                assert c.read() == b'x' * size
                            values.append((time.perf_counter() - start) * 1000)
                    finally:
                        stop.set()
                        if worker:
                            worker.join(timeout=5)
                    assert not errors and (not worker or not worker.is_alive())
                    emit('tlswake_ms', rep=rep, mode=ARGS.mode, size=size, depth=32,
                         poked=poked, latency=summary(values), load_before=before, load_after=load())


def latency():
    before = load()
    # defaults really means the shipped geometry and balancers; only persistence
    # and the temporary destination/port differ, as in ack_default.py.
    with Server(aof(), defaults=(ARGS.shape == 'defaults')) as s:
        per = []
        nconn = 1 if ARGS.shape == 'seq' else 12
        for n in range(nconn):
            c = off_writer(s) if ARGS.shape == 'seq' else s.client()
            for i in range(4):
                assert c.cmd('SET', f'warm:{i}', 'x') == b'OK'
            values = []
            for i in range(ARGS.samples):
                start = time.perf_counter()
                assert c.cmd('SET', f'c{n}:{i}', 'x' * 100) == b'OK'
                values.append((time.perf_counter() - start) * 1000)
            per.append(summary(values))
        emit('latency_ms', mode=ARGS.mode, policy=ARGS.policy, shape=ARGS.shape, connections=per,
             load_before=before, load_after=load())
        if not ARGS.observe:
            assert max(row['p50'] for row in per) < 10, 'PS4.7: acknowledgement waits for 50 ms park'


def rewrite_fail2():
    with Server(aof()) as s:
        c = s.client()
        assert c.cmd('SET', 'safe', 'value') == b'OK'
        c.cmd('BGREWRITEAOF')
        wait_rewrite(c)
        ad = s.data / 'appendonlydir'
        for n, seq in ((1, 3), (2, 4)):
            obstacle = ad / f'appendonly.aof.{seq}.base.tomo'
            obstacle.mkdir()
            assert c.cmd('SET', f'between{n}', 'x') == b'OK'
            c.cmd('BGREWRITEAOF')
            inf = wait_rewrite(c, 'aof_rewrite_failures', n)
            assert inf['aof_last_bgrewrite_status'] == 'err', 'failed-rewrite window never opened'
            emit('rewrite_failure', n=n, manifest=(ad / 'appendonly.aof.manifest').read_text())
            obstacle.rmdir()
        assert c.cmd('SET', 'last', 'written') == b'OK'
    with Server(aof()) as s:
        c = s.client()
        assert c.cmd('MGET', 'safe', 'between1', 'between2', 'last') == [b'value', b'x', b'x', b'written']


def manifest_missing():
    with Server(aof()) as s:
        c = s.client()
        assert c.cmd('SET', 'safe', 'value') == b'OK'
        c.cmd('BGREWRITEAOF')
        wait_rewrite(c)
        assert c.cmd('SET', 'later', 'value2') == b'OK'
    ad = s.data / 'appendonlydir'
    manifest = ad / 'appendonly.aof.manifest'
    manifest.rename(s.data / 'manifest.saved')
    saved = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ad.iterdir() if p.is_file()}
    assert len(saved) >= 2, 'base and increment were not created'
    with Server(aof()) as s:
        # Empty boot or explicit refusal is allowed; destroying old segments is not.
        after = {name: hashlib.sha256((ad / name).read_bytes()).hexdigest()
                 for name in saved if (ad / name).is_file()}
        emit('missing_manifest', ready=s.ready, before=saved, after=after)
        assert after == saved, 'PS4.9: unreferenced AOF segments were deleted/overwritten'


def bgsave():
    with Server() as s:
        c = s.client(20)
        for start in range(0, ARGS.keys, 1000):
            assert c.cmd('MSET', *[x for i in range(start, min(start + 1000, ARGS.keys))
                                   for x in (f'k{i}', 'v' * 200)]) == b'OK'
        times = {}
        target = s.data / 'dump.tomo'
        for poked in (False, True):
            target.unlink(missing_ok=True)
            before = load()
            start = time.perf_counter()
            c.cmd('BGSAVE')
            deadline = time.monotonic() + 40
            while not target.exists() and time.monotonic() < deadline:
                if poked:
                    assert c.cmd('PING') == b'PONG'
                time.sleep(.001)
            assert target.exists(), 'BGSAVE did not finish'
            times['poked' if poked else 'unpoked'] = time.perf_counter() - start
            emit('bgsave_seconds', poked=poked, seconds=time.perf_counter() - start,
                 bytes=target.stat().st_size, load_before=before, load_after=load())
            assert c.info()['rdb_bgsave_in_progress'] == '0'
        if not ARGS.observe:
            assert times['unpoked'] < 1, 'PS4.7: snapshot chunks did not wake their writer'


CASES = dict(snapshot=snapshot, filename=filename, large=large, large_placed=large_placed,
             error=error, tickets=tickets, exec_tickets=tickets, resurrection=resurrection,
             latency=latency, rewrite_fail2=rewrite_fail2, manifest_missing=manifest_missing,
             bgsave=bgsave, tlswake=tlswake)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=CASES)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--tls-port', type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--policy', choices=('off', 'no', 'everysec', 'always'), default='everysec')
    parser.add_argument('--oracle', action='store_true')
    parser.add_argument('--shape', choices=('seq', 'conns', 'defaults'), default='seq')
    parser.add_argument('--samples', type=int, default=24)
    parser.add_argument('--keys', type=int, default=400000)
    parser.add_argument('--observe', action='store_true')
    parser.add_argument('--artifacts', type=Path, required=True)
    ARGS = parser.parse_args()
    ARGS.binary = ARGS.binary.resolve()
    ARGS.artifacts = ARGS.artifacts.resolve()
    ARGS.artifacts.mkdir(parents=True, exist_ok=False)
    try:
        CASES[ARGS.case]()
        emit('PASS', case=ARGS.case)
    except BaseException as error:
        emit('FAIL', case=ARGS.case, error=repr(error))
        raise
