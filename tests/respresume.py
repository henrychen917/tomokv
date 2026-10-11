#!/usr/bin/env python3
"""NT4.2 wire fragmentation/work bounds; connects to already owned servers.

The gate owns boot/cleanup. No workload is run on import or by --help. Timing
rows are correctness bounds, never throughput evidence. The fragmentation row
also requires respresume-unit's deterministic no-replay witness (PRE fails it).
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import random
import signal
import socket
import ssl
import statistics
import threading
import time

from _lib import Conn, RespError, encode
from netcap import client_rows, wait_for


def raw_reply(f):
    line = f.readline()
    assert line.endswith(b'\r\n'), ('short reply', line)
    kind, n = line[:1], line[1:-2]
    if kind in (b'$', b'!', b'='):
        size = int(n)
        if size >= 0:
            data = f.read(size + 2)
            assert len(data) == size + 2, 'short bulk reply'
            line += data
    elif kind in (b'*', b'~', b'>', b'%', b'|'):
        for _ in range(max(0, int(n)) * (2 if kind in (b'%', b'|') else 1)):
            line += raw_reply(f)
    else:
        assert kind in (b'+', b'-', b':', b',', b'_', b'#', b'('), line
    return line


def exchange(endpoint, payload, replies, cuts, resp3, closes=False, tls=False):
    s = socket.create_connection(endpoint, timeout=5)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        s = context.wrap_socket(s, server_hostname='localhost')
    with s, s.makefile('rb') as f:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if resp3:
            s.sendall(encode('HELLO', 3))
            # HELLO's connection ID and server metadata are intentionally not
            # comparable. Compare every subsequent command's raw RESP3 bytes.
            assert raw_reply(f).startswith(b'%7\r\n'), 'HELLO 3 negotiation'
        s.sendall(encode('FLUSHDB'))
        assert raw_reply(f) == b'+OK\r\n'
        previous = 0
        for end in cuts:
            try:
                s.sendall(payload[previous:end])
            except (BrokenPipeError, ConnectionResetError):
                assert closes, 'unexpected close while sending valid frame'
                break
            previous = end
            if end != len(payload):
                time.sleep(.0005)
        result = b''.join(raw_reply(f) for _ in range(replies))
        if closes:
            try:
                trailing = f.read(1)
            except ConnectionResetError:
                trailing = b''
            assert trailing == b'', ('missing protocol-error close', trailing)
        else:
            s.sendall(encode('PING'))
            assert raw_reply(f) == b'+PONG\r\n', 'pipeline boundary/connection lifetime'
        return result


def corpus():
    # Deterministic representatives of the differential suites' command
    # families. Whole and split trials each start from FLUSHDB on a fresh client.
    commands = [
        [('PING',)], [('ECHO', '')], [('SET', 'k', b'a\r\n\0b'), ('GET', 'k')],
        [('INCRBYFLOAT', 'k', '.25')], [('MSET', 'a', '1', 'b', '2'), ('MGET', 'a', 'b')],
        [('SADD', 's', 'v'), ('SMEMBERS', 's')], [('LPUSH', 'l', 'v'), ('LRANGE', 'l', 0, -1)],
        [('HSET', 'h', 'f', 'v'), ('HGETALL', 'h')], [('HSET', 'h', 'f', 'v'), ('HTTL', 'h', 'FIELDS', 1, 'f')],
        [('ZADD', 'z', 1, 'v'), ('ZRANGE', 'z', 0, -1, 'WITHSCORES')],
        [('ZUNIONSTORE', 'out', 1, 'z')], [('GEOADD', 'geo', 0, 0, 'v'), ('GEOPOS', 'geo', 'v')],
        [('XADD', 'x', '1-0', 'f', 'v'), ('XRANGE', 'x', '-', '+')],
        [('XGROUP', 'CREATE', 'x', 'g', '0', 'MKSTREAM')],
        [('SETBIT', 'k', 8, 1), ('BITCOUNT', 'k')], [('BITFIELD', 'k', 'SET', 'u8', 0, 7)],
        [('PFADD', 'hll', 'v'), ('PFCOUNT', 'hll')], [('EVAL', 'return ARGV[1]', 0, 'v')],
        [('FUNCTION', 'LIST')], [('MULTI',), ('SET', 'k', 'v'), ('EXEC',)],
        [('WATCH', 'k'), ('UNWATCH',)], [('LMOVE', 'a', 'b', 'LEFT', 'RIGHT')],
        [('SADD', 'small', 'a'), ('SSCAN', 'small', 0)], [('SORT', 'empty')], [('EXISTS', 'empty'), ('TYPE', 'empty')],
        [('EXPIRE', 'empty', 10)], [('DUMP', 'empty')], [('RESTORE', 'k', 0, 'invalid')],
        [('GET',)], [('HELLO', 'invalid')], [('SELECT', 0)], [('DBSIZE',)],
        [('CLIENT', 'SETNAME', 'respresume'), ('CLIENT', 'GETNAME')],
        [('CONFIG', 'GET', 'appendonly')], [('PUBSUB', 'NUMSUB', 'none')],
        [('PUBLISH', 'none', 'message')], [('ACL', 'WHOAMI')], [('COMMAND', 'GETKEYS', 'GET', 'k')],
        [('BLPOP',)], [('SUBSCRIBE',)], [('SSUBSCRIBE',)], [('MONITOR', 'invalid')],
        [('CONFIG', 'GET', 'notify-keyspace-events')], [('SAVE', 'invalid')],
        [('GET', 'none'), ('RESET',), ('PING',)],
    ]
    for i, group in enumerate(commands):
        yield f'family-{i}', b''.join(encode(*c) for c in group), len(group), False
    yield 'inline', b'PING\r\n', 1, False
    yield 'empty-array-pipeline', b'*0\r\n' + encode('PING') + b'*0\r\n', 1, False
    for a in range(4):
        prefix = b'*4\r\n' + b'$1\r\na\r\n' * a
        for bad in (b'!\r\n', b'$x\r\n', b'$-1\r\n', b'$00\r\n'):
            yield f'error-{a}-{bad!r}', prefix + bad, 1, True
    for bad in (b'*x\r\n', b'*2147483648\r\n', b'*00\r\n'):
        yield f'array-{bad!r}', bad, 1, True


def fragmented(args):
    endpoint = (args.host, args.port)
    oracle = (args.host, args.oracle_port)
    count = 0
    for resp3 in (False, True):
        for label, payload, replies, closes in corpus():
            expected = exchange(oracle, payload, replies, [len(payload)], resp3, closes)
            whole = exchange(endpoint, payload, replies, [len(payload)], resp3, closes, args.tls)
            assert whole == expected, (label, resp3, 'whole differs from Redis', whole, expected)
            for cut in range(1, len(payload)):
                actual = exchange(endpoint, payload, replies, [cut, len(payload)], resp3, closes, args.tls)
                reference = exchange(oracle, payload, replies, [cut, len(payload)], resp3, closes)
                assert actual == expected == reference, (label, resp3, cut, actual, expected, reference)
                count += 1
        for n in (1, 2, 10, 1023, 1024, 1025, (1 << 20)-1, 1 << 20, (1 << 20)+1):
            payload = trickle_frame(n)
            whole = exchange(endpoint, payload, 1, [len(payload)], resp3, tls=args.tls)
            expected = exchange(oracle, payload, 1, [len(payload)], resp3)
            assert whole == expected, (n, resp3, 'whole')
            for seed in (7, 19, 20, 23):
                rng = random.Random(seed)
                cuts = sorted(set([1, len(payload), *[rng.randrange(1, len(payload)) for _ in range(16)]]))
                assert exchange(endpoint, payload, 1, cuts, resp3, tls=args.tls) == expected
                assert exchange(oracle, payload, 1, cuts, resp3) == expected
                count += 1
        for n in (0, 1, 16383, 16384, 16385, 32767, 32768, 32769):
            payload = encode('ECHO', b'v' * n)
            cuts = [1, 4, len(payload)-2, len(payload)-1, len(payload)]
            expected = exchange(oracle, payload, 1, [len(payload)], resp3)
            assert exchange(endpoint, payload, 1, cuts, resp3, tls=args.tls) == expected
            count += 1
    print(json.dumps(dict(fragment_trials=count, seeds=[7, 19, 20, 23], result='PASS')))


def trickle_frame(n):
    return b'*%d\r\n$4\r\nPING\r\n' % n + b'$1\r\na\r\n' * (n-1)


def cpu_seconds(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


def cpu_bound(args):
    samples = []
    payload = trickle_frame(args.cpu_args)
    for _ in range(3):
        with closing(Conn(args.host, args.port, timeout=15)) as c:
            start = cpu_seconds(args.pid)
            for i in range(0, len(payload), 2048):
                c.raw(payload[i:i+2048]); time.sleep(.0005)
            reply = c.read()
            assert reply == RespError("ERR wrong number of arguments for 'ping' command"), reply
            samples.append(cpu_seconds(args.pid)-start)
    value = statistics.median(samples)
    print(json.dumps(dict(cpu_seconds=samples, median=value, limit=args.cpu_limit)), flush=True)
    assert value < args.cpu_limit, 'T12 median server CPU bound'


def neighbour(args):
    with closing(Conn(args.host, args.port, timeout=15)) as b:
        assert b.must('CONFIG', 'GET', 'client-lb') == [b'client-lb', b'0'], 'freeze owners'
        owner = b.must('DEBUG', 'IO-THREAD')
        a = None
        for _ in range(128):
            c = Conn(args.host, args.port, timeout=15)
            if c.must('DEBUG', 'IO-THREAD') == owner:
                a = c
                break
            c.close()
        assert a is not None, 'no same-owner neighbour found; cannot skip'
        with closing(a):
            ident = a.must('CLIENT', 'ID')
            payload = trickle_frame(2000000)
            # Prove the incomplete frame is buffered before collecting samples.
            a.raw(payload[:65536])
            wait_for(lambda: int(client_rows(b).get(ident, {}).get(b'qbuf', b'-1')) == 65536,
                     'partial 2M-argument frame never opened')
            samples, failures = [], []
            stop = threading.Event()
            def pinger():
                try:
                    while not stop.is_set():
                        start = time.perf_counter()
                        assert b.must('PING') == b'PONG'
                        samples.append((time.perf_counter()-start)*1000)
                        time.sleep(.001)
                except BaseException as error:
                    failures.append(repr(error))
            worker = threading.Thread(target=pinger)
            worker.start()
            try:
                for i in range(65536, len(payload), 65536):
                    a.raw(payload[i:i+65536]); time.sleep(.002)
                assert a.read() == RespError("ERR wrong number of arguments for 'ping' command")
            finally:
                stop.set(); worker.join(15)
            assert not worker.is_alive() and not failures, failures
            assert len(samples) >= 10, ('neighbour sample count', len(samples))
            median = statistics.median(samples)
            print(json.dumps(dict(owner=owner, pings=len(samples), median_ms=median,
                                  max_ms=max(samples), limit_ms=args.median_ms)), flush=True)
            assert median < args.median_ms, 'T12b neighbour median bound'
            assert a.must('DEBUG', 'IO-THREAD') == b.must('DEBUG', 'IO-THREAD') == owner


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('case', choices=['fragment', 'cpu', 'neighbour'])
    ap.add_argument('host')
    ap.add_argument('port', type=int)
    ap.add_argument('--oracle-port', type=int)
    ap.add_argument('--pid', type=int)
    # Correctness bounds, not speed claims. Measured on the gate's 1s/2s x epoll/uring boots
    # (8 server cores): POST median 0.02-0.05 s per trickled 400k frame and 0.022 ms neighbour
    # median; PRE 0.69-0.72 s and 5.3-7.9 ms. Each bound sits ~3x / 5x from PRE and POST.
    ap.add_argument('--cpu-args', type=int, default=400000)
    ap.add_argument('--cpu-limit', type=float, default=.2)
    ap.add_argument('--median-ms', type=float, default=1)
    ap.add_argument('--tls', action='store_true')
    args = ap.parse_args()
    def expired(_signal, _frame):
        raise TimeoutError('respresume row exceeded its fixed 55-second deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(55)
    if args.case == 'fragment':
        assert args.oracle_port, 'fragmentation requires an independent Redis oracle'
        fragmented(args)
    elif args.case == 'cpu':
        assert args.pid, 'CPU witness needs the owned server PID'
        cpu_bound(args)
    else:
        neighbour(args)


if __name__ == '__main__': main()
