#!/usr/bin/env python3
"""CG4.1/CG4.2/SV4.1/SV4.2, adapted from round4-read's T5/T9 and T1/T2.

Owns its boot and port. Expected results are the fixed Redis 7.4 contract;
--oracle repeats every selected probe against Redis, preserving positive witnesses.
Each case is a gate row; failed PRE runs retain replies and exact lifecycles.
All credentials are invented fixtures. No load generator or performance assertion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


class Resp:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=2)
        self.sock.settimeout(3)
        self.file = self.sock.makefile('rb')

    def cmd(self, *args):
        args = [a if isinstance(a, bytes) else str(a).encode() for a in args]
        self.sock.sendall(b'*%d\r\n' % len(args) + b''.join(
            b'$%d\r\n' % len(a) + a + b'\r\n' for a in args))
        return self.read()

    def read(self):
        line = self.file.readline()
        assert line.endswith(b'\r\n'), ('missing RESP reply', line)
        tag, body = line[:1], line[1:-2]
        if tag == b'+':
            return body
        if tag == b'-':
            return {'error': body.decode(errors='backslashreplace')}
        if tag == b':':
            return int(body)
        if tag in (b'$', b'='):
            n = int(body)
            if n < 0:
                return None
            data = self.file.read(n)
            assert self.file.read(2) == b'\r\n'
            return data
        if tag in (b'*', b'%', b'~'):
            n = int(body)
            return None if n < 0 else [self.read() for _ in range(n * (2 if tag == b'%' else 1))]
        if tag == b'_':
            return None
        raise AssertionError(line)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.file.close()
        self.sock.close()


def clean(value):
    if isinstance(value, bytes):
        return value.decode(errors='backslashreplace')
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    return value


def listeners(port):
    return subprocess.check_output(['ss', '-ltnH', 'sport', '=', ':' + str(port)], text=True).strip()


class Server:
    def __init__(self, run, label, mode, conf=None, extra=(), refusal=False, directory=None):
        self.run, self.label, self.port = run, label, run.args.port
        self.path = run.path / label
        self.path.mkdir()
        self.directory = directory or self.path / 'data'
        self.directory.mkdir(exist_ok=True)
        self.args = ['taskset', '-c', run.args.cores, str(run.binary)]
        if conf:
            self.args.append(str(conf))
        self.args += ['--bind', '127.0.0.1', '--port', str(self.port), '--save', '',
                      '--appendonly', 'no', '--dir', str(self.directory), '--protected-mode', 'no']
        if not run.oracle:
            self.args += ['--databases', '1', '--thread-mode', mode, '--shards', '16']
            if mode == '2s':
                self.args += ['--ratio', run.args.ratio]
        self.args += list(extra)
        self.refusal = refusal
        self.booted = False

    def __enter__(self):
        assert not listeners(self.port), ('occupied port', self.port)
        self.log = (self.path / 'server.log').open('wb')
        self.process = subprocess.Popen(self.args, stdout=self.log, stderr=subprocess.STDOUT)
        self.meta = dict(command=self.args, pid=self.process.pid)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                try:
                    with Resp(self.port) as c:
                        reply = c.cmd('PING')
                    assert reply == b'PONG' or is_error(reply, 'NOAUTH'), reply
                    self.booted = True
                    break
                except (OSError, AssertionError):
                    time.sleep(.02)
            self.meta['booted'] = self.booted
            if not self.refusal:
                assert self.booted, (self.path / 'server.log').read_text()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
                self.meta['forced_kill'] = True
        self.log.close()
        deadline = time.monotonic() + 3
        while listeners(self.port) and time.monotonic() < deadline:
            time.sleep(.02)
        self.meta.update(exit=self.process.returncode, port_closed=not listeners(self.port))
        (self.path / 'lifecycle.json').write_text(json.dumps(clean(self.meta), indent=2) + '\n')
        assert self.meta['port_closed'] and not self.meta.get('forced_kill'), self.meta

    def client(self):
        return Resp(self.port)


def is_error(value, prefix):
    return isinstance(value, dict) and value.get('error', '').startswith(prefix)


class Run:
    def __init__(self, args, binary, oracle=False):
        self.args, self.binary, self.oracle = args, Path(binary).resolve(), oracle
        self.path = args.output / ('oracle' if oracle else 'candidate')
        self.path.mkdir(parents=True)
        self.checks = []
        self.rows = {}

    def check(self, label, actual, expected):
        passed = expected(actual) if callable(expected) else actual == expected
        self.checks.append(dict(label=label, passed=passed, actual=clean(actual)))
        if not passed:
            print('FAIL', label, repr(actual), flush=True)

    def conf(self, label, text):
        path = self.path / (label + '.conf')
        path.write_text(text)
        return path

    def modes(self):
        return ['redis'] if self.oracle else ['1s', '2s']

    def password(self, server, password, label):
        with server.client() as c:
            self.check(label + ' NOAUTH before AUTH', c.cmd('PING'), lambda v: is_error(v, 'NOAUTH'))
            self.check(label + ' unauthenticated SET refused', c.cmd('SET', 'cg4-auth', 'value'),
                       lambda v: is_error(v, 'NOAUTH'))
            self.check(label + ' full AUTH', c.cmd('AUTH', password), b'OK')
            self.check(label + ' full CONFIG GET', c.cmd('CONFIG', 'GET', 'requirepass'),
                       [b'requirepass', password])
            self.check(label + ' authenticated PING', c.cmd('PING'), b'PONG')
            self.check(label + ' RESET', c.cmd('RESET'), b'RESET')
            self.check(label + ' prefix refused', c.cmd('AUTH', password.split(b'\0')[0]),
                       lambda v: is_error(v, 'WRONGPASS'))

    def config_nul(self):
        for mode in self.modes():
            for name, password, escaped in [('embedded', b'cg4\0tail', r'cg4\x00tail'),
                                            ('leading', b'\0tail', r'\x00tail')]:
                label = mode + '-' + name
                conf = self.conf(label, 'requirepass "' + escaped + '"\n')
                with Server(self, label, mode, conf) as s:
                    self.password(s, password, label)
            # CLI override must replace the length as well as the bytes, including explicit off.
            for name, password in [('override', b'cli-password'), ('empty', b'')]:
                label = mode + '-' + name
                with Server(self, label, mode, conf, ['--requirepass', password]) as s, s.client() as c:
                    if password:
                        self.check(label + ' AUTH', c.cmd('AUTH', password), b'OK')
                    self.check(label + ' PING', c.cmd('PING'), b'PONG')
                    self.check(label + ' GET', c.cmd('CONFIG', 'GET', 'requirepass'),
                               [b'requirepass', password])

    def arity(self):
        for mode in self.modes():
            self.arity_mode(mode)

    def arity_mode(self, mode):
        for suffix, tail in [('final', ''), ('middle', 'bind 127.0.0.1\n')]:
            label = mode + '-requirepass-' + suffix
            conf = self.conf(label, 'requirepass cg4-required\nrequirepass\n' + tail)
            with Server(self, label, mode, conf, refusal=True) as s:
                self.check(label + ' no listener', s.booted, False)
                self.check(label + ' exit 1', s.process.poll(), 1)
            log = (s.path / 'server.log').read_text()
            self.check(label + ' wrong-number error', log.lower(),
                       lambda v: 'wrong number of arguments' in v)
        # Every next("") candidate from config.h, plus the nonempty default string paths.
        names = ['tls-cert-file', 'tls-key-file', 'tls-ca-cert-file', 'tls-ca-cert-dir',
                 'tls-protocols', 'tls-ciphers', 'tls-ciphersuites', 'unixsocket', 'aclfile',
                 'latency-monitor-threshold', 'ratio', 'shard-home', 'place',
                 'dir', 'dbfilename', 'appendfilename', 'appenddirname']
        for name in names:
            label = mode + '-missing-' + name
            conf = self.conf(label, name + '\n')
            with Server(self, label, mode, conf, refusal=True) as s:
                self.check(label + ' no listener', s.booted, False)
                self.check(label + ' exit 1', s.process.poll(), 1)
            log = (s.path / 'server.log').read_text().lower()
            # The three Tomo-only placement options are unknown to Redis 7.4.
            reason = 'bad directive or wrong number of arguments' if self.oracle and name in (
                'ratio', 'shard-home', 'place') else 'wrong number of arguments'
            self.check(label + ' diagnostic', log, lambda v: reason in v)

    def rewrite(self):
        for mode in self.modes():
            for name, password in [('leading', b'\0audit-suffix'), ('embedded', b'audit\0suffix')]:
                label = mode + '-' + name
                conf = self.conf(label, '# authfix rewrite fixture\n')
                directory = self.path / (label + '-data')
                directory.mkdir()
                with Server(self, label + '-before', mode, conf, directory=directory) as s, s.client() as c:
                    self.check(label + ' SET', c.cmd('CONFIG', 'SET', 'requirepass', password), b'OK')
                    self.password(s, password, label + '-before')
                    self.check(label + ' REWRITE', c.cmd('CONFIG', 'REWRITE'), b'OK')
                lines = [line for line in conf.read_text().splitlines() if line.startswith('requirepass')]
                self.check(label + ' escaped bytes persisted', lines,
                           lambda v: len(v) == 1 and password.replace(b'\0', b'\\x00').decode() in v[0])
                with Server(self, label + '-after', mode, conf, directory=directory) as s:
                    self.password(s, password, label + '-after')

    def slowlog(self, mode):
        redacted = b'(redacted)'
        with Server(self, 'slowlog-' + mode, mode, extra=['--slowlog-log-slower-than', '0']) as s, s.client() as c:
            self.check('set password', c.cmd('CONFIG', 'SET', 'requirepass', 'audit-password'), b'OK')
            cases = [
                (('AUTH', 'audit-password'), [b'AUTH', redacted]),
                (('AUTH', 'default', 'audit-password'), [b'AUTH', redacted, redacted]),
                (('AUTH', 'bad-password'), [b'AUTH', redacted]),
                (('HELLO', 2, 'AUTH', 'default', 'audit-password'),
                 [b'HELLO', b'2', b'AUTH', redacted, redacted]),
                (('HELLO', 3, 'SETNAME', 'AUTH', 'AUTH', 'default', 'audit-password'),
                 [b'HELLO', b'3', b'SETNAME', b'AUTH', b'AUTH', redacted, redacted]),
                (('CONFIG', 'SET', 'requirepass', 'audit-password'),
                 [b'CONFIG', b'SET', b'requirepass', redacted]),
                (('CONFIG', 'SET', 'timeout', '0', 'requirepass', 'audit-password'),
                 [b'CONFIG', b'SET', b'timeout', b'0', b'requirepass', redacted]),
                (('ACL', 'SETUSER', 'authfix-user', 'on', '>fixture-secret', '~*', '+get'),
                 [b'ACL', b'SETUSER'] + [redacted] * 5),
                (('SET', 'authfix-visible', 'audit-password'),
                 [b'SET', b'authfix-visible', b'audit-password']),
            ]
            for index, (command, expected) in enumerate(cases):
                # RESET clears every owner. Re-arm on fresh state if a split executor had not
                # entered per-op capture yet. A missing entry after bounded retries is a FAIL.
                entries = []
                for attempt in range(4):
                    assert c.cmd('AUTH', 'audit-password') == b'OK'
                    assert c.cmd('SLOWLOG', 'RESET') == b'OK'
                    assert c.cmd('SET', 'authfix-witness', index) == b'OK'
                    reply = c.cmd(*command)
                    if command[0] == 'AUTH' and command[1] == 'bad-password':
                        self.check('failed AUTH executed', reply, lambda v: is_error(v, 'WRONGPASS'))
                    elif command[0] == 'HELLO':
                        self.check('HELLO executed', reply, lambda v: isinstance(v, list))
                    else:
                        self.check('command executed ' + str(index), reply, b'OK')
                    deadline = time.monotonic() + .15
                    while time.monotonic() < deadline:
                        rows = c.cmd('SLOWLOG', 'GET', -1)
                        entries = [row[3] for row in rows if row[3][0].upper() == expected[0]
                                   and (expected[0] != b'SET' or row[3][1] == b'authfix-visible')]
                        if entries:
                            break
                        time.sleep(.01)
                    if entries:
                        break
                self.check('capture witness ' + str(index), bool(entries), True)
                self.check('redacted argv ' + str(index), entries,
                           lambda v: bool(v) and all(argv == expected for argv in v))
                self.rows[str(index)] = dict(command=command, argv=entries, attempts=attempt + 1)

    def finish(self):
        result = dict(binary=str(self.binary), sha256=hashlib.file_digest(self.binary.open('rb'), 'sha256').hexdigest(),
                      checks=self.checks, slowlog=self.rows)
        (self.path / 'results.json').write_text(json.dumps(clean(result), indent=2) + '\n')
        return sum(not c['passed'] for c in self.checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--oracle')
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--case', required=True, choices=['config-nul', 'arity', 'rewrite', 'slowlog-1s', 'slowlog-2s'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    failures = 0
    for binary, oracle in ([(args.oracle, True)] if args.oracle else []) + [(args.binary, False)]:
        run = Run(args, binary, oracle)
        try:
            if args.case.startswith('slowlog-'):
                run.slowlog('redis' if oracle else args.case.split('-')[1])
            else:
                getattr(run, args.case.replace('-', '_'))()
        finally:
            failures += run.finish()
    print(f'authfix {args.case}: {failures} failed checks; evidence {args.output}', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
