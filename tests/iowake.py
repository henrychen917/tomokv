#!/usr/bin/env python3
"""iowake directed witnesses for the round-5 bounded-queue wake audit (2026-11-04).

Each leg boots its own server on --cores/--port, asserts exact replies and bounds the latency of
the operation that the missing wake delays well below the 50 ms idle-park rescue, so a lost wake
fails deterministically instead of being masked by the park timeout.

tls      F5. TLS output after the first plaintext unit was sent one unit per loop pass and nothing
         re-drove it. Every TLS transport is driven on one boot per mode/engine: kernel TLS in
         both directions (TLS 1.2 GCM), socket-userspace (TLS 1.3: kernel TX, OpenSSL RX) and the
         memory-BIO engine (TLS 1.2 CBC). The server-side socket's tcp-ulp-tls state proves which
         transport each connection reached; plaintext TCP is the control on the same boot.
aof      F4. The AOF writer was never re-woken while a record larger than one 64 KiB frame held
         the stream. Slow-serializing hash and list post-images are written under appendfsync
         everysec while a PING probe on a third thread (neither the writer nor an owner) is timed:
         every gated reply waits for the writer, so a sleeping writer delays every PING. The
         restart replays every acknowledged post-image.
bgsave   F9. A BGSAVE owner refused by its full chunk channel was never woken when the writer
         freed it. One owner holds the whole dataset and the BGSAVE writer is another thread; the
         capture rate must exceed a bound that a 50 ms-per-channel cadence cannot reach, the
         owner's channel must actually have refused a post, and the dump reloads exactly.
loadaof  F13. DEBUG LOADAOF issued on the AOF writer's own IO thread spun without submitting or
         reaping its writes. It follows 200 pipelined SETs on the writer thread's connection, so
         their chunks are still unwritten when it drains; it must reply within 5 s, a PING on
         another thread must answer within 2 s, and every acknowledged key must reload exactly.
         The same pipeline from another IO thread is the control.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import select
import socket
import ssl
import subprocess
import time
import traceback

from _lib import Conn, encode, lbsignals, topology, wait_ready
import tls as tlslib

PARK_RESCUE_MS = 50.0


class Boot:
    """One owned server lifetime. stop() requires a clean exit without a forced kill."""

    def __init__(self, args, directory, mode, engine, extra=(), name='server'):
        self.port = args.port
        self.directory = directory
        flags = ['--bind', '127.0.0.1', '--port', str(self.port), '--dir', str(directory.resolve()),
                 '--save', '', '--enable-debug-command', 'yes', '--shards', '16',
                 '--net-io', engine, '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
        if mode == '2s':
            flags += ['--thread-mode', '2s', '--ratio', '6:2']
        elif mode == '1s':
            flags += ['--thread-mode', 'fused', '--read-local', '1']
        elif mode == '1s-r7':
            flags += ['--thread-mode', 'fused', '--read-local', '0', '--reorder', '1']
        else:
            raise ValueError(mode)
        self.argv = ['taskset', '-c', args.cores, str(Path(args.binary).resolve()), *flags, *extra]
        directory.mkdir(parents=True, exist_ok=True)
        self.log = directory / f'{name}.log'
        (directory / f'{name}.argv.json').write_text(json.dumps(self.argv) + '\n')
        self.name = name
        with self.log.open('w') as log:
            self.proc = subprocess.Popen(self.argv, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, LC_ALL='C'))
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

    def stop(self):
        if self.c:
            with contextlib.suppress(Exception):
                self.c.close()
            self.c = None
        if self.exit is None:
            forced = False
            if self.proc.poll() is None:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                forced = True
                self.kill()
            self.exit = dict(rc=self.proc.returncode, forced=forced)
            (self.directory / f'{self.name}.exit.json').write_text(json.dumps(self.exit) + '\n')
        assert self.exit == dict(rc=0, forced=False), ('server did not exit cleanly', self.name, self.exit)


def released(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
            probe.listen()
            return True
        except OSError:
            return False


def drop_data(directory):
    """Keep logs and verdicts; remove persistence files once a leg is decided (disk budget)."""
    for path in sorted(directory.rglob('*'), reverse=True):
        if path.is_file() and path.suffix not in ('.log', '.json') and path.stat().st_size > 64 * 1024:
            path.unlink()


def wait(predicate, message, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError(message)


def info_fields(conn, section):
    reply = conn.cmd('INFO', section) if isinstance(conn, Conn) else conn.command('INFO', section)
    assert isinstance(reply, bytes), reply
    out = {}
    for line in reply.decode(errors='replace').splitlines():
        key, sep, value = line.partition(':')
        if sep:
            out[key] = value
    return out


def io_thread(conn):
    return int(conn.must('DEBUG', 'IO-THREAD'))


def connect_on(port, stall, want, attempts=200):
    """A plain connection whose IO thread satisfies want(tid)."""
    spare = []
    try:
        for _ in range(attempts):
            conn = Conn('127.0.0.1', port, timeout=stall)
            if want(io_thread(conn)):
                return conn
            spare.append(conn)
        raise AssertionError('no connection reached a qualifying IO thread')
    finally:
        for conn in spare:
            conn.close()


# ---------------------------------------------------------------------------------------------
# F5: TLS output re-drive
# ---------------------------------------------------------------------------------------------

TLS_CIPHERS = 'ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384'
TRANSPORTS = {
    # name: (TLS version, TLS 1.2 cipher, expected (rxconf, txconf) classes)
    'ktls12': (ssl.TLSVersion.TLSv1_2, 'ECDHE-RSA-AES256-GCM-SHA384', ('kernel', 'kernel')),
    'tls13': (ssl.TLSVersion.TLSv1_3, None, ('none', 'kernel')),
    'cbc12': (ssl.TLSVersion.TLSv1_2, 'ECDHE-RSA-AES256-SHA384', ('none', 'none')),
}


def ulp_state(tls_port, client_port):
    """(rxconf, txconf) classes of the server-side socket of one client connection."""
    out = subprocess.run(['ss', '-tnie', 'sport', '= :%d' % tls_port, 'and',
                          'dport', '= :%d' % client_port], capture_output=True, text=True,
                         timeout=10).stdout
    words = out.split()
    if 'tcp-ulp-tls' not in words:
        return ('none', 'none'), out

    def conf(name):
        try:
            value = words[words.index(name) + 1]
        except (ValueError, IndexError):
            return 'missing'
        return 'kernel' if value in ('sw', 'device') else value
    return (conf('rxconf:'), conf('txconf:')), out


class TlsClient:
    def __init__(self, port, cert_dir, version, cipher, stall):
        ctx = tlslib.context(str(cert_dir))
        ctx.minimum_version = ctx.maximum_version = version
        if cipher:
            ctx.set_ciphers(cipher)
        self.conn = tlslib.Conn('127.0.0.1', port, ctx, timeout=stall)

    def command(self, *args):
        return self.conn.command(*args)

    def pipeline(self, frames):
        self.conn.sock.sendall(b''.join(frames))
        return [self.conn.reader.read() for _ in frames]

    def local_port(self):
        return self.conn.sock.getsockname()[1]

    def close(self):
        self.conn.close(graceful=True)


class PlainClient:
    def __init__(self, port, stall):
        self.conn = Conn('127.0.0.1', port, timeout=stall)

    def command(self, *args):
        return self.conn.cmd(*args)

    def pipeline(self, frames):
        self.conn.raw(b''.join(frames))
        return [self.conn.read() for _ in frames]

    def close(self):
        self.conn.close()


def timed_probes(client, label, values, big, rounds, bound_ms):
    """Every probe repeats `rounds` times; each must be exact and inside the bound."""
    small = [f'iowake:tls:s{i}' for i in range(16)]
    medium = [f'iowake:tls:m{i}' for i in range(4)]
    probes = (
        ('MGET 16 x 2 KiB', lambda: client.command('MGET', *small), values['small']),
        ('16 pipelined GET x 2 KiB',
         lambda: client.pipeline([tlslib.frame('GET', key) for key in small]), values['small']),
        ('MGET 4 x 64 KiB', lambda: client.command('MGET', *medium), values['medium']),
        ('GET 1 MiB', lambda: client.command('GET', 'iowake:tls:big'), big),
    )
    worst = {}
    for name, run, expected in probes:
        for attempt in range(rounds):
            began = time.monotonic()
            reply = run()
            elapsed = (time.monotonic() - began) * 1000
            worst[name] = max(worst.get(name, 0.0), elapsed)
            if reply != expected:
                raise AssertionError(f'{label}: {name} reply mismatch on round {attempt}')
            if elapsed > bound_ms:
                raise AssertionError(f'{label}: {name} took {elapsed:.1f} ms on round {attempt} '
                                     f'(bound {bound_ms} ms, idle park {PARK_RESCUE_MS:.0f} ms)')
    return {name: round(ms, 2) for name, ms in worst.items()}


def case_tls(args, directory, mode, engine, evidence):
    cert_dir = args.output / 'certs'
    tls_port = args.port + 1
    extra = ['--tls-port', str(tls_port), '--tls-cert-file', str(cert_dir / 'server.crt'),
             '--tls-key-file', str(cert_dir / 'server.key'),
             '--tls-ca-cert-file', str(cert_dir / 'ca.crt'), '--tls-auth-clients', 'no',
             '--tls-protocols', 'TLSv1.2 TLSv1.3', '--tls-ciphers', TLS_CIPHERS,
             '--protected-mode', 'no', '--databases', '1']
    b = Boot(args, directory, mode, engine, extra)
    try:
        c = b.c
        wait(lambda: not released(tls_port), 'TLS listener did not open')
        values = {'small': [os.urandom(2048) for _ in range(16)],
                  'medium': [os.urandom(64 * 1024) for _ in range(4)]}
        big = os.urandom(1024 * 1024)
        for i, value in enumerate(values['small']):
            assert c.must('SET', f'iowake:tls:s{i}', value) == b'OK'
        for i, value in enumerate(values['medium']):
            assert c.must('SET', f'iowake:tls:m{i}', value) == b'OK'
        assert c.must('SET', 'iowake:tls:big', big) == b'OK'
        failures = []
        plain = PlainClient(args.port, args.stall)
        try:
            evidence['tcp'] = dict(worst_ms=timed_probes(plain, f'{mode}/{engine}/tcp', values, big,
                                                         args.rounds, args.bound_ms))
        except AssertionError as exc:
            failures.append(str(exc))
            evidence['tcp'] = dict(error=str(exc))
        finally:
            plain.close()
        # Every transport runs even after another failed: the leg reports which paths stall.
        for name, (version, cipher, expected) in TRANSPORTS.items():
            before = info_fields(c, 'stats')
            client = TlsClient(tls_port, cert_dir, version, cipher, args.stall)
            try:
                assert client.command('PING') == b'PONG'
                state, raw = ulp_state(tls_port, client.local_port())
                after = info_fields(c, 'stats')
                assert state == expected, (name, 'transport not reached', state, expected, raw)
                if name == 'ktls12':
                    assert int(after['tls_ktls_active']) == int(before['tls_ktls_active']) + 1, \
                        (name, before['tls_ktls_active'], after['tls_ktls_active'])
                else:
                    assert int(after['tls_ktls_fallback']) == int(before['tls_ktls_fallback']) + 1, \
                        (name, before['tls_ktls_fallback'], after['tls_ktls_fallback'])
                if name == 'tls13':
                    assert (int(after['tls_ktls_rx_declined_13']) ==
                            int(before['tls_ktls_rx_declined_13']) + 1), (name, 'RX decline not counted')
                evidence[name] = dict(version=client.conn.sock.version(),
                                      cipher=client.conn.sock.cipher()[0], ulp=list(state))
                try:
                    evidence[name]['worst_ms'] = timed_probes(
                        client, f'{mode}/{engine}/{name}', values, big, args.rounds, args.bound_ms)
                except AssertionError as exc:
                    failures.append(str(exc))
                    evidence[name]['error'] = str(exc)
            finally:
                client.close()
        after = info_fields(c, 'stats')
        evidence['tls_zc_suppressed'] = int(after['tls_zc_suppressed'])
        evidence['tls_plaintext_output_bytes'] = int(after['tls_plaintext_output_bytes'])
        b.stop()
        assert not failures, failures
    finally:
        b.kill()


# ---------------------------------------------------------------------------------------------
# shared persistence geometry
# ---------------------------------------------------------------------------------------------

AOF_EXTRA = ['--appendonly', 'yes', '--appendfsync', 'everysec',
             '--auto-aof-rewrite-percentage', '0']
MiB = 1024 * 1024


def aof_writer(c):
    """The elected AOF writer: the last IO-capable thread (Server::init, aof_.init)."""
    roles = topology(c).roles
    return sorted(t for t, role in roles.items() if role in ('io', 'fused'))[-1]


def key_on(c, prefix, want, limit=4096):
    """(key, owner) for the first candidate whose shard owner satisfies want(owner)."""
    names = [f'{prefix}:{i}' for i in range(limit)]
    for start in range(0, limit, 256):
        rows = c.must('DEBUG', 'SHARDS', *names[start:start + 256])
        for key, row in zip(names[start:start + 256], rows):
            if want(int(row[1])):
                return key, int(row[1])
    raise AssertionError(f'no {prefix} key reached a qualifying owner')


def thread_row(c, tid):
    return next(t for t in lbsignals(c).threads if t.tid == tid)


# ---------------------------------------------------------------------------------------------
# F4: AOF writer re-wake during a large record
# ---------------------------------------------------------------------------------------------

def gated_write(c, pusher, probe, command, expected, bound_ms, label):
    """Send one large-record write and time PINGs on `probe` until its reply arrives."""
    before = info_fields(c, 'persistence')
    pusher.send(*command)
    began = time.monotonic()
    worst = 0.0
    pings = 0
    while not select.select([pusher.sock], [], [], 0)[0]:
        sent = time.monotonic()
        assert probe.must('PING') == b'PONG', label
        elapsed = (time.monotonic() - sent) * 1000
        worst = max(worst, elapsed)
        pings += 1
        if elapsed > bound_ms:
            raise AssertionError(f'{label}: a gated PING waited {elapsed:.1f} ms (bound {bound_ms} '
                                 f'ms, idle park {PARK_RESCUE_MS:.0f} ms) while the record was open')
        assert time.monotonic() - began < 30, f'{label}: the write never replied'
    reply = pusher.read()
    elapsed = (time.monotonic() - began) * 1000
    after = info_fields(c, 'persistence')
    assert reply == expected, (label, 'reply', reply, expected)
    grew = int(after['aof_current_size']) - int(before['aof_current_size'])
    waits = int(after['aof_send_gate_waits']) - int(before['aof_send_gate_waits'])
    # Anti-vacuity: a multi-frame record, an open window and a gate that held the probe.
    assert grew >= MiB, (label, 'record was not larger than one frame', grew)
    assert pings >= 10, (label, 'the write window closed before the probe ran', pings)
    assert waits >= 1, (label, 'no reply waited on the AOF gate', waits)
    return dict(write_ms=round(elapsed, 2), pings=pings, worst_ping_ms=round(worst, 2),
                aof_bytes=grew, gate_waits=waits)


def case_aof(args, directory, mode, engine, evidence):
    b = Boot(args, directory, mode, engine, AOF_EXTRA)
    try:
        c = b.c
        writer = aof_writer(c)
        hash_key, hash_owner = key_on(c, 'iowake:aof:hash', lambda owner: owner != writer)
        list_key, list_owner = key_on(c, 'iowake:aof:list', lambda owner: owner != writer)
        owners = {hash_owner, list_owner}
        pusher = connect_on(args.port, args.stall, lambda t: t != writer and t not in owners)
        probe = connect_on(args.port, args.stall,
                           lambda t: t != writer and t not in owners and t != io_thread(pusher))
        evidence.update(writer=writer, owners=sorted(owners), pusher_io=io_thread(pusher),
                        probe_io=io_thread(probe))
        # Two slow serializers: a 200k-field hash (one record of under 64 frames, so its owner
        # never fills the channel) and a 3M-element list (a record that refills it repeatedly).
        fields = []
        for i in range(200000):
            fields += [f'f{i}', 'v']
        assert pusher.must('HSET', hash_key, *fields) == 200000
        for start in range(0, 3000000, 1000000):
            assert pusher.must('RPUSH', list_key, *(['1'] * 1000000)) == start + 1000000
        writes = []
        for i in range(args.repeats):
            writes.append(dict(kind='hash', **gated_write(
                c, pusher, probe, ['HSET', hash_key, f'extra{i}', 'v'], 1, args.bound_ms,
                f'{mode}/{engine}/hash#{i}')))
            writes.append(dict(kind='list', **gated_write(
                c, pusher, probe, ['RPUSH', list_key, f'x{i}'], 3000000 + i + 1, args.bound_ms,
                f'{mode}/{engine}/list#{i}')))
        evidence['writes'] = writes
        pusher.close()
        probe.close()
        b.stop()
        # Every acknowledged post-image replays.
        again = Boot(args, directory, mode, engine, AOF_EXTRA, name='restart')
        try:
            assert again.c.must('HLEN', hash_key) == 200000 + args.repeats
            assert again.c.must('LLEN', list_key) == 3000000 + args.repeats
            assert again.c.must('LINDEX', list_key, -1) == f'x{args.repeats - 1}'.encode()
            again.stop()
        finally:
            again.kill()
    finally:
        b.kill()


# ---------------------------------------------------------------------------------------------
# F9: BGSAVE chunk channel consumer -> producer wake
# ---------------------------------------------------------------------------------------------

def case_bgsave(args, directory, mode, engine, evidence):
    b = Boot(args, directory, mode, engine)
    try:
        c = b.c
        # One owner produces every chunk and the BGSAVE writer is a different thread, so the
        # only event that can resume a refused owner is the writer freeing its channel.
        saver = c
        owner = None
        keys = []
        names = [f'iowake:snap:{i}' for i in range(8192)]
        rows = []
        for start in range(0, len(names), 256):
            rows += c.must('DEBUG', 'SHARDS', *names[start:start + 256])
        saver_io = io_thread(saver)
        for key, row in zip(names, rows):
            if owner is None and int(row[1]) != saver_io:
                owner = int(row[1])
            if int(row[1]) == owner:
                keys.append(key)
            if len(keys) == args.snapshot_keys:
                break
        assert len(keys) == args.snapshot_keys, ('not enough single-owner keys', len(keys))
        values = {key: os.urandom(16) * (MiB // 16) for key in keys}
        for start in range(0, len(keys), 16):
            batch = keys[start:start + 16]
            c.raw(b''.join(encode('SET', key, values[key]) for key in batch))
            for _ in batch:
                assert c.read() == b'OK'
        dataset = sum(len(v) for v in values.values())
        # Neither probe may share the owner's loop: its traffic would wake a parked owner.
        poller = connect_on(args.port, args.stall, lambda t: t != owner)
        saves = []
        for i in range(args.repeats):
            refused = thread_row(poller, owner).full_events
            began = time.monotonic()
            assert saver.must('BGSAVE') == b'Background saving started'
            while info_fields(poller, 'persistence')['rdb_bgsave_in_progress'] != '0':
                assert time.monotonic() - began < 60, 'BGSAVE did not finish'
                time.sleep(.001)
            elapsed = time.monotonic() - began
            status = info_fields(poller, 'persistence')['rdb_last_bgsave_status']
            refusals = thread_row(poller, owner).full_events - refused
            rate = dataset / MiB / elapsed
            saves.append(dict(seconds=round(elapsed, 4), mib_per_s=round(rate, 1),
                              owner_channel_refusals=refusals))
            assert status == 'ok', status
            # Anti-vacuity: the owner's post was refused by a full chunk channel at least once.
            assert refusals > 0, ('the chunk channel never filled; the wait was not exercised', saves)
            if rate < args.capture_mib_s:
                raise AssertionError(f'{mode}/{engine}: BGSAVE captured {rate:.0f} MiB/s from one owner '
                                     f'(bound {args.capture_mib_s} MiB/s): {saves}')
        evidence.update(owner=owner, saver_io=saver_io, dataset_mib=dataset // MiB, saves=saves)
        poller.close()
        b.stop()
        again = Boot(args, directory, mode, engine, name='restart')
        try:
            assert again.c.must('DBSIZE') == len(keys)
            for key in (keys[0], keys[len(keys) // 2], keys[-1]):
                assert again.c.must('GET', key) == values[key], key
            again.stop()
        finally:
            again.kill()
    finally:
        b.kill()


# ---------------------------------------------------------------------------------------------
# F13: DEBUG LOADAOF on the AOF writer's own IO thread
# ---------------------------------------------------------------------------------------------

def case_loadaof(args, directory, mode, engine, evidence):
    b = Boot(args, directory, mode, engine, AOF_EXTRA)
    try:
        c = b.c
        writer = aof_writer(c)
        on_writer = connect_on(args.port, args.stall, lambda t: t == writer)
        off_writer = connect_on(args.port, args.stall, lambda t: t != writer)
        control = connect_on(args.port, args.stall, lambda t: t != writer)
        sentinels = {f'iowake:f13:s{i}': os.urandom(32) for i in range(16)}
        for key, value in sentinels.items():
            assert c.must('SET', key, value) == b'OK'
        keys = len(sentinels)
        attempts = []
        # Pipelined writes ahead of LOADAOF on the same connection: their chunks are posted, and
        # on the writer's own thread still unwritten, when LOADAOF drains. The writer-thread
        # attempts are the witness; the off-writer attempt takes the existing timed wait.
        for i, (name, issuer) in enumerate([('writer', on_writer)] * args.repeats +
                                           [('control', off_writer)]):
            batch = [f'iowake:f13:{i}:{n}' for n in range(200)]
            issuer.raw(b''.join(encode('SET', key, f'v{i}') for key in batch) +
                       encode('DEBUG', 'LOADAOF'))
            issuer.sock.settimeout(5)
            began = time.monotonic()
            try:
                assert all(issuer.read() == b'OK' for _ in batch), (name, 'pipelined SET')
                reply = issuer.read()
            except (TimeoutError, socket.timeout) as exc:
                raise AssertionError(f'{mode}/{engine}/{name}#{i}: DEBUG LOADAOF did not reply '
                                     'in 5 s') from exc
            finally:
                issuer.sock.settimeout(args.stall)
            elapsed = (time.monotonic() - began) * 1000
            assert reply == b'OK', (name, reply)
            control.sock.settimeout(2)
            try:
                assert control.must('PING') == b'PONG'
            except (TimeoutError, socket.timeout) as exc:
                raise AssertionError(f'{mode}/{engine}/{name}#{i}: PING after LOADAOF hung') from exc
            finally:
                control.sock.settimeout(args.stall)
            keys += len(batch)
            # Exact: every acknowledged write, including the pipelined batch, was reloaded.
            assert c.must('DBSIZE') == keys, (name, 'reloaded key count')
            assert c.must('GET', batch[-1]) == f'v{i}'.encode(), (name, 'pipelined value')
            for key, value in sentinels.items():
                assert c.must('GET', key) == value, (name, 'acknowledged sentinel lost', key)
            attempts.append(dict(issuer=name, issuer_io=io_thread(issuer), loadaof_ms=round(elapsed, 2)))
        evidence.update(writer=writer, attempts=attempts)
        for conn in (on_writer, off_writer, control):
            conn.close()
        b.stop()
    finally:
        b.kill()


# ---------------------------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------------------------

CASES = {'tls': case_tls, 'aof': case_aof, 'bgsave': case_bgsave, 'loadaof': case_loadaof}


def main():
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case', choices=sorted(CASES), required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--modes', nargs='+', default=None)
    p.add_argument('--engines', nargs='+', default=['uring', 'epoll'])
    p.add_argument('--rounds', type=int, default=10)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--bound-ms', type=float, default=25.0)
    p.add_argument('--capture-mib-s', type=float, default=200.0)
    p.add_argument('--snapshot-keys', type=int, default=128)
    p.add_argument('--stall', type=float, default=20.0)
    a = p.parse_args()
    # The caller owns the port allocation; TLS uses PORT+1. Stay below the ephemeral range.
    assert 1024 <= a.port and a.port + 1 < 32768, ('ports outside 1024-32767', a.port)
    assert a.bound_ms < PARK_RESCUE_MS, 'a bound at or above the park rescue proves nothing'
    a.output.mkdir(parents=True, exist_ok=False)
    if a.case == 'tls':
        tlslib.generate(str(a.output / 'certs'))
    modes = a.modes or (['2s', '1s', '1s-r7'] if a.case == 'tls' else ['2s', '1s'])
    rows = []
    for mode in modes:
        for engine in a.engines:
            name = f'{a.case}-{mode}-{engine}'
            directory = a.output / name
            record = dict(case=a.case, mode=mode, engine=engine)
            try:
                CASES[a.case](a, directory, mode, engine, record)
                record['verdict'] = 'PASS'
            except Exception as exc:  # noqa: BLE001 -- every leg reports, then the run fails
                record.update(verdict='FAIL', error=repr(exc), traceback=traceback.format_exc())
            wait(lambda: released(a.port) and released(a.port + 1),
                 'owned listener survived child teardown', timeout=15)
            directory.mkdir(parents=True, exist_ok=True)
            drop_data(directory)
            (directory / 'result.json').write_text(json.dumps(record, indent=2, default=str) + '\n')
            print(record['verdict'], name, record.get('error', ''), flush=True)
            rows.append(record)
    (a.output / 'results.json').write_text(json.dumps(rows, indent=2, default=str) + '\n')
    return int(any(r['verdict'] != 'PASS' for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
