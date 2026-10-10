#!/usr/bin/env python3
"""PS4.10/PS4.11: acknowledged shutdown writes and cancelled live captures.

Adapted from round4-read/tests/persist/{probes2,at26}.py and server-atomics/T13.
Each row owns its boots, port and fresh data. The same assertions run on PRE
and POST; an unobserved race window retries fresh state and ultimately fails.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import threading
import time

from _lib import Conn, encode, info, wait_ready
from persistfix import check_port_owner, guard_port


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields), sort_keys=True), flush=True)


def load():
    return dict(loadavg=Path('/proc/loadavg').read_text().strip(),
                cpus=sorted(os.sched_getaffinity(0)),
                cpu_ticks=[line for line in Path('/proc/stat').read_text().splitlines()
                           if line.split()[0] in {'cpu%d' % n for n in range(112, 128)}])


@contextlib.contextmanager
def boot(args, directory, label, recovery=False):
    guard_port(args.port)
    aof = args.case == 'rewrite' or args.aof
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(directory),
            '--save', '3600 1' if args.case == 'acks' and not recovery else '',
            '--appendonly', 'yes' if aof else 'no', '--appendfsync', 'everysec',
            '--auto-aof-rewrite-percentage', '0']
    if args.oracle:
        argv += ['--protected-mode', 'no']
    else:
        argv += ['--thread-mode', args.mode, '--net-io', args.net_io,
                 '--shards', '16', '--atomic', str(args.atomic), '--databases', str(args.databases),
                 '--read-local', str(args.read_local), '--key-lb', '0', '--client-lb', '0',
                 '--flip-auto', '0', '--enable-debug-command', 'yes']
        if args.mode == '2s':
            argv += ['--ratio', args.ratio]
    path = directory / (label + '.log')
    (directory / (label + '.argv.json')).write_text(json.dumps(argv) + '\n')
    with path.open('wb') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=log)
        emit('boot', pid=process.pid, argv=argv)
        conn = None
        try:
            conn = wait_ready('127.0.0.1', args.port, timeout=15, process=process,
                              log_path=None if args.oracle else path)
            check_port_owner(args.port, process.pid)
            yield process, conn, path
        finally:
            if conn:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            # io_uring's async listener teardown can briefly outlive waitpid.
            deadline = time.monotonic() + 5
            while True:
                try:
                    guard_port(args.port)
                    break
                except AssertionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.01)


def seed(args, conn):
    value = b'x' * args.value_bytes
    # The audited probe used batched MSET to populate. Keep each frame below
    # 1 MiB; seed traffic must not turn a shutdown row into an AOF throughput run.
    batch = max(1, min(2000, 524288 // (args.value_bytes + 64)))
    for begin in range(0, args.keys, batch):
        words = [part for index in range(begin, min(begin + batch, args.keys))
                 for part in ('savefix:pop:%d' % index, value)]
        assert conn.must('MSET', *words) == b'OK'
    assert conn.must('DBSIZE') == args.keys


class Writers:
    def __init__(self, args):
        self.args = args
        self.acked = [-1] * 8
        self.sent = [0] * 8
        self.errors = []
        self.stopping = threading.Event()
        self.paused = threading.Event()
        self.parked = [False] * 8
        self.threads = [threading.Thread(target=self.run, args=(index,)) for index in range(8)]

    def keys(self, index):
        return ['savefix:w:%d:%d' % (index, key) for key in range(3)]

    def run(self, index):
        conn = None
        try:
            conn = Conn('127.0.0.1', self.args.port, timeout=15)
            generation = 0
            while not self.stopping.is_set():
                if self.paused.is_set():
                    self.parked[index] = True
                    while self.paused.is_set() and not self.stopping.wait(.001):
                        pass
                    self.parked[index] = False
                    continue
                keys = self.keys(index)
                if self.args.case == 'acks' and self.args.atomic == 0:
                    conn.send('SET', keys[0], generation)
                    self.sent[index] += 1
                    assert conn.read() == b'OK'
                elif self.args.atomic == 1:
                    conn.send('MSET', *[part for key in keys for part in (key, generation)])
                    self.sent[index] += 1
                    assert conn.read() == b'OK'
                else:
                    # EXEC installs MVCC records even at the default --atomic 0.
                    conn.raw(encode('MULTI') + b''.join(encode('SET', key, generation)
                                                      for key in keys) + encode('EXEC'))
                    self.sent[index] += 1
                    assert conn.read() == b'OK'
                    assert [conn.read() for _ in keys] == [b'QUEUED'] * len(keys)
                    assert conn.read() == [b'OK'] * len(keys)
                self.acked[index] = generation
                generation += 1
        except (EOFError, ConnectionResetError, BrokenPipeError):
            pass  # terminal shutdown closes the one outstanding request
        except Exception as error:
            self.errors.append(repr(error))
        finally:
            if conn:
                conn.close()

    def start(self):
        for thread in self.threads:
            thread.start()
        deadline = time.monotonic() + 5
        while min(self.acked) < 3 and time.monotonic() < deadline:
            time.sleep(.001)
        assert min(self.acked) >= 3, ('writers did not arm', self.acked, self.errors)

    def pause(self):
        self.paused.set()
        deadline = time.monotonic() + 5
        while not all(self.parked) and time.monotonic() < deadline:
            time.sleep(.001)
        assert all(self.parked), ('group writers did not quiesce for rewrite admission', self.errors)

    def finish(self):
        self.stopping.set()
        for thread in self.threads:
            thread.join(timeout=16)
        assert not any(thread.is_alive() for thread in self.threads), 'writer did not terminate'
        assert not self.errors, self.errors


def prefix(args, directory):
    # A real incomplete data prefix, not just in_progress or an empty temp file.
    for path in directory.rglob('*'):
        if '.tmp.' not in path.name and not path.name.startswith('temp-'):
            continue
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        if path.is_file() and 4096 <= size < args.keys * args.value_bytes // 2:
            return dict(path=str(path), bytes=size)
    return None


def attempt(args, directory):
    with boot(args, directory, 'write') as (process, conn, log):
        seed(args, conn)
        writers = Writers(args)
        witness = None
        writers.start()
        try:
            if args.case == 'acks':
                emit('shutdown_request', acked=writers.acked[:], load=load())
                if args.action == 'sigterm':
                    process.send_signal(signal.SIGTERM)
                else:
                    conn.send('SHUTDOWN')
                deadline = time.monotonic() + 15
                while process.poll() is None and time.monotonic() < deadline:
                    partial = prefix(args, directory)
                    if partial and min(writers.acked) >= 3:
                        witness = dict(prefix=partial, acked=writers.acked[:],
                                       sent=writers.sent[:])
                        break
                    time.sleep(.001)
            else:
                if args.case == 'rewrite':
                    # Rewrites wait for atomic_inflight == 0 before starting.
                    # Eight continuous group streams can prevent that admission
                    # altogether. Open the real capture first, then put the same
                    # streams back in flight while its partial file is observed.
                    writers.pause()
                reply = conn.must('BGSAVE' if args.case == 'bgsave' else 'BGREWRITEAOF')
                emit('capture_started', reply=reply.decode())
                deadline = time.monotonic() + 5
                if args.case == 'rewrite':
                    while not prefix(args, directory) and time.monotonic() < deadline:
                        time.sleep(.001)
                    writers.paused.clear()
                while process.poll() is None and time.monotonic() < deadline:
                    current = info(conn, 'all')
                    partial = prefix(args, directory)
                    active = int(current.get('rdb_bgsave_in_progress', 0)) if args.case == 'bgsave' \
                        else int(current.get('aof_rewrite_in_progress', 0))
                    entries = int(current.get('atomic_pending_entries', 0))
                    if active and partial and (entries > 0 or args.oracle):
                        witness = dict(prefix=partial, in_progress=active,
                                       atomic_pending_entries=entries, acked=writers.acked[:])
                        break
                    time.sleep(.001)
                emit('shutdown_request', witness=witness, load=load())
                process.send_signal(signal.SIGTERM)
            status = process.wait(timeout=15)
        finally:
            # On an assertion/timeout the context closes the server before join.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            writers.finish()
        temporary = sorted(str(path.relative_to(directory)) for path in directory.rglob('*tmp*'))
        result = dict(witness=witness, status=status, acked=writers.acked[:], sent=writers.sent[:],
                      temporary=temporary, shutdown_report='shutdown_report {' in log.read_text(),
                      load=load())
        emit('shutdown_result', **result)
        if witness is None:
            emit('invalid_window', reason='no observed live capture; retry fresh state')
            return None
    # Check replay even after PRE's abort, retaining data-integrity evidence too.
    if args.case == 'acks' or args.case == 'rewrite' or args.aof:
        with boot(args, directory, 'replay', recovery=True) as (process, conn, log):
            restored = []
            for index, generation in enumerate(writers.acked):
                keys = writers.keys(index)
                if args.case == 'acks' and args.atomic == 0:
                    keys = keys[:1]
                values = [conn.must('GET', key) for key in keys]
                restored.append([None if value is None else int(value) for value in values])
            result['restored'] = restored
            result['lost'] = [index for index, values in enumerate(restored)
                              if any(value is None or value < writers.acked[index] for value in values)]
            result['dbsize'] = conn.must('DBSIZE')
            emit('replay', restored=restored, lost=result['lost'], dbsize=result['dbsize'])
            conn.send('SHUTDOWN', 'NOSAVE')
            assert process.wait(timeout=10) == 0, log.read_text()[-2000:]
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    assert status == 0, ('shutdown must exit cleanly', result)
    assert result['shutdown_report'] or args.oracle, ('missing normal shutdown report', result)
    assert not temporary, ('orphan capture temporary file', result)
    assert not result.get('lost'), ('acknowledged writes missing from final dump', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=('acks', 'bgsave', 'rewrite'), required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--action', choices=('sigterm', 'command'), default='sigterm')
    parser.add_argument('--atomic', choices=(0, 1), type=int, default=0)
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--keys', type=int, default=131072)
    parser.add_argument('--value-bytes', type=int, default=200)
    parser.add_argument('--databases', type=int, default=1)
    parser.add_argument('--read-local', type=int, choices=(0, 1), default=0)
    parser.add_argument('--aof', action='store_true')
    parser.add_argument('--oracle', action='store_true')
    args = parser.parse_args()
    assert args.keys >= 1024 and args.value_bytes >= 200
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    emit('start', sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(), load=load())
    for number in range(1, 4):
        directory = args.output / ('attempt-%d' % number)
        directory.mkdir()
        result = attempt(args, directory)
        if result is not None:
            emit('SAVEFIX PASS', case=args.case, mode=args.mode, atomic=args.atomic,
                 action=args.action, result=result)
            return
    raise AssertionError('capture window never armed in three fresh datasets')


if __name__ == '__main__':
    main()
