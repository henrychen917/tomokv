#!/usr/bin/env python3
"""Raw Redis-oracle line replies and subsequent-command synchronization, no load test."""
import argparse
import itertools
import json
from pathlib import Path
import socket
import sys
import traceback

from _lib import encode
from authfix import Run, Server


def cases():
    # The clean twin locks ordinary bytes; the others exercise both delimiters,
    # mixed delimiters and Redis's distinct trailing-newline policies.
    for suffix, text in [('clean', b'X'), ('cr', b'X\r+INJECTED'),
                         ('lf', b'X\n+INJECTED'), ('crlf', b'X\r\n+INJECTED'),
                         ('trailing', b'X\r\n'), ('edges', b'\r\nX\n\r')]:
        commands = {
            'function-list': ('FUNCTION', 'LIST', text),
            'function-load-option': ('FUNCTION', 'LOAD', text, 'code'),
            'unknown-command': (text, 'arg'),
            'unknown-command-arg': ('no-such-command', text),
            'config-name': ('CONFIG', 'SET', text, '0'),
            'config-value': ('CONFIG', 'SET', 'maxmemory-policy', text),
            'acl-user': ('ACL', 'DRYRUN', text, 'PING'),
            'acl-command': ('ACL', 'DRYRUN', 'default', text),
            'acl-category': ('ACL', 'CAT', text),
            'acl-modifier': ('ACL', 'SETUSER', 'crlffix-user', b'+@' + text),
            'client-name': ('CLIENT', 'SETNAME', text),
            'hello-option': ('HELLO', '2', text),
            'stream-key': ('XPENDING', text, 'g'),
            'stream-group': ('XGROUP', 'CREATECONSUMER', 'crlffix-stream', text, 'c'),
            'stream-readgroup': ('XREADGROUP', 'GROUP', text, 'c', 'STREAMS', 'crlffix-stream', '>'),
            'geo-unit': ('GEODIST', 'crlffix-geo', 'a', 'b', text),
            'pfdebug-option': ('PFDEBUG', text, 'crlffix-hll'),
            'lua-error-table': ('EVAL', 'return {err=ARGV[1]}', '0', text),
            'lua-status-table': ('EVAL', 'return {ok=ARGV[1]}', '0', text),
            'lua-error-api': ('EVAL', 'return redis.error_reply(ARGV[1])', '0', text),
            'lua-status-api': ('EVAL', 'return redis.status_reply(ARGV[1])', '0', text),
            'lua-runtime-error': ('EVAL', 'error(ARGV[1])', '0', text),
            'script-compile-error': ('EVAL', b"return '" + text, '0'),
            'function-compile-error': ('FUNCTION', 'LOAD', b"#!lua name=crlffix_bad\nreturn '" + text),
            'function-call-name': ('FCALL', text, '0'),
            'library-name': ('FUNCTION', 'DELETE', text),
            'function-error': ('FCALL', 'crlffix_err', '0', text),
            'function-status': ('FCALL', 'crlffix_ok', '0', text),
            'function-runtime-error': ('FCALL', 'crlffix_raise', '0', text),
            'module-filter': ('COMMAND', 'LIST', 'FILTERBY', 'MODULE', text),
            'bulk-echo': ('ECHO', text),
            'bulk-script': ('EVAL', 'return ARGV[1]', '0', text),
        }
        for container in ('FUNCTION', 'SCRIPT', 'CLIENT', 'OBJECT', 'CONFIG',
                          'ACL', 'COMMAND', 'XGROUP', 'XINFO', 'MEMORY',
                          'SLOWLOG', 'PUBSUB', 'LATENCY'):
            commands['subcommand-' + container.lower()] = (container, text)
        for name, command in commands.items():
            yield name + ':' + suffix, encode(*command), False
    # Parser errors close the connection in Redis; verify exact error + EOF,
    # then a fresh connection's PING. They cannot promise same-socket recovery.
    yield 'inline-unbalanced', b'"bad\n+INJECTED\r\n', True
    for byte in (b'\r', b'\n'):
        yield 'resp-bulk-prefix:' + byte.hex(), b'*1\r\n' + byte + b'x\r\n', True


def read_raw(stream):
    line = stream.readline(1 << 20)
    if not line.endswith(b'\r\n'):
        raise AssertionError(('invalid/missing RESP line', line))
    tag, value = line[:1], line[1:-2]
    if tag in (b'$', b'='):
        size = int(value)
        if size >= 0:
            body = stream.read(size + 2)
            assert len(body) == size + 2 and body.endswith(b'\r\n'), body
            return line + body
    elif tag in (b'*', b'~', b'>', b'%'):
        count = max(0, int(value)) * (2 if tag == b'%' else 1)
        return line + b''.join(read_raw(stream) for _ in range(count))
    else:
        assert tag in (b'+', b'-', b':', b'_', b'#', b','), line
    return line


def wire(port, request, closes=False, database=0):
    with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
        with sock.makefile('rb') as stream:
            if database:
                sock.sendall(encode('SELECT', str(database)))
                assert read_raw(stream) == b'+OK\r\n'
            sock.sendall(request + encode('PING'))
            reply = read_raw(stream)
            if closes:
                following = stream.read(1)
                assert following == b'', ('protocol error did not close', following)
            else:
                following = read_raw(stream)
                # A third reply rejects a forged PONG that might otherwise pass.
                sock.sendall(encode('ECHO', 'crlffix-sync'))
                witness = read_raw(stream)
                assert witness == b'$12\r\ncrlffix-sync\r\n', witness
            return reply, following


def monitor(port, database):
    # MONITOR deliberately emits quoted, escaped client bytes in a status line.
    # Only its timestamp and peer address are variable; retain both raw lines.
    rows = {}
    with socket.create_connection(('127.0.0.1', port), timeout=3) as watch:
        with watch.makefile('rb') as stream:
            watch.sendall(encode('MONITOR'))
            assert read_raw(stream) == b'+OK\r\n'
            with socket.create_connection(('127.0.0.1', port), timeout=3) as client:
                with client.makefile('rb') as replies:
                    for text in (b'clean', b'X\r\n+INJECTED', b'\rX\n'):
                        client.sendall(encode('ECHO', text) + encode('PING'))
                        assert read_raw(replies) == b'$%d\r\n' % len(text) + text + b'\r\n'
                        assert read_raw(replies) == b'+PONG\r\n'
                        raw = [read_raw(stream), read_raw(stream)]
                        assert all(line.startswith(b'+') and b'] ' in line for line in raw), raw
                        rows[text.hex()] = {'raw': [line.hex() for line in raw],
                                            'payload': [line.split(b'] ', 1)[1].hex() for line in raw]}
    return rows


def probe(run, mode, label, extra, database):
    results = {}
    with Server(run, label, mode, extra=extra) as server:
        with server.client() as c:
            if database:
                assert c.cmd('SELECT', str(database)) == b'OK'
            assert c.cmd('XADD', 'crlffix-stream', '1-0', 'f', 'v') == b'1-0'
            assert c.cmd('GEOADD', 'crlffix-geo', '1', '2', 'a', '2', '3', 'b') == 2
            assert c.cmd('PFADD', 'crlffix-hll', 'v') == 1
            code = ("#!lua name=crlffix\n"
                    "redis.register_function('crlffix_err',function(k,a) return {err=a[1]} end)\n"
                    "redis.register_function('crlffix_ok',function(k,a) return {ok=a[1]} end)\n"
                    "redis.register_function('crlffix_raise',function(k,a) error(a[1]) end)")
            assert c.cmd('FUNCTION', 'LOAD', code) == b'crlffix'
        for name, request, closes in cases():
            try:
                reply, following = wire(server.port, request, closes, database)
                results[name] = {'reply': reply.hex(), 'following': following.hex()}
                assert closes or following == b'+PONG\r\n', ('following reply', following)
                if closes:
                    with server.client() as c: assert c.cmd('PING') == b'PONG'
                if not run.oracle:
                    assert results[name] == run.reference[name], (results[name], run.reference[name])
                run.check(label + ':' + name, True, True)
            except Exception as exc:
                results[name] = dict(error=repr(exc))
                run.check(label + ':' + name, repr(exc), True)
        try:
            monitored = monitor(server.port, database)
            results['monitor'] = {key: value['payload'] for key, value in monitored.items()}
            (run.path / label / 'monitor.json').write_text(json.dumps(monitored, indent=2) + '\n')
            if not run.oracle: assert results['monitor'] == run.reference['monitor']
            run.check(label + ':monitor-escaped-status', True, True)
        except Exception as exc:
            run.check(label + ':monitor-escaped-status', repr(exc), True)
    (run.path / label / 'wire.json').write_text(json.dumps(results, indent=2) + '\n')
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    failures = 0
    reference = {}
    for binary, oracle in [(args.oracle, True), (args.binary, False)]:
        run = Run(args, binary, oracle)
        run.reference = reference
        legs = [('redis', '', 0, 16)] if oracle else itertools.product(
            ('1s', '2s'), ('epoll', 'uring'), (0, 1), (1, 16))
        for mode, engine, atomic, databases in legs:
            label = f'{mode}-{engine}-a{atomic}-db{databases}'
            extra = ['--databases', str(databases), '--enable-debug-command', 'yes']
            if not oracle:
                extra += ['--net-io', engine, '--atomic', str(atomic)]
                if mode == '1s': extra += ['--read-local', '1']
            try:
                rows = probe(run, mode, label, extra, databases - 1)
                if oracle: reference = rows
            except Exception:
                traceback.print_exc()
                run.check(label + ': completed every case', False, True)
        failures += run.finish()
    print(f'crlffix: {failures} failed checks', flush=True)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
