#!/usr/bin/env python3
"""S1 script admission and CONFIG single-reply regressions; no rate assertions.

Every row uses fresh servers, the gate's 16-shard/6:2 geometry, both modes and
engines, both atomic/read-local settings, and both database namespaces. The Lua
wire scripts run unchanged on Redis 7.4. Limits account for the documented
per-shard budget on TomoKV; assertions compare replies and the entire keyspace.
CONFIG uses an external debugger schedule on the exact candidate ELF, so the
same deterministic witness can fail on the unmodified frozen release.
"""
import argparse
import contextlib
import hashlib
import itertools
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

from maxmemrace import Conn, port_open, server


ROOT = Path(__file__).resolve().parents[1]
SHARDS = 16
MIB = 1 << 20
OOM = b"-OOM command not allowed when used memory > 'maxmemory'."
ROTATE = "local v=redis.call('RPOP',KEYS[1]); redis.call('LPUSH',KEYS[1],v); return v"
GROW = ("for i=1,16 do redis.call('APPEND',KEYS[1],ARGV[1]) end "
        "return redis.call('STRLEN',KEYS[1])")


def expect(value, wanted):
    assert value == wanted, (value, wanted)
    return value


def snapshot(c):
    result = []
    for key in sorted(c.cmd('KEYS', '*')):
        kind = c.cmd('TYPE', key)
        if kind == b'+list':
            value = c.cmd('LRANGE', key, 0, -1)
        elif kind == b'+string':
            value = c.cmd('GET', key)
            value = (len(value), hashlib.sha256(value).hexdigest())
        else:
            raise AssertionError(('unexpected type', key, kind))
        result.append((key, kind, value))
    return result


def script_case(c, case, oracle):
    results = []

    def run(source, initial, limit, wanted, args=(), function=None):
        replies = []
        for command in (('FCALL',) if function else ('EVAL', 'EVALSHA')):
            expect(c.cmd('CONFIG', 'SET', 'maxmemory', 0), b'+OK')
            expect(c.cmd('FLUSHALL'), b'+OK')
            expect(c.cmd('CONFIG', 'SET', 'maxmemory-policy', 'noeviction'), b'+OK')
            if function:
                expect(c.cmd('FUNCTION', 'FLUSH'), b'+OK')
                library = ('#!lua name=s1pair\nredis.register_function{function_name="f", '
                           'callback=function(keys,args) ' + source + ' end, flags={' + function + '}}')
                expect(c.cmd('FUNCTION', 'LOAD', library), b's1pair')
                invocation = ('FCALL', 'f', 1, 'q', *args)
            else:
                digest = expect(c.cmd('SCRIPT', 'LOAD', source), hashlib.sha1(source.encode()).hexdigest().encode())
                invocation = (command, source if command == 'EVAL' else digest, 1, 'q', *args)
            if initial:
                expect(c.cmd('RPUSH', 'q', *initial), len(initial))
            expect(c.cmd('CONFIG', 'SET', 'maxmemory', limit), b'+OK')
            reply = c.cmd(*invocation)
            expect(c.cmd('CONFIG', 'SET', 'maxmemory', 0), b'+OK')
            image = snapshot(c)
            results.append((command, reply, image))
            # Log the actual reply AND image before asserting, including failures.
            print(repr(results[-1]), flush=True)
            replies.append(reply)
            if wanted == b'-OOM':
                results[-1] = (command, b'-OOM', image)
        for reply in replies:
            if wanted == b'-OOM':
                assert isinstance(reply, bytes) and reply.startswith(b'-OOM '), reply
            else:
                expect(reply, wanted)
        return results[-1][2]

    if case == 'EVAL-ROTATE':
        for initial in (('a', 'b', 'c'), ('c',)):
            image = run(ROTATE, initial, 1, b'c')
            expect(image, [(b'q', b'+list', [v.encode() for v in (initial[-1], *initial[:-1])])])
        # Redis marks WRITE_DIRTY before the handler, including a caught error.
        image = run("redis.pcall('HDEL',KEYS[1],'x'); return redis.call('LPUSH',KEYS[1],'z')",
                    ('a',), 1, 2)
        expect(image, [(b'q', b'+list', [b'z', b'a'])])
    elif case == 'EVAL-GROW':
        # Both start below their limits; 16 MiB exceeds Redis's total limit and
        # TomoKV's 4 MiB shard slice. The same script must complete all 16 writes.
        limit = 8 * MIB if oracle else 16 * 4 * MIB
        image = run(GROW, (), limit, 16 * MIB, (b'x' * MIB,))
        expect(image, [(b'q', b'+string', (16 * MIB, hashlib.sha256(b'x' * (16 * MIB)).hexdigest()))])
    elif case == 'EVAL-ADMISSION':
        # A first DENYOOM write remains refused, including after a read. Returning
        # pcall's error preserves the oracle's exact OOM frame without stack text.
        for prefix in ('', "redis.call('LLEN',KEYS[1]); "):
            image = run(prefix + "return redis.pcall('LPUSH',KEYS[1],'z')", ('a',), 1, OOM)
            expect(image, [(b'q', b'+list', [b'a'])])
        # A refused command does not mark dirty. A later non-DENYOOM write does.
        image = run("local e=redis.pcall('LPUSH',KEYS[1],'z'); "
                    "local f=redis.pcall('LPUSH',KEYS[1],'z'); "
                    "assert(e.err and f.err); " + ROTATE, ('a', 'b', 'c'), 1, b'c')
        expect(image, [(b'q', b'+list', [b'c', b'a', b'b'])])
        for header, body, wanted in (
                ('#!lua\n', "return 1", b'-OOM'),
                ('#!lua flags=allow-oom\n', "return redis.call('LPUSH',KEYS[1],'z')", 2),
                ('#!lua flags=no-writes\n', "return redis.call('LLEN',KEYS[1])", 1)):
            run(header + body, ('a',), 1, wanted)
        for flags, body, wanted in (
                (' ', "return 1", OOM),
                ('"allow-oom"', "return redis.call('LPUSH',keys[1],'z')", 2),
                ('"no-writes"', "return redis.call('LLEN',keys[1])", 1)):
            run(body, ('a',), 1, wanted, function=flags)
    else:
        raise AssertionError(case)
    return results


@contextlib.contextmanager
def scheduled_server(argv, cores, port, directory, databases):
    assert not port_open(port), port
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / 'schedule'
    env = dict(os.environ, LC_ALL='C', S1PAIR_GDB_OUTPUT=str(marker),
               S1PAIR_GDB_NAMESPACE='tomo_db0' if databases == 1 else 'tomo')
    cmd = ['taskset', '-c', cores, 'gdb', '-nx', '-q', '-batch',
           '-x', str(ROOT / 'tests/s1pair_loading.py'), '--args', *argv]
    (directory / 'argv.json').write_text(json.dumps(cmd) + '\n')
    with (directory / 'server.log').open('w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        deadline = time.monotonic() + 45
        while not port_open(port):
            assert proc.poll() is None, (directory / 'server.log').read_text()[-4000:]
            assert time.monotonic() < deadline, 'debugged server did not listen'
            time.sleep(.02)
        yield marker.with_suffix('.json')
    finally:
        if proc.poll() is None:
            pidfile = marker.with_suffix('.pid')
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                proc.kill()
                proc.wait()
        assert not port_open(port), 'debugged server still listens'


def config_case(c, marker):
    _, before = c.cmd('CONFIG', 'GET', 'slowlog-max-len')
    wanted = str(int(before) + 1).encode()
    command = ('CONFIG', 'SET', 'appendonly', 'no', 'slowlog-max-len', wanted)
    # Phase 1: every owner re-check sees the reload. One reply (the error),
    # nothing applied, and the next command's reply is still its own.
    reply = c.cmd(*command)
    ping = c.cmd('PING')
    print('phase 1: CONFIG reply=%r following PING=%r' % (reply, ping), flush=True)
    witness = json.loads(marker.read_text())
    print('schedule=' + json.dumps(witness), flush=True)
    assert len(witness) == 1 and witness[0]['io_checks'] == 1 and \
        witness[0]['owner_checks'] > 0 and witness[0]['assemblies'] == 1, witness
    expect(reply, b'-LOADING Redis is loading the dataset in memory')
    expect(ping, b'+PONG')
    expect(c.cmd('PING', 's1pair-aligned'), b's1pair-aligned')
    expect(c.cmd('CONFIG', 'GET', 'slowlog-max-len'), [b'slowlog-max-len', before])
    # Phase 2: the first owner fragment decided and applied the SET before the
    # reload began; the remaining SHARDS-1 re-checks see it. Applied means +OK.
    reply = c.cmd(*command)
    ping = c.cmd('PING')
    print('phase 2: CONFIG reply=%r following PING=%r' % (reply, ping), flush=True)
    witness = json.loads(marker.read_text())
    print('schedule=' + json.dumps(witness), flush=True)
    assert len(witness) == 2 and witness[1]['io_checks'] == 1 and \
        witness[1]['owner_checks'] == SHARDS and witness[1]['assemblies'] == 1, witness
    expect(reply, b'+OK')
    expect(ping, b'+PONG')
    expect(c.cmd('CONFIG', 'GET', 'slowlog-max-len'), [b'slowlog-max-len', wanted])
    expect(c.cmd('CONFIG', 'GET', 'appendonly'), [b'appendonly', b'no'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--case', required=True, choices=('EVAL-ROTATE', 'EVAL-GROW', 'EVAL-ADMISSION', 'CONFIG-OWNER'))
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    oracle_result = None
    if args.case != 'CONFIG-OWNER':
        folder = args.output / 'oracle'
        argv = [args.oracle, '--bind', '127.0.0.1', '--port', str(args.port),
                '--save', '', '--appendonly', 'no', '--dir', str(folder)]
        with server(argv, args.cores, args.port, folder), contextlib.closing(Conn(args.port)) as c:
            oracle_result = script_case(c, args.case, True)
    failed = []
    for mode, engine, atomic, read_local, databases in itertools.product(
            ('1s', '2s'), ('uring', 'epoll'), (0, 1), (0, 1), (1, 16)):
        label = f'{mode}-{engine}-a{atomic}-r{read_local}-db{databases}'
        print(label, flush=True)
        folder = args.output / label
        argv = [str(Path(args.binary).resolve()), '--bind', '127.0.0.1', '--port', str(args.port),
                '--shards', str(SHARDS), '--thread-mode', mode,
                '--net-io', engine, '--atomic', str(atomic), '--read-local', str(read_local),
                '--databases', str(databases), '--save', '', '--appendonly', 'no',
                '--enable-debug-command', 'yes', '--key-lb', '0', '--client-lb', '0',
                '--dir', str(folder)]
        if mode == '2s':
            argv += ['--ratio', args.ratio]
        try:
            if args.case == 'CONFIG-OWNER':
                with scheduled_server(argv, args.cores, args.port, folder, databases) as marker:
                    with contextlib.closing(Conn(args.port)) as c:
                        config_case(c, marker)
            else:
                with server(argv, args.cores, args.port, folder), contextlib.closing(Conn(args.port)) as c:
                    expect(script_case(c, args.case, False), oracle_result)
        except Exception:
            traceback.print_exc()
            failed.append(label)
    (args.output / 'result.json').write_text(json.dumps(dict(case=args.case, failed=failed), indent=2) + '\n')
    assert not failed, failed


if __name__ == '__main__':
    main()
