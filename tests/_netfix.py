"""Owned, bounded server lifetimes for the netfix gate jobs (three reserved ports)."""
import argparse
from contextlib import contextmanager
import json
from functools import lru_cache
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
import traceback

import _lib


def arguments():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--tls-oracle', default=os.getenv('NETFIX_TLS_ORACLE', ''))
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    a.binary = str(Path(a.binary).resolve())
    a.oracle = str(Path(a.oracle).resolve())
    return a


def certificates(a):
    certs = a.output / 'certs'
    subprocess.run(['python3', 'tests/tls.py', '--generate', str(certs)], check=True,
                   stdout=subprocess.DEVNULL)
    return certs


@lru_cache(maxsize=8)
def client_context(certs):
    ctx = ssl.create_default_context(cafile=str(certs / 'ca.crt'))
    ctx.check_hostname = False
    return ctx


def connect(port, certs=None, unix=None):
    c = _lib.Conn.__new__(_lib.Conn)
    c.host, c.port = '127.0.0.1', port
    if unix:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect(str(unix))
    else:
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    if certs:
        s = client_context(certs).wrap_socket(s, server_hostname='localhost')
    c.sock, c.file = s, s.makefile('rb')
    return c


@contextmanager
def server(a, label, *, oracle=False, mode='2s', engine='uring', certs=None, extra=()):
    directory = (a.output / label).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cmd = ['taskset', '-c', a.cores, (a.tls_oracle if certs and a.tls_oracle else a.oracle) if oracle else a.binary,
           '--port', str(a.port), '--bind', '127.0.0.1', '--protected-mode', 'no',
           '--save', '', '--appendonly', 'no', '--dir', str(directory),
           '--maxclients', '20032']
    if not oracle:
        cmd += ['--thread-mode', mode, '--net-io', engine, '--shards', '16',
                '--client-lb', '0', '--enable-debug-command', 'yes']
        if mode == '2s':
            cmd += ['--ratio', a.ratio]
    if certs:
        cmd += ['--tls-port', str(a.port + 1), '--tls-cert-file', str(certs / 'server.crt'),
                '--tls-key-file', str(certs / 'server.key'), '--tls-ca-cert-file',
                str(certs / 'ca.crt'), '--tls-auth-clients', 'no']
    cmd += list(extra)
    (directory / 'command.json').write_text(json.dumps(cmd))
    with (directory / 'server.log').open('w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if proc.poll() is not None:
                    raise AssertionError(f'{label}: boot exited {proc.returncode}')
                try:
                    c = connect(a.port)
                    assert c.must('PING') == b'PONG'
                    c.close()
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.03)
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise AssertionError(f'{label}: shutdown timed out')
            assert proc.returncode == 0, f'{label}: exit {proc.returncode}'


def matrix(a, test, *, tls=True):
    certs = certificates(a) if tls else None
    results, failures = {}, []
    for oracle, mode, engine in [(True, 'oracle', 'oracle')] + [
            (False, m, e) for m in ('1s', '2s') for e in ('epoll', 'uring')]:
        for transport in ('tcp', 'tls') if tls else ('tcp',):
            label = f'{mode}-{engine}-{transport}'
            try:
                with server(a, label, oracle=oracle, mode=mode, engine=engine, certs=certs if transport == 'tls' else None) as proc:
                    results[label] = test(a, a.port + (transport == 'tls'),
                                          certs if transport == 'tls' else None, proc, oracle)
                print('PASS', label, results[label], flush=True)
            except Exception:
                failures.append(label)
                results[label] = traceback.format_exc()
                print('FAIL', label, results[label], flush=True)
    (a.output / 'results.json').write_text(json.dumps(results, indent=2))
    assert not failures, failures
