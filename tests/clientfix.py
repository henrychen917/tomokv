#!/usr/bin/env python3
"""Round-4 clientfix regressions, adapted from the owner-provided audit probes.

Each case owns its listener. PRE must fail the same assertions POST passes.
No hardcoded CPU set or binary; gate geometry is eight cores / 16 shards / 6:2.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import random
import select
import socket
import subprocess
import tempfile
import time

class Error(str): pass
class Push(list): pass

def plain(x):
    if isinstance(x, Error): return {'error': str(x)}
    if isinstance(x, Push): return {'push': [plain(v) for v in x]}
    if isinstance(x, bytes): return x.decode('utf-8', 'backslashreplace')
    if isinstance(x, list): return [plain(v) for v in x]
    if isinstance(x, dict): return {str(plain(k)): plain(v) for k,v in x.items()}
    return x

def enc(args):
    args = [a if isinstance(a, bytes) else str(a).encode() for a in args]
    return b'*%d\r\n'%len(args)+b''.join(b'$%d\r\n'%len(a)+a+b'\r\n' for a in args)
class Conn:
    def __init__(self, port):
        self.s=socket.create_connection(('127.0.0.1',port),2); self.s.settimeout(2)
        self.buf=bytearray(); self.pushes=[]
    def __enter__(self): return self
    def __exit__(self,*a): self.s.close()
    def close(self): self.s.close()
    def take(self,n):
        while len(self.buf)<n:
            b=self.s.recv(65536)
            if not b: raise EOFError('peer closed')
            self.buf.extend(b)
        out=bytes(self.buf[:n]); del self.buf[:n]; return out
    def line(self):
        while b'\r\n' not in self.buf:
            b=self.s.recv(65536)
            if not b: raise EOFError('peer closed')
            self.buf.extend(b)
        n=self.buf.index(b'\r\n'); return self.take(n+2)[:-2]
    def read(self):
        tag=self.take(1); v=self.line()
        if tag==b'+': return v
        if tag==b'-': return Error(v.decode())
        if tag==b':': return int(v)
        if tag in (b'$', b'='):
            n=int(v)
            if n<0: return None
            b=self.take(n); assert self.take(2)==b'\r\n'; return b
        if tag in (b'*', b'~', b'>'):
            n=int(v)
            if n<0: return None
            out=[self.read() for _ in range(n)]; return Push(out) if tag==b'>' else out
        if tag==b'%': return {self.read():self.read() for _ in range(int(v))}
        if tag==b'_': return None
        if tag==b'#': return v==b't'
        if tag==b',': return float(v)
        raise ValueError((tag,v))
    def cmd(self,*args):
        self.s.sendall(enc(args))
        while True:
            r=self.read()
            if isinstance(r,Push): self.pushes.append(r)
            else: return r
    def pipe(self,commands):
        self.s.sendall(b''.join(enc(c) for c in commands)); out=[]
        while len(out)<len(commands):
            r=self.read()
            if isinstance(r,Push): self.pushes.append(r)
            else: out.append(r)
        return out
    def drain(self,timeout=.15):
        out=self.pushes; self.pushes=[]; deadline=time.monotonic()+timeout
        while self.buf or select.select([self.s],[],[],max(0,deadline-time.monotonic()))[0]:
            out.append(self.read())
            if time.monotonic()>=deadline and not self.buf: break
        return out


def emit(**data):
    print(json.dumps(plain(data), sort_keys=True), flush=True)


@contextlib.contextmanager
def server(args, atomic=0, read_local=0):
    check = subprocess.run(['ss', '-ltnH', 'sport', '=', str(args.port)],
                           capture_output=True, text=True, check=True)
    assert not check.stdout.strip(), f'port {args.port} occupied'
    runtime = Path(__file__).resolve().parents[1] / 'build/clientfix/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='clientfix-', dir=runtime) as directory:
        command = ['taskset', '-c', args.cores, str(Path(args.binary).resolve()),
                   '--bind', '127.0.0.1', '--port', str(args.port), '--save', '',
                   '--appendonly', 'no', '--dir', directory]
        if not args.oracle:
            command += ['--shards', '16', '--thread-mode', args.mode,
                        '--read-local', str(read_local), '--atomic', str(atomic),
                        '--flip-auto', '0', '--enable-debug-command', 'yes']
            if args.mode == '2s':
                command += ['--ratio', args.ratio]
        command += getattr(args, 'extra_flags', [])
        log_path = Path(directory) / 'server.log'
        with log_path.open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        emit(lifecycle='start', pid=process.pid, command=command,
             load=Path('/proc/loadavg').read_text().strip())
        try:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, log_path.read_text()
                try:
                    with Conn(args.port) as conn:
                        assert conn.cmd('PING') == b'PONG'
                    break
                except (ConnectionRefusedError, TimeoutError):
                    assert time.monotonic() < deadline, log_path.read_text()
                    time.sleep(.03)
            yield args.port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            emit(lifecycle='stop', pid=process.pid, exit=process.returncode,
                 load=Path('/proc/loadavg').read_text().strip())
            if process.returncode != 0:
                print(log_path.read_text(), flush=True)
            assert process.returncode == 0, 'server did not exit cleanly'


def tracking_cap(port):
    keys = [f'clientfix:cap:{i}' for i in range(1100)]
    with Conn(port) as track, Conn(port) as writer:
        track.cmd('HELLO', 3)
        assert track.cmd('CLIENT', 'TRACKING', 'ON') == b'OK'
        assert track.cmd('MGET', *keys) == [None] * len(keys)
        assert writer.cmd('MSET', *[arg for key in keys for arg in (key, 'v')]) == b'OK'
        frames = track.drain(.5)
        invalidated = {key for frame in frames if isinstance(frame, Push)
                       and frame[0] == b'invalidate' and frame[1] is not None
                       for key in frame[1]}
        missing = set(key.encode() for key in keys) - invalidated
        emit(case='tracking-cap', tracked=len(keys), invalidated=len(invalidated),
             missing=len(missing), sample=sorted(missing)[:5])
        assert not missing, f'{len(missing)} cached nonexistent keys survived MSET'


def tracking_pipeline(port):
    failures = []
    for attempt in range(20):
        key = f'clientfix:pipeline:{attempt}'
        with Conn(port) as track, Conn(port) as writer:
            track.cmd('HELLO', 3)
            assert track.cmd('CLIENT', 'TRACKING', 'ON', 'NOLOOP') == b'OK'
            assert track.cmd('GET', key) is None
            replies = track.pipe([['SET', key, 'v'], ['GET', key]])
            assert replies == [b'OK', b'v'], replies
            own = track.drain(.01)
            assert own == [], own
            assert writer.cmd('SET', key, 'v2') == b'OK'
            frames = track.drain(.1)
            if frames != [Push([b'invalidate', [key.encode()]])]:
                failures.append({'attempt': attempt, 'frames': frames})
    emit(case='tracking-pipeline', attempts=20, failures=failures)
    assert not failures, 'later GET registration lost to earlier NOLOOP SET'


def reply_skip(port, oracle=False):
    targets = [('PING',), ('GET', 'clientfix:k'), ('WAIT', 0, 0),
               ('SCRIPT', 'EXISTS', 'a' * 40), ('FUNCTION', 'LIST'),
               ('BLPOP', 'clientfix:nolist', '.05'),
               ('XREAD', 'BLOCK', 50, 'STREAMS', 'clientfix:nostream', '$')]
    if not oracle:
        targets.append(('FLIP', 'invalid', 'invalid'))
    failures = []
    for target in targets:
        for shape in ('older', 'pipelined', 'separate'):
            with Conn(port) as conn:
                conn.s.settimeout(5)
                assert conn.cmd('SET', 'clientfix:k', 'v') == b'OK'
                for attempt in range(20):
                    sentinel = f'end-{attempt}'.encode()
                    skip = enc(['CLIENT', 'REPLY', 'SKIP'])
                    if shape == 'separate':
                        conn.s.sendall(skip)
                        time.sleep(.005)
                        prefix = b''
                    else:
                        prefix = (enc(['GET', 'clientfix:k']) if shape == 'older' else b'') + skip
                    conn.s.sendall(prefix + enc(target) + enc(['ECHO', sentinel]))
                    got = []
                    while not got or got[-1] != sentinel:
                        got.append(conn.read())
                        assert len(got) < 10, got
                    expected = ([b'v'] if shape == 'older' else []) + [sentinel]
                    if got != expected:
                        failures.append({'target': target, 'shape': shape,
                                         'attempt': attempt, 'replies': got})
    # WB4.13: a retry must not produce duplicate MONITOR lines either.
    with Conn(port) as monitor, Conn(port) as conn:
        assert monitor.cmd('MONITOR') == b'OK'
        commands = [['GET', 'clientfix:k'], ['WAIT', 0, 0],
                    ['BLPOP', 'clientfix:nolist', '.05'], ['ECHO', 'monitor-end']]
        assert conn.pipe(commands) == [b'v', 0, None, b'monitor-end']
        lines = monitor.drain(.2)
        counts = {name: sum(isinstance(line, bytes) and b'"' + name.encode() + b'"' in line
                           for line in lines) for name in ('WAIT', 'BLPOP')}
    emit(case='reply-skip', targets=len(targets), repetitions=20,
         failures=len(failures), sample=failures[:5], monitor=counts)
    assert not failures, 'CLIENT REPLY SKIP leaked the retried command reply'
    assert counts == {'WAIT': 1, 'BLPOP': 1}, counts


def pattern_cleanup(port):
    with Conn(port) as keep, Conn(port) as admin:
        assert keep.cmd('PSUBSCRIBE', 'keep:*') == [b'psubscribe', b'keep:*', 1]
        assert admin.cmd('PUBLISH', 'keep:one', 'before') == 1
        assert keep.read() == [b'pmessage', b'keep:*', b'keep:one', b'before']
        with Conn(port) as drop:
            assert drop.cmd('SUBSCRIBE', 'drop') == [b'subscribe', b'drop', 1]
            assert drop.cmd('RESET') == b'RESET'
        assert admin.cmd('PUBSUB', 'NUMSUB', 'drop') == [b'drop', 0]
        assert admin.cmd('PUBSUB', 'NUMPAT') == 1
        count = admin.cmd('PUBLISH', 'keep:one', 'after')
        frames = keep.drain(.1)
        empty_count = admin.cmd('PUBLISH', '', 'empty')
        empty_frames = keep.drain(.1)
        emit(case='pattern-cleanup', count=count, frames=frames,
             empty_count=empty_count, empty_frames=empty_frames)
        assert count == 1 and frames == [[b'pmessage', b'keep:*', b'keep:one', b'after']]
        assert empty_count == 0 and empty_frames == []


def pause_deadline(port):
    with Conn(port) as admin:
        for attempt in range(3):
            assert admin.cmd('CLIENT', 'UNPAUSE') == b'OK'
            with Conn(port) as writer:
                start = time.monotonic()
                assert admin.cmd('CLIENT', 'PAUSE', 1000, 'WRITE') == b'OK'
                assert admin.cmd('CLIENT', 'PAUSE', 100, 'WRITE') == b'OK'
                writer.s.sendall(enc(['SET', f'clientfix:pause:{attempt}', 'v']))
                ready = bool(select.select([writer.s], [], [], .3)[0])
                observed = time.monotonic() - start
                reply = writer.read()
                completed = time.monotonic() - start
            assert admin.cmd('CLIENT', 'UNPAUSE') == b'OK'
            if observed >= .7:
                continue  # fresh pause and writer; never pass an unobserved window
            emit(case='pause-deadline', ready=ready, observed=observed,
                 completed=completed, reply=reply, attempt=attempt)
            assert not ready and reply == b'OK', 'shorter PAUSE replaced the original deadline'
            # The server floors its clock to milliseconds when setting the deadline.
            assert completed >= 1.0 - .001, 'SET escaped before the original 1000 ms deadline'
            break
        else:
            raise AssertionError('original PAUSE deadline window never witnessed')


def geo_count(port, store=False):
    rng = random.Random(4242)
    points = []
    for index in range(300):
        points += [round(rng.uniform(-.5, .5), 6), round(rng.uniform(-.5, .5), 6), f'p{index}']
    failures = []
    with Conn(port) as conn:
        assert conn.cmd('GEOADD', 'clientfix:geo', *points) == 300
        for index in range(20):
            lon, lat = round(rng.uniform(-.4, .4), 4), round(rng.uniform(-.4, .4), 4)
            options = ['FROMLONLAT', lon, lat, 'BYRADIUS', 100, 'km', 'COUNT', 5]
            expected = conn.cmd('GEOSEARCH', 'clientfix:geo', *options, 'ASC')
            assert len(expected) == 5
            if store:
                assert conn.cmd('GEOSEARCHSTORE', 'clientfix:dst', 'clientfix:geo', *options) == 5
                got = conn.cmd('ZRANGE', 'clientfix:dst', 0, -1)
                radius = conn.cmd('GEORADIUS', 'clientfix:geo', lon, lat, 100, 'km',
                                  'COUNT', 5, 'STORE', 'clientfix:radius')
                assert radius == 5
                other = conn.cmd('ZRANGE', 'clientfix:radius', 0, -1)
                equal = set(got) == set(expected) == set(other)
            else:
                got = conn.cmd('GEOSEARCH', 'clientfix:geo', *options)
                other = conn.cmd('GEORADIUS', 'clientfix:geo', lon, lat, 100, 'km', 'COUNT', 5)
                equal = got == expected == other
            if not equal:
                failures.append({'center': index, 'expected': expected, 'got': got, 'radius': other})
        # Explicit descending order and ANY remain valid independent options.
        query = ['GEOSEARCH', 'clientfix:geo', 'FROMLONLAT', 0, 0, 'BYRADIUS', 100, 'km']
        assert conn.cmd(*query, 'COUNT', 5, 'DESC') == conn.cmd(*query, 'DESC')[:5]
        assert len(conn.cmd(*query, 'COUNT', 5, 'ANY')) == 5
    emit(case='geo-store' if store else 'geo-count', centers=20,
         failures=len(failures), sample=failures[:1])
    assert not failures, 'COUNT without ANY did not select the nearest members'


CASES = ('tracking-cap', 'tracking-pipeline', 'reply-skip', 'pattern-cleanup',
         'pause-deadline', 'geo-count', 'geo-store')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--case', choices=CASES, required=True)
    parser.add_argument('--oracle', action='store_true')
    args = parser.parse_args()
    axes = [(0, 0)]
    if not args.oracle and args.case.startswith('tracking-'):
        axes += [(1, 0), (1, 1)]
    failures = []
    for atomic, read_local in axes:
        try:
            with server(args, atomic, read_local) as port:
                if args.case == 'reply-skip':
                    reply_skip(port, args.oracle)
                elif args.case.startswith('geo-'):
                    geo_count(port, args.case == 'geo-store')
                else:
                    globals()[args.case.replace('-', '_')](port)
        except AssertionError as exc:
            failures.append(dict(atomic=atomic, read_local=read_local, error=str(exc)))
    if failures:
        emit(result='FAIL', case=args.case, mode=args.mode, failures=failures)
        raise SystemExit(1)
    emit(result='PASS', case=args.case, mode=args.mode, axes=axes)


if __name__ == '__main__':
    main()
