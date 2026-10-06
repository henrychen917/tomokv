#!/usr/bin/env python3
"""AT15 wire witnesses. Import compare() from differ's MULTI suite; never starts a server."""
import argparse
import io
import socket


def encode(args):
    values = [str(arg).encode() for arg in args]
    return b'*%d\r\n' % len(values) + b''.join(
        b'$%d\r\n' % len(value) + value + b'\r\n' for value in values)


def read_frame(file):
    line = file.readline()
    if not line.endswith(b'\r\n'):
        raise AssertionError('truncated RESP header')
    marker = line[:1]
    if marker in (b'+', b'-', b':', b'_', b'#'):
        return line
    count = int(line[1:-2])
    if marker in (b'$', b'='):
        if count == -1:
            return line
        body = file.read(count + 2)
        assert len(body) == count + 2 and body.endswith(b'\r\n'), 'truncated bulk'
        return line + body
    if marker in (b'*', b'>', b'%', b'~'):
        return line + b''.join(read_frame(file) for _ in range(max(0, count) * (2 if marker == b'%' else 1)))
    raise AssertionError('unknown RESP marker: %r' % marker)


class Connection:
    def __init__(self, host, port, resp3=False):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.file = self.sock.makefile('rb')
        self.resp3 = resp3
        if resp3:
            assert self.command(['HELLO', '3']).startswith(b'%7\r\n')

    def command(self, args):
        self.sock.sendall(encode(args))
        return read_frame(self.file)

    def close(self):
        self.file.close()
        self.sock.close()


def info_element(wire, resp3=False):
    """Dynamic INFO contents may differ; RESP type, length and section identity may not."""
    prefix = b'*1\r\n=' if resp3 else b'*1\r\n$'
    assert wire.startswith(prefix), ('INFO EXEC element type', wire[:100])
    end = wire.index(b'\r\n', len(prefix))
    count = int(wire[len(prefix):end])
    body = wire[end + 2:]
    assert len(body) == count + 2 and body.endswith(b'\r\n'), 'INFO exact frame length'
    body = body[:-2]
    if resp3:
        assert body.startswith(b'txt:'), 'INFO verbatim tag'
        body = body[4:]
    return body


def transaction(connection, commands):
    assert connection.command(['MULTI']) == b'+OK\r\n'
    for command in commands:
        assert connection.command(command) == b'+QUEUED\r\n', ('not queued', command)
    return connection.command(['EXEC'])


def witness(connection):
    out = []
    for command in (['INFO'], ['INFO', 'server'], ['INFO', 'all'], ['INFO', 'keyspace'],
                    ['INFO', 'server', 'keyspace'], ['INFO', 'no-such-section']):
        body = info_element(transaction(connection, [command]), connection.resp3)
        sections = set(line for line in body.split(b'\r\n') if line.startswith(b'# '))
        if len(command) == 1 or command[1] == 'all':
            assert {b'# Server', b'# Keyspace'} <= sections
        elif command[1:] == ['server']:
            assert sections == {b'# Server'} and b'redis_version:' in body
        elif command[1:] == ['keyspace']:
            assert sections == {b'# Keyspace'}
        elif command[1:] == ['server', 'keyspace']:
            assert sections == {b'# Server', b'# Keyspace'}
        else:
            assert body == b''
        # INFO has server-specific sections and counters. The above validates required sections
        # on EACH arm before recording its wire type for comparison.
        out.append((tuple(command), 'verbatim' if connection.resp3 else 'bulk'))
    out.append(('sleep', transaction(connection, [['DEBUG', 'SLEEP', '0']])))
    assert out[-1][1] == b'*1\r\n+OK\r\n'
    assert connection.command(['MULTI']) == b'+OK\r\n'
    nested = connection.command(['MULTI'])
    watch = connection.command(['WATCH', 'at15:watched'])
    assert nested == b'-ERR MULTI calls can not be nested\r\n'
    assert watch == b'-ERR WATCH inside MULTI is not allowed\r\n'
    assert connection.command(['PING']) == b'+QUEUED\r\n'
    result = connection.command(['EXEC'])
    assert result == b'*1\r\n+PONG\r\n', 'nested MULTI/WATCH do not dirty EXEC'
    out.append(('controls', nested, watch, result))
    assert connection.command(['MULTI']) == b'+OK\r\n'
    save = connection.command(['SAVE'])
    result = connection.command(['EXEC'])
    assert save == b'-ERR Command not allowed inside a transaction\r\n'
    assert result == b'-EXECABORT Transaction discarded because of previous errors.\r\n'
    out.append(('no_multi', save, result))
    # Deterministic ConfigRoute ordering, including a runtime error which must remain an element.
    result = transaction(connection, [['CONFIG', 'GET', 'at15-no-such-setting'],
                                      ['CONFIG', 'RESETSTAT'], ['DEBUG', 'SLEEP', '0']])
    assert result == (b'*3\r\n%0\r\n+OK\r\n+OK\r\n' if connection.resp3
                      else b'*3\r\n*0\r\n+OK\r\n+OK\r\n')
    out.append(('admin', result))
    return out


def subscription_policy(connection, oracle=False):
    """Explicit group-5 difference: Redis permits it; TomoKV currently refuses it."""
    assert not connection.resp3
    assert connection.command(['MULTI']) == b'+OK\r\n'
    queued = connection.command(['SUBSCRIBE', 'at15:channel'])
    result = connection.command(['EXEC'])
    if oracle:
        assert queued == b'+QUEUED\r\n'
        assert result == b'*1\r\n*3\r\n$9\r\nsubscribe\r\n$12\r\nat15:channel\r\n:1\r\n'
        assert connection.command(['RESET']) == b'+RESET\r\n'
    else:
        assert queued == b'-ERR Command not allowed inside a transaction\r\n'
        assert result == b'-EXECABORT Transaction discarded because of previous errors.\r\n'
    return queued, result


def compare(target_host, target_port, oracle_host, oracle_port, resp3=False):
    target = Connection(target_host, target_port, resp3)
    oracle = Connection(oracle_host, oracle_port, resp3)
    try:
        assert witness(target) == witness(oracle), 'AT15 differential replies'
    finally:
        target.close()
        oracle.close()
    print('  AT15: INFO sections, DEBUG SLEEP, controls and admin replies agree (RESP%d)' % (3 if resp3 else 2))


def self_test():
    for wire in (b'*1\r\n$0\r\n\r\n', b'*1\r\n=4\r\ntxt:\r\n'):
        assert info_element(wire, b'=' in wire) == b''
    rejected = 0
    for wire in (b'*1\r\n-ERR command is not supported by MULTI execution\r\n',
                 b'$0\r\n\r\n', b'*0\r\n', b'*1\r\n$5\r\nx\r\n',
                 b'*1\r\n$0\r\n\r\n+OK\r\n'):
        try:
            info_element(wire)
        except (AssertionError, ValueError):
            rejected += 1
    assert rejected == 5
    print('PASS AT15 wire validator: five broken reply controls rejected')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--target', nargs=2, metavar=('HOST', 'PORT'))
    parser.add_argument('--oracle', nargs=2, metavar=('HOST', 'PORT'))
    parser.add_argument('--subscription-policy', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        assert args.target, '--target HOST PORT required'
        if args.oracle:
            for resp3 in (False, True):
                compare(*args.target, *args.oracle, resp3)
        else:
            for resp3 in (False, True):
                connection = Connection(*args.target, resp3)
                try:
                    witness(connection)
                finally:
                    connection.close()
        if args.subscription_policy:
            for endpoint, oracle in ((args.target, False), (args.oracle, True)):
                if endpoint:
                    connection = Connection(*endpoint)
                    try:
                        print('POLICY group 5', 'Redis' if oracle else 'TomoKV', subscription_policy(connection, oracle))
                    finally:
                        connection.close()
