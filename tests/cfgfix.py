#!/usr/bin/env python3
"""CONFIG oracle receipts; called by gate.sh's cfgfix job, with all engine/mode legs."""
from contextlib import closing, contextmanager
import ctypes
import itertools
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import subprocess
import time

import _netfix as n


@contextmanager
def environment(**values):
    previous = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def syslog_trial(a, mode, engine, oracle):
    # Intercept the libc boundary in these owned processes. This checks ident,
    # facility, severity and live filtering without changing the host /dev/log
    # socket or sending test messages to its logging service.
    hook = (a.output / 'syslog-hook.so').resolve()
    if not hook.exists():
        source = a.output / 'syslog-hook.c'
        source.write_text(r'''
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
static void record(const char *kind, const char *value, int number) {
    const char *path = getenv("CFGFIX_SYSLOG_RECEIPT");
    if (!path) _exit(97);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0) _exit(98);
    dprintf(fd, "%s\t%s\t%d\n", kind, value, number);
    close(fd);
}
void openlog(const char *ident, int options, int facility) {
    (void)options; record("openlog", ident, facility);
}
void syslog(int priority, const char *format, ...) {
    (void)format; record("syslog", "", priority);
}
void __syslog_chk(int priority, int flag, const char *format, ...) {
    (void)flag; (void)format; record("syslog", "", priority);
}
void closelog(void) { record("closelog", "", 0); }
''')
        subprocess.run(['gcc', '-shared', '-fPIC', '-O2', str(source), '-o', str(hook)], check=True)
    label = f'syslog-{mode}-{engine}'
    receipt = (a.output / (label + '.tsv')).resolve()
    with environment(LD_PRELOAD=str(hook), CFGFIX_SYSLOG_RECEIPT=str(receipt)):
        with n.server(a, label, oracle=oracle, mode=mode, engine=engine,
                      extra=('--syslog-enabled', 'yes', '--syslog-ident', 'cfgfix',
                             '--syslog-facility', 'local7')):
            assert 'openlog\tcfgfix\t184\n' in receipt.read_text()  # LOG_LOCAL7
            with closing(n.connect(a.port)) as c, closing(socket.socket()) as occupied:
                occupied.bind(('127.0.0.1', a.port + 2)); occupied.listen()
                before = receipt.stat().st_size
                assert isinstance(c.cmd('CONFIG', 'SET', 'port', a.port + 2), n._lib.RespError)
                assert 'syslog\t\t4\n' in receipt.read_text()[before:]  # LOG_WARNING
                c.must('CONFIG', 'SET', 'loglevel', 'nothing')
                before = receipt.stat().st_size
                assert isinstance(c.cmd('CONFIG', 'SET', 'port', a.port + 2), n._lib.RespError)
                assert receipt.stat().st_size == before, 'filtered warning reached syslog'


def supervisor_trial(a, mode, engine):
    # The supplied Redis oracle lacks libsystemd. Verify the native notification
    # protocol on private filesystem and abstract sockets, including their
    # different sockaddr lengths. No host supervisor is contacted.
    messages = {}
    variants = [('base', ()), ('armed', ('--read-local', '1'))]
    if mode == '1s':
        variants += [('reorder', ('--reorder', '1')),
                     ('armed-reorder', ('--read-local', '1', '--reorder', '1'))]
    for abstract, (variant, extra) in itertools.product((False, True), variants):
        short = Path('build/cfgfix') / f'notify-{os.getpid()}-{mode}-{engine}.sock'
        address = '@cfgfix-' + str(os.getpid()) + '-' + mode + '-' + engine if abstract else str(short.resolve())
        wire_address = '\0' + address[1:] if abstract else address
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)) as receiver:
            receiver.bind(wire_address)
            receiver.settimeout(5)
            try:
                with environment(NOTIFY_SOCKET=address, UPSTART_JOB=None):
                    with n.server(a, f'supervisor-{mode}-{engine}-{variant}-{abstract}', mode=mode, engine=engine,
                                  extra=('--supervised', 'auto', *extra)):
                        lines = []
                        while 'READY=1' not in lines:
                            lines += receiver.recv(4096).decode().splitlines()
                        assert any(line.startswith('STATUS=') for line in lines), lines
                        messages[f'{variant}:{abstract}'] = lines
            finally:
                if not abstract:
                    short.unlink()
    (a.output / f'supervisor-{mode}-{engine}.json').write_text(json.dumps(messages, indent=2))


def plain(value):
    if isinstance(value, n._lib.RespError):
        return {'error': str(value)}
    if isinstance(value, bytes):
        return value.decode('utf-8', 'backslashreplace')
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def process_trial(a, mode, engine, oracle):
    label = f'process-{mode}-{engine}'
    directory = (a.output / label).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    logfile, pidfile = directory / 'configured.log', directory / 'configured.pid'
    logfile.write_text('cfgfix append marker\n')
    extra = ('--logfile', str(logfile), '--pidfile', str(pidfile), '--loglevel', 'notice',
             '--syslog-enabled', 'no', '--syslog-ident', 'cfgfix', '--syslog-facility', 'local7')
    with n.server(a, label, oracle=oracle, mode=mode, engine=engine, extra=extra) as child:
        assert int(pidfile.read_text()) == child.pid
        assert logfile.read_text().startswith('cfgfix append marker\n')
        with closing(n.connect(a.port)) as c, closing(socket.socket()) as occupied:
            occupied.bind(('127.0.0.1', a.port + 2)); occupied.listen()
            before = logfile.stat().st_size
            assert isinstance(c.cmd('CONFIG', 'SET', 'port', a.port + 2), n._lib.RespError)
            assert logfile.stat().st_size > before, 'warning was not written to logfile'
            c.must('CONFIG', 'SET', 'loglevel', 'nothing')
            before = logfile.stat().st_size
            assert isinstance(c.cmd('CONFIG', 'SET', 'port', a.port + 2), n._lib.RespError)
            assert logfile.stat().st_size == before, 'loglevel nothing did not suppress diagnostics'
    assert not pidfile.exists(), 'configured pidfile was not removed'

    # A daemon's parent exits successfully. Bind cleanup to its pidfd before
    # sending any signal, so PID reuse cannot target a different process.
    # Adopt the daemon as well: even a broken pidfile implementation must not
    # leave an unowned server behind when this assertion fails.
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    args = json.loads((directory / 'command.json').read_text()) + ['--daemonize', 'yes']
    with (directory / 'daemon-parent.log').open('w') as log:
        parent = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        assert parent.wait(timeout=15) == 0
    children = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split()
    assert len(children) == 1, children
    pid = int(children[0])
    pidfd = os.pidfd_open(pid)
    try:
        deadline = time.monotonic() + 15
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert pidfile.exists(), 'daemon never published its pid'
        assert int(pidfile.read_text()) == pid
        expected = Path(a.oracle if oracle else a.binary).resolve()
        assert Path(f'/proc/{pid}/exe').resolve() == expected
        while True:
            try:
                with closing(n.connect(a.port)) as c:
                    assert c.must('PING') == b'PONG'
                break
            except OSError:
                if time.monotonic() >= deadline: raise
                time.sleep(.01)
    finally:
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            pass
        waiter = select.poll(); waiter.register(pidfd, select.POLLIN)
        if not waiter.poll(15000):
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            waiter.poll(5000)
            raise AssertionError('daemon did not stop on SIGTERM')
        os.close(pidfd)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0, status
    assert not pidfile.exists(), 'daemon pidfile was not removed'
    syslog_trial(a, mode, engine, oracle)
    if not oracle:
        supervisor_trial(a, mode, engine)


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
            ('GET', 'key-load-delay'), ('GET', 'KEY-LOAD-DELAY'), ('GET', 'key-load-*'),
            ('GET', 'TIMEOUT', 'timeout', 'time*'),
            ('GET', 'time*', 'TIMEOUT'),
            ('GET', 'HASH-MAX-ZIPLIST-ENTRIES', 'hash-max-listpack-entries', 'hash-max-*pack-entries'),
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
        # Runtime AOF must capture pre-existing keys, writes after activation,
        # and an OFF gap. A fresh process then proves the final manifest recovers
        # the current image, rather than silently replaying the stale old base.
        def persistence():
            return dict(line.split(':', 1) for line in c.must('INFO', 'persistence').decode().splitlines()
                        if ':' in line)

        def rewritten(target):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                fields = persistence()
                if (int(fields['aof_rewrites']) >= target and
                        fields['aof_rewrite_in_progress'] == fields['aof_rewrite_scheduled'] == '0'):
                    assert fields['aof_last_bgrewrite_status'] == 'ok', fields
                    selected = {key: fields[key] for key in (
                        'aof_enabled', 'aof_rewrite_in_progress', 'aof_rewrite_scheduled',
                        'aof_last_bgrewrite_status', 'aof_last_write_status', 'aof_rewrites')}
                    replies.append([['INFO persistence after rewrite', target], selected])
                    return
                time.sleep(.02)
            raise AssertionError(('AOF rewrite never completed', fields))

        c.must('SET', 'cfgfix:before-aof', 'old')
        c.must('SET', 'cfgfix:deleted-in-gap', 'old')
        c.must('SELECT', '1')
        c.must('SET', 'cfgfix:namespace', 'before-aof')
        c.must('SELECT', '0')
        appenddir = Path(proc.args[proc.args.index('--dir') + 1]) / 'appendonlydir'
        appenddir.write_text('not a directory\n')
        for fsync in ('no', 'everysec', 'always'):
            c.must('CONFIG', 'SET', 'appendfsync', fsync)
            command('CONFIG', 'SET', 'maxmemory', '12345678', 'appendonly', 'yes', 'port', str(port + 1))
            command('CONFIG', 'GET', 'maxmemory', 'appendonly', 'port')
            with closing(n.connect(port)) as original:
                assert original.must('PING') == b'PONG'
        c.must('CONFIG', 'SET', 'appendfsync', 'everysec')
        server_log = appenddir.parent / 'server.log'
        (a.output / ('oracle' if oracle else f'candidate-{proc.pid}') / 'apply-error.log').parent.mkdir(exist_ok=True)
        (a.output / ('oracle' if oracle else f'candidate-{proc.pid}') / 'apply-error.log').write_bytes(server_log.read_bytes())
        appenddir.unlink()
        command('CONFIG', 'SET', 'appendonly', 'yes')
        command('CONFIG', 'GET', 'appendonly')
        c.must('SET', 'cfgfix:after-aof', 'written')
        rewritten(1)
        command('CONFIG', 'SET', 'appendonly', 'no')
        command('CONFIG', 'GET', 'appendonly')
        c.must('SET', 'cfgfix:before-aof', 'changed-while-off')
        c.must('DEL', 'cfgfix:deleted-in-gap')
        c.must('SET', 'cfgfix:gap', 'new-while-off')
        c.must('SWAPDB', '1', '2')
        c.must('SELECT', '2')
        c.must('SET', 'cfgfix:namespace', 'changed-while-off')
        c.must('SELECT', '0')
        command('CONFIG', 'SET', 'appendonly', 'yes')
        rewritten(2)
        c.must('SELECT', '2')
        c.must('SET', 'cfgfix:namespace', 'after-second-rewrite')
        c.must('SELECT', '0')
        c.must('SET', 'cfgfix:last', 'durable')
        try:
            c.cmd('SHUTDOWN', 'NOSAVE')
        except (EOFError, ConnectionError, OSError):
            pass
        assert proc.wait(timeout=15) == 0
        mode = 'oracle' if oracle else proc.args[proc.args.index('--thread-mode') + 1]
        engine = 'oracle' if oracle else proc.args[proc.args.index('--net-io') + 1]
        label = Path(proc.args[proc.args.index('--dir') + 1]).name
        with n.server(a, label, oracle=oracle, mode=mode, engine=engine, extra=('--appendonly', 'yes')):
            with closing(n.connect(port)) as recovered:
                result = recovered.must('MGET', 'cfgfix:before-aof', 'cfgfix:after-aof',
                                        'cfgfix:deleted-in-gap', 'cfgfix:gap', 'cfgfix:last')
                assert result == [b'changed-while-off', b'written', None, b'new-while-off', b'durable'], result
                replies.append([['AOF restart across OFF gap'], plain(result)])
                recovered.must('SELECT', '1')
                assert recovered.must('GET', 'cfgfix:namespace') is None
                recovered.must('SELECT', '2')
                assert recovered.must('GET', 'cfgfix:namespace') == b'after-second-rewrite'
                replies.append([['AOF namespace map across OFF gap'], 'preserved'])
        process_trial(a, mode, engine, oracle)
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
