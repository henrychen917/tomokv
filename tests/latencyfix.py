#!/usr/bin/env python3
"""LAT-HIST-1: one oracle battery, including grammar, wire shapes and off allocations.

Every gate row executes both modes and both engines at the gate geometry. Durations
are never compared: only command/call accounting, CDF structure and percentile keys.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import traceback

from authfix import Run, Server as AuthServer, is_error
from _lib import encode

class Server:
    """A fresh boot may reroll within its gate slot's three reserved ports.

    These ports overlap Linux's ephemeral client range. A stopped listener can
    race a foreign outbound socket/TIME_WAIT; preserve that failed boot and try
    a fresh process on the next reserved port. No command assertion is retried.
    """
    def __init__(self, run, label, mode, **kwargs):
        self.run, self.label, self.mode, self.kwargs = run, label, mode, kwargs

    def __enter__(self):
        base = self.run.args.port
        for attempt in range(3):
            self.run.args.port = base + attempt
            try:
                self.server = AuthServer(self.run, self.label + f'-port{attempt}',
                                         self.mode, **self.kwargs)
                return self.server.__enter__()
            except AssertionError as error:
                if 'Address already in use' not in str(error) and 'occupied port' not in str(error):
                    raise
                if attempt == 2:
                    raise
            finally:
                self.run.args.port = base
        raise AssertionError('port arming exhausted')

    def __exit__(self, *args):
        return self.server.__exit__(*args)


KNOB = 'latency-tracking-info-percentiles'


def pairs(value):
    assert isinstance(value, list) and len(value) % 2 == 0, value
    return list(zip(value[::2], value[1::2]))


def histogram(c, *names, protocol=2):
    c.sock.sendall(encode('LATENCY', 'HISTOGRAM', *names))
    assert c.file.peek(1)[:1] == (b'%' if protocol == 3 else b'*'), 'histogram wire type'
    value = c.read()
    out = []
    for name, raw in pairs(value):
        fields = dict(pairs(raw))
        assert set(fields) == {b'calls', b'histogram_usec'}, fields
        calls = fields[b'calls']
        bins = pairs(fields[b'histogram_usec'])
        assert isinstance(calls, int) and calls > 0 and bins
        prior_key, prior_count = 0, 0
        for key, count in bins:
            assert isinstance(key, int) and key > prior_key, bins
            assert key in {((2 ** n) + (2 ** (n - 7)) - 1) // 1000 for n in range(10, 30)} | {1073741}, bins
            assert isinstance(count, int) and prior_count < count <= calls, bins
            prior_key, prior_count = key, count
        assert prior_count == calls, bins
        out.append((name.decode(), calls))
    return out


def percentile_keys(c):
    info = c.cmd('INFO', 'latencystats')
    if isinstance(info, bytes):
        info = info.removeprefix(b'txt:')
    assert isinstance(info, bytes) and info.startswith(b'# Latencystats\r\n'), info
    result = {}
    for line in info.decode().splitlines():
        if not line.startswith('latency_percentiles_usec_'):
            continue
        key, values = line.split(':', 1)
        entries = values.split(',') if values else []
        for item in entries:
            assert re.fullmatch(r'p-?\d+(?:\.\d+)?=\d+\.\d{3}', item), item
        result[key.removeprefix('latency_percentiles_usec_')] = [v.split('=')[0] for v in entries]
    return result


def oracle_equal(run, key, value):
    if run.oracle:
        run.reference[key] = value
    else:
        run.check(key, value, run.reference[key])


def grammar(run, mode, label, extra):
    with Server(run, label, mode, extra=extra) as server, server.client() as c:
        run.check(label + ' explicit default deviation', c.cmd('CONFIG', 'GET', 'latency-tracking'),
                  [b'latency-tracking', b'yes' if run.oracle else b'no'])
        run.check(label + ' percentiles default', c.cmd('CONFIG', 'GET', KNOB), [KNOB.encode(), b'50 99 99.9'])
        for name, values in [
            ('latency-tracking', ['yes', 'no', 'YES', 'No', '', '1', '0', 'true', 'yes ', b'yes\0tail']),
            (KNOB, ['50 99 99.9', '', '100 0 50 50 99.1234567', '-0 +0 1e1 0x1p2',
                    ' 50', '50 ', '50  99', '50\t99', 'nan', 'inf', '-1', '100.01',
                    '1e-9999', '0.00000001', b'50\0 99', '00', '1e-310'])]:
            for index, value in enumerate(values):
                c.cmd('CONFIG', 'SET', name, 'no' if name == 'latency-tracking' else '50 99 99.9')
                reply = c.cmd('CONFIG', 'SET', name, value)
                retained = c.cmd('CONFIG', 'GET', name)
                oracle_equal(run, f'{name}:{index}', [reply, retained])
        for command in [('CONFIG', 'SET', KNOB, '1', KNOB.upper(), '2'),
                        ('CONFIG', 'SET', KNOB, '1', 'timeout', 'bad'),
                        ('CONFIG', 'SET', KNOB, '50', '99'),
                        ('CONFIG', 'SET', 'latency-tracking', 'bad', 'no-such-knob', 'x')]:
            oracle_equal(run, repr(command), c.cmd(*command))

    for index, (values, expected) in enumerate([
            ('50 99 99.9', b'50 99 99.9'), ('100 0 25.125 25.125', b'100 0 25.125 25.125'),
            ('""', b''), ('', b''), ('" 50  99.1234567 "', b'50 99.123457')]):
        conf = run.conf(label + f'-file-{index}',
                        'latency-tracking yes\n' + KNOB + ' ' + values + '\n')
        for restart in range(2):
            with Server(run, label + f'-file-{index}-{restart}', mode, conf=conf, extra=extra) as server:
                with server.client() as c:
                    run.check(label + ' file tracking', c.cmd('CONFIG', 'GET', 'latency-tracking'),
                              [b'latency-tracking', b'yes'])
                    run.check(label + ' file percentiles', c.cmd('CONFIG', 'GET', KNOB),
                              [KNOB.encode(), expected])
                    run.check(label + ' rewrite', c.cmd('CONFIG', 'REWRITE'), b'OK')
        text = conf.read_text()
        canonical = expected.decode() if expected else '""'
        run.check(label + ' rewrite directive', KNOB + ' ' + canonical in text, True)


def shape(run, mode, label, extra):
    with Server(run, label, mode, extra=extra + ['--latency-tracking', 'yes']) as server:
        with server.client() as c:
            for protocol in (2, 3):
                c.cmd('HELLO', protocol)
                run.check(label + ' reset', c.cmd('CONFIG', 'RESETSTAT'), b'OK')
                assert c.cmd('SET', 'latencyfix:key', '0') == b'OK'
                for command in [('GET', 'latencyfix:key'), ('INCR', 'latencyfix:key')]:
                    c.sock.sendall(encode(*command) * 32)
                    for _ in range(32):
                        assert not is_error(c.read(), '')
                assert is_error(c.cmd('INCR', 'latencyfix:bad', 'extra'), 'ERR')
                assert is_error(c.cmd('no-such-latency-command'), 'ERR')
                selected = histogram(c, 'GET', 'sEt', 'incr', 'no-such-command', protocol=protocol)
                oracle_equal(run, f'basic:{protocol}', sorted(selected))
                assert dict(selected) == {'get': 32, 'set': 1, 'incr': 32}, selected
                duplicate = histogram(c, 'GET', 'get', protocol=protocol)
                oracle_equal(run, f'duplicate:{protocol}', duplicate)
                assert duplicate == [('get', 32), ('get', 32)], duplicate
                assert histogram(c, 'no-such-command', protocol=protocol) == []
                assert histogram(c, 'get|unknown', protocol=protocol) == []
                for command in [('CLIENT', 'ID'), ('CLIENT', 'GETNAME'), ('COMMAND', 'COUNT'),
                                ('CONFIG', 'GET', 'latency-tracking')]:
                    c.cmd(*command)
                for selector in ('client', 'CLIENT|ID', 'command|count', 'config|get'):
                    rows = histogram(c, selector, protocol=protocol)
                    assert rows, selector
                    oracle_equal(run, f'subcommand:{protocol}:{selector}', sorted(rows))
                for command in [('CONFIG', 'unknown-latency-child'),
                                ('LATENCY', 'unknown-latency-child'),
                                ('CLIENT', 'unknown-latency-child')]:
                    assert is_error(c.cmd(*command), 'ERR')
                all_rows = dict(histogram(c, protocol=protocol))
                assert not {'config', 'latency', 'client'} & set(all_rows), all_rows
                assert {'get', 'set', 'incr', 'latency|histogram', 'client|id'} <= set(all_rows), all_rows
                keys = percentile_keys(c)
                for name in ('get', 'set', 'incr', 'client|id', 'command|count'):
                    assert keys[name] == ['p50', 'p99', 'p99.9'], keys
                for value, expected in [('99.9 0 100 50 50', ['p99.9', 'p0', 'p100', 'p50', 'p50']),
                                        ('', [])]:
                    assert c.cmd('CONFIG', 'SET', KNOB, value) == b'OK'
                    keys = percentile_keys(c)
                    assert keys['get'] == expected, keys
                c.cmd('CONFIG', 'SET', KNOB, '50 99 99.9')
                before = histogram(c, 'get', 'set', 'incr', protocol=protocol)
                c.cmd('LATENCY', 'RESET')
                assert histogram(c, 'get', 'set', 'incr', protocol=protocol) == before
                assert c.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'
                c.cmd('GET', 'latencyfix:key')
                assert histogram(c, 'get', 'set', 'incr', protocol=protocol) == before
                assert percentile_keys(c) == {}
                assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
                assert histogram(c, protocol=protocol) == []
                c.cmd('CONFIG', 'SET', 'latency-tracking', 'yes')
                # A cold configuration publication may take one executor pass.
                for _ in range(4):
                    c.cmd('GET', 'latencyfix:key')
                assert dict(histogram(c, 'get', protocol=protocol)).get('get', 0) > 0
            c.cmd('CONFIG', 'RESETSTAT')
            c.cmd('EVAL', "return redis.call('GET', KEYS[1])", 1, 'latencyfix:key')
            rows = dict(histogram(c, 'eval', 'get', protocol=3))
            run.check(label + ' nested script is a command', rows, {'eval': 1, 'get': 1})
            c.cmd('CONFIG', 'RESETSTAT')
            c.cmd('MULTI')
            c.cmd('GET', 'latencyfix:key')
            c.cmd('INCR', 'latencyfix:key')
            c.cmd('EXEC')
            rows = dict(histogram(c, 'get', 'incr', 'exec', protocol=3))
            run.check(label + ' EXEC child commands', rows, {'get': 1, 'incr': 1, 'exec': 1})


def execution_paths(run, mode, label, extra):
    armed = extra + ['--latency-tracking', 'yes', '--enable-debug-command', 'yes']
    if not run.oracle:
        armed += ['--read-local', '1']
    with Server(run, label + '-paths', mode, extra=armed) as server, server.client() as c:
        keys = ['latencyfix:cross:' + str(i) for i in range(24)]
        if not run.oracle:
            from _lib import shard_of, topology
            topo = topology(c)
            by_owner = {}
            for key in keys:
                by_owner.setdefault(topo.shard_owner[shard_of(c, key)], key)
            assert len(by_owner) >= 2, 'cross-owner window never opened'
            keys = list(by_owner.values())[:2]
        else:
            keys = keys[:2]
        c.cmd('SET', keys[0], '1')
        c.cmd('SET', keys[1], '2')
        cases = [
            ('cross', [('MSET', keys[0], '1', keys[1], '2'), ('MGET', *keys),
                       ('EXISTS', *keys), ('DBSIZE',), ('KEYS', '*')],
             ['mset', 'mget', 'exists', 'dbsize', 'keys']),
            ('blocking-timeout', [('BLPOP', 'latencyfix:empty', '.01')], ['blpop']),
            ('wait-timeout', [('WAIT', 1, 1)], ['wait']),
            ('exec-cross', [('MULTI',), ('MGET', *keys), ('MSET', keys[0], '3', keys[1], '4'),
                            ('EXEC',)], ['multi', 'exec', 'mget', 'mset']),
            ('exec-controls', [('MULTI',), ('PING',), ('ECHO', 'v'), ('CLIENT', 'ID'), ('EXEC',)],
             ['multi', 'exec', 'ping', 'echo', 'client|id']),
            ('local-read', [('GET', keys[0]), ('GET', keys[0]), ('MGET', keys[0])],
             ['get', 'mget']),
        ]
        for name, commands, selectors in cases:
            assert c.cmd('CONFIG', 'RESETSTAT') == b'OK'
            for command in commands:
                reply = c.cmd(*command)
                assert not is_error(reply, ''), (command, reply)
            actual = sorted(histogram(c, *selectors))
            oracle_equal(run, 'path:' + name, actual)
        c.cmd('CONFIG', 'SET', 'latency-tracking', 'no', 'slowlog-log-slower-than', '-1')
        c.cmd('CONFIG', 'RESETSTAT')
        c.cmd('CONFIG', 'SET', 'latency-tracking', 'yes')
        oracle_equal(run, 'path:enable-command', sorted(histogram(c, 'config|set')))
        c.cmd('CONFIG', 'RESETSTAT')
        c.cmd('LPUSH', 'latencyfix:pop', 'v')
        c.cmd('BLPOP', 'latencyfix:pop', '0')
        oracle_equal(run, 'path:blocking-ready', sorted(histogram(c, 'blpop', 'lpush')))


@contextlib.contextmanager
def allocations(run, label):
    if run.oracle:
        yield None
        return
    root = Path(__file__).resolve().parents[1]
    shim = root / 'build/latencyfix/alloc-trace.so'
    shim.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['g++', '-std=c++20', '-O2', '-fPIC', '-shared',
                    str(root / 'tests/serverfix_alloc.cc'), '-o', str(shim), '-ldl'], check=True)
    path = run.path / (label + '-allocations.log')
    updates = dict(LD_PRELOAD=str(shim), TOMO_ALLOC_TRACE=str(path),
                   TOMO_ALLOC_BINARY=str(run.binary))
    old = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield path
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def off_allocations(run, mode, label, extra):
    with allocations(run, label) as path, Server(
            run, label, mode, extra=extra + ['--slowlog-log-slower-than', '-1']) as server:
        with server.client() as c:
            if run.oracle:
                c.cmd('CONFIG', 'SET', 'latency-tracking', 'no')
                c.cmd('CONFIG', 'RESETSTAT')
            run.check(label + ' tracking really off', c.cmd('CONFIG', 'GET', 'latency-tracking'),
                      [b'latency-tracking', b'no'])
            for i in range(32):
                with server.client() as other:
                    for command in [('SET', 'latencyfix:key', '1'), ('GET', 'latencyfix:key'),
                                    ('INCR', 'latencyfix:key')]:
                        assert not is_error(other.cmd(*command), '')
            assert histogram(c) == []
            if path:
                with path.open('a') as log:
                    log.write('MARK off\n')
            assert c.cmd('CONFIG', 'SET', 'latency-tracking', 'yes') == b'OK'
            for _ in range(4):
                c.cmd('GET', 'latencyfix:key')
            assert dict(histogram(c, 'get')).get('get', 0) > 0
            if path:
                with path.open('a') as log:
                    log.write('MARK on\n')
    if not path:
        return
    lines = path.read_text().splitlines()
    addresses = sorted({a for line in lines if line.startswith('N ') for a in line.split()[3:]})
    decoded = subprocess.check_output(['addr2line', '-a', '-f', '-C', '-i', '-e', str(run.binary)],
                                     input='\n'.join('0x' + a for a in addresses), text=True)
    symbols, address = {}, None
    for line in decoded.splitlines():
        if re.fullmatch(r'0x[0-9a-f]+', line):
            address = format(int(line, 16), 'x')
            symbols[address] = ''
        elif address:
            symbols[address] += line + '\n'
    count = 0
    receipt = {}
    for line in lines:
        fields = line.split()
        if fields[0] == 'N' and any(
                ('latency_tracking.cc:' in symbols.get(a, '') or
                 'latency_tracking_' in symbols.get(a, '')) for a in fields[3:]):
            count += 1
        if fields[0] == 'MARK':
            receipt[fields[1]] = count
    run.check(label + ' zero histogram allocations off', receipt.get('off'), 0)
    run.check(label + ' positive allocation control on', receipt.get('on', 0) > 0, True)
    (run.path / (label + '-allocation-counts.json')).write_text(json.dumps(receipt) + '\n')
    path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--oracle', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--case', choices=('grammar', 'shape', 'off'), required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    reference, failures = {}, 0
    probe = {'grammar': grammar, 'shape': shape, 'off': off_allocations}[args.case]
    for binary, oracle in [(args.oracle, True), (args.binary, False)]:
        run = Run(args, binary, oracle)
        run.reference = reference
        for mode in run.modes():
            for engine in (['redis'] if oracle else ['uring', 'epoll']):
                label = mode + '-' + engine
                try:
                    extra = [] if oracle else ['--net-io', engine]
                    probe(run, mode, label, extra)
                    if args.case == 'shape':
                        execution_paths(run, mode, label, extra)
                except Exception:
                    traceback.print_exc()
                    run.check(label + ' complete battery', False, True)
        failures += run.finish()
    print(f'LAT-HIST-1 {args.case}: {failures} failed checks; {args.output}', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
