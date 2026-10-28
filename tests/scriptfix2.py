#!/usr/bin/env python3
"""Redis 7.4 scripting compatibility: exact wire comparisons, with owned listeners.

--reproduce runs the original harness5 commands, including stopped owner roots.
The ordinary gate adds boundary cases and requires every wire reply to match.
No throughput or timing verdict is made. Ports/CPU masks are supplied by callers.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from _lib import encode

ROOT = Path(__file__).resolve().parents[1]
ROOTS = '''EVAL-SHEBANG EVALSHA-SHA-CASE FCALL-NAME-CASE FUNCTION-LOAD-DENYOOM
FUNCTION-LOAD-ENV FUNCTION-REGISTER-ARGS FUNCTION-SHEBANG-META FUNCTION-SUBCMD-ARGS
LUA-REDIS-API LUA-SANDBOX-GLOBALS SCRIPT-ERROR-WORDING SCRIPT-NUMBER-ARG
SCRIPT-REPLY-DEPTH ACL-SCRIPTS-NEED-ALLCOMMANDS'''.split()


class Wire:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), 10)
        self.file = self.sock.makefile('rb')

    def close(self):
        self.file.close()
        self.sock.close()

    def cmd(self, *args):
        self.sock.sendall(encode(*args))
        # Iterative framing also records deep/cyclic replies without a client
        # recursion limit. Preserve simple/bulk distinctions and inline errors.
        remaining = 1
        result = bytearray()
        while remaining:
            line = self.file.readline()
            if not line.endswith(b'\r\n'):
                raise EOFError(repr(line))
            result.extend(line)
            remaining -= 1
            tag, value = line[:1], line[1:-2]
            if tag in (b'$', b'=', b'!') and int(value) >= 0:
                size = int(value) + 2
                data = self.file.read(size)
                assert len(data) == size and data.endswith(b'\r\n')
                result.extend(data)
            elif tag in (b'*', b'~', b'>', b'%'):
                remaining += max(0, int(value)) * (2 if tag == b'%' else 1)
            else:
                assert tag in (b'+', b'-', b':', b'_', b'#', b',', b'(', b'$'), line
        return bytes(result)


def free_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))


@contextlib.contextmanager
def server(args, oracle=False):
    port = args.port + int(oracle)
    free_port(port)
    directory = (args.output / ('redis' if oracle else 'target')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    binary = args.oracle if oracle else args.binary
    cmd = ['taskset', '-c', args.oracle_cores if oracle else args.cores,
           str(binary.resolve()), '--bind', '127.0.0.1', '--port', str(port),
           '--save', '', '--appendonly', 'no', '--dir', str(directory),
           '--enable-debug-command', 'yes']
    if not oracle:
        cmd += ['--thread-mode', args.mode, '--shards', '16',
                '--databases', str(args.databases), '--net-io', args.net_io,
                '--flip-auto', '0']
        if args.mode == '2s':
            cmd += ['--ratio', args.ratio]
    with (directory / 'server.log').open('w') as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError((directory / 'server.log').read_text())
                try:
                    c = Wire(port)
                    assert c.cmd('PING') == b'+PONG\r\n'
                    c.close()
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)
            yield port, cmd
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise AssertionError('owned server required SIGKILL')
            assert process.returncode == 0, process.returncode
            deadline = time.monotonic() + 2
            while True:
                try:
                    free_port(port)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.02)


def extras(root):
    """Boundary/interaction cases; all keys remain explicitly declared."""
    commands = []
    def eval_(code, *keys, verb='eval'):
        commands.append([verb, code, len(keys), *keys])
    def load(body, name='extra', replace=True):
        commands.append(['function', 'load', *(['replace'] if replace else []),
                         '#!lua name=' + name + '\n' + body])
    if root == 'EVALSHA-SHA-CASE':
        for code in ("return 'hello'", "error('case')"):
            digest = hashlib.sha1(code.encode()).hexdigest()
            commands += [['script', 'load', code], ['evalsha', digest.upper(), 0],
                         ['evalsha_ro', digest.upper(), 0],
                         ['script', 'exists', digest.upper(), digest, digest[:-1]]]
    elif root == 'EVAL-SHEBANG':
        for header in ('#!lua', '#!LUA', '#!lua flags=', '#!lua flags=no-writes',
                       '#!lua flags=allow-oom,no-writes', '#!lua flags=unknown',
                       '#!lua flags=no-writes,', '#!lua unknown=1', '#!lua "broken',
                       '#!lua flags="no-writes"', '#!lua flags=allow-stale,no-cluster,allow-cross-slot-keys'):
            eval_(header + '\nreturn 1')
            eval_(header + '\nreturn 1', verb='eval_ro')
            commands.append(['script', 'load', header + '\nreturn 1'])
        eval_('#!lua')
        eval_("#!lua flags=no-writes\nreturn redis.pcall('set',KEYS[1],1)", 'readonly')
        commands.append(['get', 'readonly'])
        code = "#!lua flags=no-writes\nreturn redis.call('set',KEYS[1],1)"
        commands += [['script', 'load', code],
                     ['evalsha', hashlib.sha1(code.encode()).hexdigest().upper(), 1, 'readonly']]
    elif root == 'FCALL-NAME-CASE':
        load("redis.register_function{function_name='MiXeD',callback=function() return 42 end,flags={'no-writes'}}")
        commands += [['fcall', 'MIXED', 0], ['fcall_ro', 'mixed', 0]]
        load("redis.register_function('mixed',function() return 0 end)", 'collision')
        load("redis.register_function('DUP',function() end) redis.register_function('dup',function() end)", 'duplicate')
        commands += [['function', 'delete', 'extra'], ['fcall', 'mIxEd', 0]]
    elif root == 'FUNCTION-SHEBANG-META':
        for header in ('#!lua name=', '#!lua', '#!lua name=x', '#!lua NAME=quoted',
                       '#!lua name="quoted"', "#!lua name='quoted'", '#!LUA name=x',
                       '#!lua name=x NAME=y', '#!lua name="unterminated',
                       '#!lua name="x"tail', '#!lua name=x unknown=1', '#!bad'):
            commands.append(['function', 'load', 'replace', header + '\nredis.register_function("h",function() end)'])
        commands += [['function', 'load', '#!lua name=no_newline']]
    elif root == 'FUNCTION-LOAD-ENV':
        for expression in ('type', '_G', 'math', 'getmetatable', 'string', 'cjson', 'os', 'redis.call'):
            load('local p = ' + expression + '\nredis.register_function("e",function() return 1 end)')
        load("redis.register_function('env_cb',function() return {type(math),type(redis.call)} end)")
        commands.append(['fcall', 'env_cb', 0])
    elif root == 'FUNCTION-REGISTER-ARGS':
        for call in ('()', '(1)', '({},function() end)', "('f',{})", "('',function() end)",
                     "('a-b',function() end)", "{[1]='x'}", "{function_name='f'}",
                     "{function_name='f',callback=1}", "{function_name='f',callback=function() end,flags='no-writes'}",
                     "{function_name='f',callback=function() end,description={}}"):
            load('redis.register_function' + call)
    elif root == 'FUNCTION-SUBCMD-ARGS':
        for sub in ('load', 'restore', 'flush', 'dump', 'stats', 'delete', 'kill', 'help'):
            for tail in ([], ['a'], ['a', 'b'], ['a', 'b', 'c']):
                if not tail and sub in ('dump', 'help'):
                    continue  # Own dump format/help text are explicit existing contracts.
                commands.append(['function', sub, *tail])
        commands += [['function', 'list', 'LIBRARYNAME'],
                     ['function', 'list', 'withcode', 'WITHCODE']]
    elif root == 'SCRIPT-ERROR-WORDING':
        for code in ('return redis.pcall()', "return redis.pcall('get', {})",
                     "return redis.pcall('get','a','b')", 'error(false)', 'error(nil)',
                     "error({err='CUSTOM detail'})", "error('my error')"):
            eval_(code)
    elif root == 'SCRIPT-NUMBER-ARG':
        for value in ('-0.0', '1e-7', '1e-6', '1e20', '1e21', '1e100', '1e-100',
                      '9007199254740992', '-9007199254740991', '1/0', '-1/0', '0/0'):
            eval_("redis.call('set',KEYS[1]," + value + ") return redis.call('get',KEYS[1])", 'number')
    elif root == 'LUA-REDIS-API':
        for code in ("return redis.error_reply('')", "return redis.error_reply('message')",
                     "return redis.error_reply('-CUSTOM detail')", "return redis.error_reply('X a\\r\\nb')",
                     "return redis.error_reply('X a\\0b')", "return redis.error_reply(1)",
                     "return redis.status_reply(1)", "return redis.status_reply('a\\r\\nb')",
                     "return {redis.REDIS_VERSION,redis.REDIS_VERSION_NUM}",
                     "redis.log()", "redis.log({},'x')", "redis.log(4,'x')",
                     "redis.log(redis.LOG_DEBUG,'x') return 1", 'return redis.replicate_commands()'):
            eval_(code)
        load("local version=redis.REDIS_VERSION_NUM redis.log(redis.LOG_NOTICE,'load') "
             "redis.register_function('api',function() return {version,redis.REDIS_VERSION} end)")
        commands.append(['fcall', 'api', 0])
    elif root == 'LUA-SANDBOX-GLOBALS':
        for code in ("return loadstring('return 7')()", "return loadstring('\\27Lua')()",
                     "return type(load)", "local co=coroutine.create(function() return 3 end) "
                     "local ok,n=coroutine.resume(co) return {ok,n}",
                     "collectgarbage('collect') return 1", "return os.execute('anything')",
                     "return os.clock() >= 0", "math.randomseed(10) return {tostring(math.random()),math.random(10),math.random(-10,10)}",
                     "math.randomseed(10) return tostring(math.random())",
                     "return math.random(0)", "return math.random(2,1)", "return math.random(1,2,3)"):
            eval_(code)
        load("redis.register_function('globals',function() return {type(os.clock),type(loadstring),type(coroutine),type(collectgarbage)} end)")
        commands.append(['fcall', 'globals', 0])
    elif root == 'SCRIPT-REPLY-DEPTH':
        for depth in (31, 32, 33, 128, 512):
            eval_(f'local t={{}} local c=t for i=1,{depth} do c[1]={{}} c=c[1] end return t')
        eval_('local t={} t[1]=t return t')
    return [{'c': 'a', 'send': command} for command in commands]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--oracle', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    p.add_argument('--cores', required=True)
    p.add_argument('--oracle-cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--databases', type=int, default=16)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--root', choices=ROOTS)
    p.add_argument('--reproduce', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = json.loads((ROOT / 'docs/harness5/redis-tcl-repros.json').read_text())['cases']
    report = dict(mode=args.mode, net_io=args.net_io, databases=args.databases,
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  oracle_sha256=hashlib.sha256(args.oracle.read_bytes()).hexdigest(), rows=[])
    with server(args) as (target, target_argv), server(args, True) as (oracle, oracle_argv):
        report.update(target_argv=target_argv, oracle_argv=oracle_argv)
        for root in ([args.root] if args.root else ROOTS):
            steps = original['A-' + root]['steps'] + ([] if args.reproduce else extras(root))
            row = dict(root=root, steps=[], differences=0)
            conns = {}
            try:
                for port in (target, oracle):
                    c = conns[port, 'a'] = Wire(port)
                    for command in (('config', 'set', 'maxmemory', 0), ('flushall',),
                                    ('function', 'flush'), ('script', 'flush'), ('acl', 'deluser', 'bob')):
                        assert not c.cmd(*command).startswith(b'-'), command
                for step in steps:
                    replies = []
                    for port in (target, oracle):
                        key = port, step['c']
                        if key not in conns:
                            conns[key] = Wire(port)
                        replies.append(conns[key].cmd(*step['send']))
                    equal = replies[0] == replies[1]
                    row['differences'] += int(not equal)
                    row['steps'].append(dict(**step, equal=equal,
                        target=replies[0].decode('utf-8', 'backslashreplace'),
                        redis=replies[1].decode('utf-8', 'backslashreplace')))
            finally:
                for c in conns.values():
                    c.close()
            report['rows'].append(row)
            (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f"{root}: {row['differences']}/{len(steps)} differ", flush=True)
    return int(any(r['differences'] for r in report['rows']))


if __name__ == '__main__':
    raise SystemExit(main())
