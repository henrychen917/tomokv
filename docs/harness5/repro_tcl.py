"""Minimal protocol reproductions for the classified Tcl differences.

Each case is a short command script replayed against a FRESH server per mode:
TomoKV 2s, TomoKV 1s and Redis 7.4.10. Replies keep their RESP type (simple vs
bulk string, push, map, double ...) so a type-only difference is visible. No
load generator; one connection per named client; every server is reaped.

Case file: {"CASE-ID": {"title": str, "steps": [STEP, ...],
                        "server_args": [...]?  (appended for every mode)}}
STEP is one of
  {"c": "a", "send": [argv...]}                 send, read one reply (2 s deadline)
  {"c": "a", "send": [argv...], "read": 0}      send only (blocking command)
  {"c": "a", "read": 1, "timeout": 1.0}         read one pending reply or TIMEOUT
  {"c": "a", "raw": "PING\\r\\n"}                 send raw bytes, read one reply
  {"sleep": 0.2}
  {"c": "a", "close": true}
Optional per step: "compare": false excludes a volatile reply (timestamps, ids)
from the verdict; it is still recorded. "normalize": [[REGEX, REPLACEMENT], ...]
rewrites every string in the reply before comparison (for example keeping only one
INFO field); the untouched reply is kept as "raw_reply".
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
REDIS = Path('/home/user/Projects/redis/src/redis-server')


class Timeout(Exception):
    pass


class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=2)
        self.buf = b''

    def send(self, argv):
        out = [b'*%d\r\n' % len(argv)]
        for value in argv:
            data = value.encode() if isinstance(value, str) else str(value).encode() \
                if not isinstance(value, bytes) else value
            out.append(b'$%d\r\n%s\r\n' % (len(data), data))
        self.sock.sendall(b''.join(out))

    def _fill(self, deadline):
        left = deadline - time.monotonic()
        if left <= 0:
            raise Timeout()
        self.sock.settimeout(left)
        try:
            data = self.sock.recv(65536)
        except socket.timeout:
            raise Timeout()
        if not data:
            raise EOFError('connection closed by server')
        self.buf += data

    def _line(self, deadline):
        while b'\r\n' not in self.buf:
            self._fill(deadline)
        line, self.buf = self.buf.split(b'\r\n', 1)
        return line

    def _bytes(self, size, deadline):
        while len(self.buf) < size + 2:
            self._fill(deadline)
        data, self.buf = self.buf[:size], self.buf[size + 2:]
        return data

    @staticmethod
    def text(data):
        try:
            return data.decode()
        except UnicodeDecodeError:
            return {'hex': data.hex()}

    def read(self, timeout=2.0):
        return self._value(time.monotonic() + timeout)

    def _value(self, deadline):
        line = self._line(deadline)
        head, body = line[:1], line[1:]
        if head == b'+':
            return {'simple': self.text(body)}
        if head == b'-':
            return {'error': self.text(body)}
        if head == b':':
            return int(body)
        if head == b'$':
            size = int(body)
            return None if size < 0 else self.text(self._bytes(size, deadline))
        if head == b'=':
            return {'verbatim': self.text(self._bytes(int(body), deadline))}
        if head in (b'*', b'~', b'>'):
            count = int(body)
            if count < 0:
                return None
            items = [self._value(deadline) for _ in range(count)]
            return items if head == b'*' else {'set' if head == b'~' else 'push': items}
        if head == b'%':
            return {'map': [[self._value(deadline), self._value(deadline)] for _ in range(int(body))]}
        if head == b'|':
            attrs = [[self._value(deadline), self._value(deadline)] for _ in range(int(body))]
            return {'attribute': attrs, 'value': self._value(deadline)}
        if head == b'_':
            return {'null3': True}
        if head == b',':
            return {'double': self.text(body)}
        if head == b'#':
            return {'bool': body == b't'}
        if head == b'(':
            return {'bignum': self.text(body)}
        raise ValueError('unknown RESP marker %r' % line[:20])

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def normalize(value, rules):
    if isinstance(value, str):
        for pattern, replacement in rules:
            value = re.sub(pattern, replacement, value)
        return value
    if isinstance(value, list):
        return [normalize(v, rules) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v, rules) for k, v in value.items()}
    return value


def boot(mode, binary, port, cores, ratio, extra, folder):
    folder.mkdir(parents=True, exist_ok=True)
    command = ['taskset', '-c', cores, str(binary), '--port', str(port), '--bind', '127.0.0.1',
               '--save', '', '--appendonly', 'no', '--dir', str(folder), '--enable-debug-command', 'yes']
    if mode != 'redis':
        command += ['--thread-mode', mode, '--shards', '16', '--databases', '16']
        if mode == '2s':
            command += ['--ratio', ratio]
    command += [str(a) for a in extra]
    log = (folder / 'server.log').open('w')
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                               env=dict(os.environ, LC_ALL='C'))
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError('server exited during boot: ' + (folder / 'server.log').read_text()[-500:])
        try:
            c = Client(port)
            c.send(['PING'])
            if c.read() == {'simple': 'PONG'}:
                c.close()
                return process, command
            c.close()
        except (OSError, EOFError, Timeout, ValueError):
            pass
        time.sleep(0.03)
    raise RuntimeError('server not ready')


def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def play(case, mode, binary, options, folder):
    process, command = boot(mode, binary, options.port, options.cores, options.ratio,
                            case.get('server_args', []), folder)
    clients, transcript = {}, []
    try:
        for step in case['steps']:
            row = dict(step)
            try:
                if 'sleep' in step:
                    time.sleep(step['sleep'])
                    transcript.append(row)
                    continue
                name = step.get('c', 'a')
                if step.get('close'):
                    clients.pop(name).close()
                    transcript.append(row)
                    continue
                if name not in clients:
                    clients[name] = Client(options.port)
                client = clients[name]
                if 'send' in step:
                    client.send(step['send'])
                elif 'raw' in step:
                    client.sock.sendall(step['raw'].encode())
                if step.get('read', 1):
                    try:
                        row['reply'] = client.read(step.get('timeout', 2.0))
                    except Timeout:
                        row['reply'] = 'TIMEOUT'
                    if step.get('normalize'):
                        row['raw_reply'] = row['reply']
                        row['reply'] = normalize(row['reply'], step['normalize'])
            except (EOFError, OSError) as error:
                row['reply'] = {'connection_error': str(error)}
            transcript.append(row)
    finally:
        for client in clients.values():
            client.close()
        stop(process)
    return dict(server_argv=command, transcript=transcript)


def verdict(results):
    def compared(mode):
        return [r.get('reply') for r in results[mode]['transcript']
                if r.get('compare', True) and ('send' in r or 'read' in r or 'raw' in r)]
    redis = compared('redis')
    return {mode: ('SAME' if compared(mode) == redis else 'DIFFERENT') for mode in ('2s', '1s')}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--only', default='')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    options = p.parse_args()
    cases = json.loads(options.cases.read_text())
    selected = [c for c in cases if not options.only or c in options.only.split(',')]
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    out = dict(binary_sha256=sha(options.binary), redis_sha256=sha(REDIS), cases={})
    if options.output.exists():
        out = json.loads(options.output.read_text())
    work = Path(tempfile.mkdtemp(prefix='h5repro-', dir=ROOT / 'build'))
    try:
        for ident in selected:
            case = cases[ident]
            results = {}
            for mode, binary in (('2s', options.binary), ('1s', options.binary), ('redis', REDIS)):
                try:
                    results[mode] = play(case, mode, binary, options, work / ident / mode)
                except Exception as error:  # infrastructure, never a verdict
                    results[mode] = dict(infrastructure_error=f'{type(error).__name__}: {error}', transcript=[])
            entry = dict(title=case.get('title', ''), steps=case['steps'],
                         server_args=case.get('server_args', []), results=results)
            if not any('infrastructure_error' in r for r in results.values()):
                entry['verdict'] = verdict(results)
            out['cases'][ident] = entry
            options.output.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
            print(ident, entry.get('verdict', 'INFRASTRUCTURE ERROR'), flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
