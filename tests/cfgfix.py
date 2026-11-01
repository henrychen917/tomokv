#!/usr/bin/env python3
"""CONFIG oracle receipts; called by gate.sh's cfgfix job, with all engine/mode legs."""
from contextlib import closing
import json
from pathlib import Path
import re
import socket

import _netfix as n


def plain(value):
    if isinstance(value, n._lib.RespError):
        return {'error': str(value)}
    if isinstance(value, bytes):
        return value.decode('utf-8', 'backslashreplace')
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def test(a, port, certs, proc, oracle):
    replies = []
    with closing(n.connect(port)) as c:
        def command(*args):
            result = c.cmd(*args)
            replies.append([list(args), plain(result)])
            return result

        # Keep the complete map for the inventory, including explicit hidden queries.
        visible = c.must('CONFIG', 'GET', '*')
        (a.output / ('oracle' if oracle else f'candidate-{proc.pid}') ).with_suffix('.configs.json').write_text(
            json.dumps(dict(zip(map(plain, visible[::2]), map(plain, visible[1::2]))), indent=2))
        reference_source = Path(a.oracle).parent / 'config.c'
        standard = reference_source.read_text().split('standardConfig static_configs[] = {')[1].split('/* NULL Terminator')[0]
        names = set(re.findall(r'create\w+Config\("([^"]+)"', standard))
        names.update(re.findall(r'create\w+Config\("[^"]+", "([^"]+)"', standard))
        explicit = {name: plain(c.must('CONFIG', 'GET', name)) for name in sorted(names)}
        (a.output / ('oracle' if oracle else f'candidate-{proc.pid}')).with_suffix('.explicit.json').write_text(
            json.dumps(explicit, indent=2))
        for args in (
            ('GET', 'key-load-delay'), ('GET', 'key-load-*'),
            ('GET', 'key-load-delay', 'key-load-*', 'key-load-delay'),
            ('GET', 'daemonize', 'logfile', 'syslog-*', 'loglevel', 'supervised'),
            ('SET', 'daemonize', 'yes'), ('SET', 'logfile', 'anything'),
            ('SET', 'maxmemory', 'bad'),
            ('SET', 'maxmemory', '12345678', 'timeout', 'bad'),
            ('GET', 'maxmemory', 'timeout'),
            ('SET', 'maxmemory', '12345678', 'timeout'),
            ('SET', 'TIMEOUT', '1', 'timeout', '2'),
            ('SET', 'maxmemory', 'bad', 'daemonize', 'yes'),
            ('SET', 'list-max-listpack-size', '-6'),
            ('SET', 'shutdown-on-sigterm', 'nosave now'),
            ('GET', 'shutdown-on-sigterm'),
            ('SET', 'shutdown-on-sigint', 'save force'),
            ('GET', 'shutdown-on-sigint'),
            ('SET', 'shutdown-on-sigint', 'save nosave'),
            ('SET', 'shutdown-on-sigint', 'default now'),
            ('SET', 'shutdown-on-sigint', 'default'),
            ('SET', 'shutdown-on-sigterm', 'default'),
            ('SET', 'tls-auth-clients', 'optional'),
            ('GET', 'tls-auth-clients'), ('SET', 'tls-auth-clients', 'yes'),
            ('SET', 'loglevel', 'warning\0ignored'), ('GET', 'loglevel'),
            ('SET', 'loglevel', 'notice'), ('SET', 'loglevel', 'invalid'),
            ('SET', 'key-load-delay', '01'), ('SET', 'key-load-delay', '2147483648'),
            ('SET', 'maxmemory', '12345678', 'locale-collate', 'no_such_locale'),
            ('GET', 'maxmemory', 'locale-collate'),
        ):
            command('CONFIG', *args)
        for flags in ('AKEn', 'nAKE', 'AKE', 'AKEmn', 'n', 'g$lnKE', ''):
            command('CONFIG', 'SET', 'notify-keyspace-events', flags)
            command('CONFIG', 'GET', 'notify-keyspace-events')
        c.must('DEL', 'cfgfix:list')
        c.must('RPUSH', 'cfgfix:list', 'x' * 60000)
        command('OBJECT', 'ENCODING', 'cfgfix:list')
        c.must('RPUSH', 'cfgfix:list', 'x' * 5536)
        command('OBJECT', 'ENCODING', 'cfgfix:list')
        # Redis GET serializes AKEn as AKE too. The raw configured n bit must
        # survive that lossy display format and actually publish new events.
        c.must('DEL', 'cfgfix:new')
        c.must('CONFIG', 'SET', 'notify-keyspace-events', 'AKEn')
        with closing(n.connect(port)) as sub:
            assert sub.must('PSUBSCRIBE', '__key*__:*')[0] == b'psubscribe'
            c.must('SET', 'cfgfix:new', 'value')
            messages = []
            try:
                for _ in range(4):
                    messages.append(plain(sub.read()))
            except (TimeoutError, OSError):
                pass
            replies.append([['notification-events', 'AKEn'], sorted(messages)])
        c.must('CONFIG', 'SET', 'notify-keyspace-events', '')
        with closing(socket.socket()) as occupied:
            occupied.bind(('127.0.0.1', port + 2))
            occupied.listen()
            command('CONFIG', 'SET', 'maxmemory', '12345678', 'port', str(port + 2),
                    'client-query-buffer-limit', '10m')
            command('CONFIG', 'GET', 'maxmemory', 'client-query-buffer-limit')
            # A fresh connection must still reach the original listener after failure.
            with closing(n.connect(port)) as fresh:
                assert fresh.must('PING') == b'PONG'
        # Keep this connection across successful changes, including a disabled
        # TCP listener, and verify every new endpoint from a fresh connection.
        command('CONFIG', 'SET', 'port', str(port + 1))
        with closing(n.connect(port + 1)) as fresh:
            assert fresh.must('PING') == b'PONG'
        command('CONFIG', 'SET', 'port', '0')
        assert c.must('PING') == b'PONG'
        command('CONFIG', 'SET', 'port', str(port))
        with closing(n.connect(port)) as fresh:
            assert fresh.must('PING') == b'PONG'
        if not oracle and proc.args[proc.args.index('--thread-mode') + 1] == '2s':
            # Rebind listener homes transferred by FLIP, then transfer them
            # again. Existing connections and fresh accepts must both survive.
            for io_threads in (4, 6):
                c.must('FLIP', str(io_threads), str(8 - io_threads))
                c.must('CONFIG', 'SET', 'port', str(port + 1))
                with closing(n.connect(port + 1)) as fresh:
                    assert fresh.must('PING') == b'PONG'
                c.must('CONFIG', 'SET', 'port', str(port))
                with closing(n.connect(port)) as fresh:
                    assert fresh.must('PING') == b'PONG'
        # Only sorted key/value pairs are compared; Redis hash-table order is unspecified.
        for args, result in replies:
            if args[:2] == ['CONFIG', 'GET'] and isinstance(result, list):
                result[:] = sorted(zip(result[::2], result[1::2]))
    path = a.output / 'oracle-replies.json'
    if oracle:
        path.write_text(json.dumps(replies, indent=2))
    else:
        # JSON normalizes tuples and binds a complete receipt even on PRE failures.
        replies = json.loads(json.dumps(replies))
        expected = json.loads(path.read_text())
        differences = [dict(command=old[0], oracle=old[1], candidate=new[1])
                       for old, new in zip(expected, replies) if old != new]
        (a.output / f'differences-{proc.pid}.json').write_text(json.dumps(differences, indent=2))
        assert not differences, json.dumps(differences, indent=2)
    return len(replies)


if __name__ == '__main__':
    n.matrix(n.arguments(), test, tls=False)
