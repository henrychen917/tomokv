#!/usr/bin/env python3
"""Round-5 S1 witnesses, promoted from round5-read/tests/{net,ex-path,io-loop}.

Transcripts: T20/T20b/T20d/T2, T17, T12/T12b/T12c, T01/T21, T02/T02b/T03/T08.
Only finite correctness traffic; no throughput measurement. Each failure is fatal
to its gate row. All servers are owned, locale-fixed, bounded, and reaped.
"""
import argparse
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import resource
import selectors
import socket
import ssl
import subprocess
import time
import traceback

import _lib
import _netfix as n


def arguments():
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=('tls-watch', 'exclusive', 'fds', 'tls-idle', 'boot'), required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    a.binary = str(Path(a.binary).resolve())
    return a


def certs(a):
    dest = a.output / 'certs'
    subprocess.run(['python3', 'tests/tls.py', '--generate', str(dest)], check=True,
                   stdout=subprocess.DEVNULL)
    return dest


def tls_args(a):
    return ['--tls-port', str(a.port + 1), '--tls-cert-file', str(a.certs / 'server.crt'),
            '--tls-key-file', str(a.certs / 'server.key'), '--tls-ca-cert-file',
            str(a.certs / 'ca.crt'), '--tls-auth-clients', 'no']


def connect(a, version=None):
    if version is None:
        return n.connect(a.port)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ctx.maximum_version = getattr(ssl.TLSVersion, 'TLSv1_' + version)
    ctx.set_ciphers('ECDHE-RSA-AES128-GCM-SHA256')
    c = _lib.Conn.__new__(_lib.Conn)
    c.host, c.port = '127.0.0.1', a.port + 1
    raw = socket.create_connection((c.host, c.port), timeout=4)
    c.sock = ctx.wrap_socket(raw, server_hostname='localhost')
    c.file = c.sock.makefile('rb')
    return c


def info(c):
    return dict(line.split(b':', 1) for line in c.must('INFO', 'stats').splitlines()
                if b':' in line and not line.startswith(b'#'))


def argv(a, directory, mode, engine, db, extra, oracle=False):
    cmd = ['taskset', '-c', a.cores, a.oracle if oracle else a.binary,
           '--bind', '127.0.0.1', '--port', str(a.port), '--save', '',
           '--appendonly', 'no', '--dir', str(directory)]
    if not oracle:
        cmd += ['--thread-mode', mode, '--net-io', engine, '--shards', '16',
                '--databases', str(db), '--client-lb', '0']
        if mode == '2s':
            cmd += ['--ratio', a.ratio]
    return cmd + list(extra)


@contextmanager
def process(a, label, mode='2s', engine='uring', db=16, extra=(), limit=None, oracle=False):
    directory = a.output / label
    directory.mkdir(parents=True, exist_ok=True)
    cmd = argv(a, directory, mode, engine, db, extra, oracle)
    if limit:
        cmd = ['prlimit', f'--nofile={limit}:{limit}'] + cmd
    (directory / 'command.json').write_text(json.dumps(cmd))
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                             env=dict(os.environ, LC_ALL='C'), start_new_session=True)
        p.logpath = directory / 'server.log'
        try:
            yield p
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                    raise AssertionError(f'{label}: shutdown timeout')


def ready(a, p):
    end = time.monotonic() + 20
    while time.monotonic() < end:
        assert p.poll() is None, (p.returncode, p.logpath.read_text())
        try:
            with closing(connect(a)) as c:
                assert c.must('PING') == b'PONG'
            return
        except OSError:
            time.sleep(.03)
    raise AssertionError('boot deadline expired')


def tls_watch(a, label, mode, engine, db):
    # A fresh server for each suppression/version arm makes every crash visible.
    value = b'y' * 20000
    for version in ('3', '2'):
        for suppression in ('tracking', 'skip'):
            arm = f'{label}-tls1{version}-{suppression}'
            with process(a, arm, mode, engine, db, tls_args(a)) as p:
                ready(a, p)
                with closing(connect(a)) as admin, closing(connect(a, version)) as c:
                    c.must('HELLO', '3')
                    assert c.must('SET', 'mykey', value) == b'OK'
                    assert c.must('WATCH', 'mykey') == b'OK'
                    if version == '2':
                        assert int(info(admin)[b'tls_ktls_active']) == 1, 'kTLS arm never armed'
                    before = int(info(admin)[b'zc_releases'])
                    if suppression == 'tracking':
                        assert c.must('CLIENT', 'TRACKING', 'ON') == b'OK'
                        assert c.must('GET', 'mykey') == value
                    else:
                        # SKIP consumes a small PING; the following borrowed GET must
                        # traverse the same suppressing drain without being skipped.
                        c.sock.sendall(_lib.encode('CLIENT', 'REPLY', 'SKIP') +
                                       _lib.encode('PING') + _lib.encode('GET', 'mykey'))
                        assert c.read() == value
                    assert c.must('GET', 'mykey') == value
                    assert int(info(admin)[b'zc_releases']) == before, 'TLS GET borrowed store memory'
                    assert p.poll() is None
            assert p.returncode == 0, p.returncode
    return '4 TLS WATCH/suppression arms; exact 20KB replies; no store borrows'


def exclusive(a, label, mode, engine, db):
    for transport in ('tcp', 'tls', 'unix'):
        path = Path('build').resolve() / f'nf2-{os.getpid()}.sock'
        extra = tls_args(a) if transport == 'tls' else (
            ['--unixsocket', str(path)] if transport == 'unix' else [])
        with process(a, label + '-' + transport, mode, engine, db, extra) as first:
            ready(a, first)
            second_extra = extra[:]
            if transport != 'tcp':
                second_extra += ['--port', str(a.port + 2)]
            with process(a, label + '-' + transport + '-second', mode, engine, db,
                         second_extra) as second:
                try:
                    rc = second.wait(12)
                except subprocess.TimeoutExpired:
                    raise AssertionError(f'second {transport} server booted on occupied endpoint')
                log = second.logpath.read_text()
                assert rc == 1 and 'Address already in use' in log, (rc, log)
                assert 'listening on' not in log and 'listening with TLS' not in log, log
            with closing(n.connect(a.port, unix=path if transport == 'unix' else None)) as c:
                assert c.must('SET', 'isolation', 'first') == b'OK'
                assert c.must('GET', 'isolation') == b'first'
        assert first.returncode == 0
    return '3 occupied endpoints refused with exit 1; first instance retained data'


def fds(a, label, mode, engine, db):
    with process(a, label, mode, engine, db, tls_args(a), limit=200) as p:
        ready(a, p)
        with closing(connect(a)) as admin:
            mc = int(admin.must('CONFIG', 'GET', 'maxclients')[1])
            own = len(os.listdir(f'/proc/{p.pid}/fd')) - 1  # exclude this admin
            error = admin.cmd('CONFIG', 'SET', 'maxclients', '1000')
            assert isinstance(error, _lib.RespError), ('CONFIG SET accepted impossible limit', error)
            text = str(error)
            assert "CONFIG SET failed (possibly related to argument 'maxclients') - The operating system is not able to handle the specified number of clients, try with " in text, text
            assert int(admin.must('CONFIG', 'GET', 'maxclients')[1]) == mc
            assert own + mc < 200, (own, mc)
            assert 'maxclients has been reduced' in p.logpath.read_text()
            sockets = []
            try:
                for _ in range(mc + 10):
                    s = socket.create_connection(('127.0.0.1', a.port), timeout=3)
                    s.settimeout(3)
                    s.sendall(_lib.encode('PING'))
                    sockets.append(s)
                replies = [s.recv(128) for s in sockets]
                assert all(r == b'+PONG\r\n' or r == b'-ERR max number of clients reached\r\n' for r in replies), replies
                assert sum(r.startswith(b'-ERR') for r in replies) >= 10
            finally:
                for s in sockets:
                    s.close()
    assert p.returncode == 0
    return dict(maxclients=mc, own_fds=own, answered=len(replies), rejected=sum(r.startswith(b'-ERR') for r in replies))


def tls_idle(a, label, mode, engine, db):
    with process(a, label, mode, engine, db, tls_args(a) + ['--timeout', '1']) as p:
        ready(a, p)
        with closing(connect(a, '3')) as c:
            deadline = time.monotonic() + 4
            pings = 0
            while time.monotonic() < deadline:
                assert c.must('PING') == b'PONG'
                pings += 1
                time.sleep(.1)
            assert pings >= 20
        # Exact plaintext byte accounting: INFO's own input is included, its
        # output follows the snapshot. Subtract the actual preceding wire reply,
        # not an estimate from another INFO (whose length can change).
        with closing(connect(a)) as admin:
            for version in (None, '3', '2'):
                with closing(connect(a, version)) as c:
                    assert c.must('PING') == b'PONG'
                    before_body = admin.must('INFO', 'stats')
                    before = dict(l.split(b':', 1) for l in before_body.splitlines() if b':' in l)
                    payload = b'q' * 10000
                    for _ in range(10):
                        assert c.must('ECHO', payload) == payload
                    after = info(admin)
                    incoming = int(after[b'total_net_input_bytes']) - int(before[b'total_net_input_bytes'])
                    outgoing = int(after[b'total_net_output_bytes']) - int(before[b'total_net_output_bytes'])
                    assert incoming == 10 * len(_lib.encode('ECHO', payload)) + len(_lib.encode('INFO', 'stats')), (version, incoming)
                    expected = 10 * 10010 + len(before_body) + len(str(len(before_body))) + 5
                    assert outgoing == expected, (version, outgoing, expected)
    assert p.returncode == 0
    return dict(busy_tls13_pings=pings, exact_byte_paths=3)


def boot(a, label, mode, engine, db):
    blocked = a.output / (label + '-not-directory')
    blocked.write_bytes(b'not a directory')
    with process(a, label + '-failure', mode, engine, db,
                 ['--appendonly', 'yes', '--appenddirname', str(blocked)]) as p:
        rc = p.wait(20)
        log = p.logpath.read_text()
        assert rc == 1, (rc, log)
        assert 'listening on' not in log and 'listening with TLS' not in log, log
    # Poll log bytes and connect immediately on the banner (auditor T03/T08).
    for attempt in range(5):
        with process(a, f'{label}-ready-{attempt}', mode, engine, db) as p:
            end = time.monotonic() + 20
            while 'listening on' not in p.logpath.read_text():
                assert p.poll() is None and time.monotonic() < end
                time.sleep(.001)
            with closing(connect(a)) as c:
                assert c.must('PING') == b'PONG'
        assert p.returncode == 0
    return 'exit 1 without ready banner; 5/5 immediate banner connects'


def main():
    os.environ['LC_ALL'] = 'C'
    # Never leave core dumps from deliberately exercised PRE crashes.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    a = arguments()
    a.certs = certs(a)
    results = {}
    failed = []
    test = globals()[a.case.replace('-', '_')]
    for mode in ('2s', '1s'):
        for engine in ('uring', 'epoll'):
            for db in (1, 16):
                label = f'{a.case}-{mode}-{engine}-db{db}'
                try:
                    results[label] = test(a, label, mode, engine, db)
                    print('PASS', label, results[label], flush=True)
                except Exception:
                    results[label] = traceback.format_exc()
                    failed.append(label)
                    print('FAIL', label, results[label], flush=True)
                (a.output / 'results.json').write_text(json.dumps(results, indent=2))
    print(f'{a.case}: {len(results)-len(failed)}/{len(results)} legs passed', flush=True)
    assert not failed, failed


if __name__ == '__main__':
    main()
