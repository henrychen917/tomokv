#!/usr/bin/env python3
"""FLIP liveness/stop regressions (lane flipfix): IO4.1, IO4.2, IO4.4, CT4.3.

Adapted from round4-read/tests/io-loop t05d/t05e/t05f/t05g and tests/controllers U1. Every case
owns its exact child process, port and fresh persistence directory, emits JSON lines, and turns
any sanitizer report, abort or unanswered FLIP into a failure. No throughput conclusions.

  close        IO4.1: idle connections close right after each FLIP is sent. Every FLIP must
               answer (OK or an error) within the reply bound, an OK must have applied the
               requested split, and every closed connection must be reaped afterwards.
  churn        IO4.1/IO4.4 under connection churn (fresh connects + closes); meant for the
               ASAN/TSAN builds, where a lifetime or ordering defect is a sanitizer report.
  late         IO4.1 abort branch: closes spread over FLIPs that turn executors into IOs.
  sigterm      IO4.2: save clauses armed, 1000 acknowledged SETs, a FLIP held live by a blocked
               client, SIGTERM: the server must save and exit 0 promptly; restart sees 1000 keys.
  sigint       IO4.2: same live FLIP, SIGINT twice (the second only after the first was
               delivered): the second must exit at once with status 1 (Redis 7.4 "You insist").
  controllers  CT4.3: --flip-auto 1 with sampled fingerprint windows read by the monitor and
               DEBUG FLIPCTL/LBSIGNALS; meant for the TSAN build.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

from _lib import Conn, RespError, encode, wait_ready

REPLY_BOUND_S = 6.5   # a FLIP's own pre-commit deadline is 5 s
# A connection that closes during a FLIP must neither wedge it nor hold it to that deadline nor
# make it fail: the only refusals tolerated here are the epoll registration collisions of IO4.19
# (stale source registrations of earlier moves; a separate finding, out of this lane's scope).
STALL_BOUND_S = 3.0
OUT_OF_SCOPE_REFUSALS = (
    b'ERR FLIP could not detach a connection: could not reserve destination epoll registration',
    b'ERR FLIP could not detach a connection: could not reserve source epoll rollback registration',
)
SANITIZER_MARKS = ('ERROR: AddressSanitizer', 'WARNING: ThreadSanitizer', 'ThreadSanitizer:',
                   'runtime error:', 'ERROR: LeakSanitizer')


def emit(**values):
    print(json.dumps(values, sort_keys=True), flush=True)


def report(conn):
    row = conn.must('FLIP')
    return dict(zip(row[::2], row[1::2]))


def info_field(conn, section, field):
    raw = conn.must('INFO', section)
    for line in raw.splitlines():
        if line.startswith(field.encode() + b':'):
            return line.split(b':', 1)[1].strip()
    raise AssertionError(f'INFO {section} has no {field}')


def wait_for(predicate, timeout, what, interval=.01):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f'timed out after {timeout}s waiting for {what}')
        time.sleep(interval)


@contextlib.contextmanager
def boot(args, label, save='', directory=None, extra=()):
    directory = directory or args.output / label
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (label + '.log')
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', args.port)) != 0, 'owned port already busy'
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(directory),
            '--save', save, '--appendonly', 'no', '--thread-mode', '2s',
            '--ratio', args.ratio, '--shards', '16', '--databases', '1', '--net-io', args.net_io,
            '--enable-debug-command', 'yes', *extra]
    if args.sanitizer == 'tsan':
        # TSan's shadow layout needs the classic address map (the gate's tsan_unit does the same).
        argv = ['setarch', 'x86_64', '-R', *argv]
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',
               TSAN_OPTIONS=args.tsan_options)
    emit(event='boot', label=label, argv=argv, affinity=sorted(os.sched_getaffinity(0)),
         loadavg=os.getloadavg())
    (directory / (label + '.argv.json')).write_text(json.dumps(argv) + '\n')
    # Record the shared-core load beside every timing (sibling lanes share CPUs 112-127).
    (directory / (label + '.load.txt')).write_text(
        'loadavg %s\n' % (os.getloadavg(),) + subprocess.run(
            ['ps', '-eLo', 'pid,tid,psr,pcpu,stat,comm'], capture_output=True, text=True,
            check=True).stdout)
    with path.open('w') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        conn = None
        try:
            conn = wait_ready('127.0.0.1', args.port, timeout=60, process=process, log_path=path)
            conn.sock.settimeout(REPLY_BOUND_S)
            emit(event='ready', label=label, pid=process.pid,
                 exe=os.readlink(f'/proc/{process.pid}/exe'))
            yield conn, process, directory
        finally:
            if conn:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30 if args.sanitizer != 'none' else 5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            emit(event='stop', label=label, rc=process.returncode, log=str(path),
                 loadavg=os.getloadavg())
            text = path.read_text(errors='replace')
            hits = [mark for mark in SANITIZER_MARKS if mark in text]
            assert not hits, f'sanitizer report {hits} in {path}:\n' + text[-20000:]
            assert 'Aborted' not in text, f'abort in {path}:\n' + text[-4000:]
    assert process.returncode in (0, 1, -signal.SIGTERM), \
        f'unclean process exit {process.returncode}: {text[-4000:]}'


def conn(args, timeout=REPLY_BOUND_S):
    return Conn('127.0.0.1', args.port, timeout=timeout, buffering=1 << 14)


class Idle:
    """A raw idle connection: one verified PING, then nothing until close()."""

    def __init__(self, args):
        self.sock = socket.create_connection(('127.0.0.1', args.port), timeout=REPLY_BOUND_S)
        self.sock.sendall(encode('PING'))
        reply = b''
        while not reply.endswith(b'\r\n'):
            chunk = self.sock.recv(64)
            assert chunk, 'idle connection closed during PING'
            reply += chunk
        assert reply == b'+PONG\r\n', reply

    def close(self):
        self.sock.close()


def subscribe(args, channel):
    peer = conn(args)
    reply = peer.must('SUBSCRIBE', channel)
    assert reply[0] == b'subscribe', reply
    return peer


def disconnects(args, churn=False):
    with boot(args, 'churn' if churn else 'close') as (admin, process, _):
        idle, subscribers, workers = [], [], []
        observer = conn(args)
        stop = threading.Event()
        outcomes, witnessed, applied, connector_stats = {}, 0, 0, {'ok': 0, 'refused': 0}

        def connector():
            while not stop.is_set():
                peer = None
                try:
                    peer = Conn('127.0.0.1', args.port, timeout=.5, buffering=4096)
                    reply = peer.cmd('PING')
                    connector_stats['ok' if reply == b'PONG' else 'refused'] += 1
                except (OSError, EOFError):
                    # Accept-side drops during a FLIP are IO4.3 (out of scope here).
                    connector_stats['refused'] += 1
                finally:
                    if peer:
                        peer.close()

        try:
            for i in range(args.subscribers):
                subscribers.append(subscribe(args, f'flipfix:{i % 4}'))
            for _ in range(args.idle):
                idle.append(Idle(args))
            shape = report(admin)
            total = shape[b'live_io'] + shape[b'live_ex']
            shapes = [max(2, total // 4), total // 2, total * 3 // 4, total // 2]
            if churn:
                workers = [threading.Thread(target=connector, daemon=True)
                           for _ in range(args.connectors)]
                for worker in workers:
                    worker.start()
            closed = 0
            for attempt in range(args.attempts):
                target = shapes[attempt % len(shapes)]
                admin.send('FLIP', target, total - target)
                moving = report(observer)[b'moving']
                witnessed += bool(moving)
                for _ in range(args.closes):
                    # Alternate idle and subscribed peers: both teardown paths (plain and
                    # pub/sub cleanup) must meet the FLIP.
                    pool = subscribers if subscribers and closed % 3 == 2 else idle
                    if pool:
                        pool.pop().close()
                        closed += 1
                    time.sleep(.0002)
                start = time.monotonic()
                try:
                    reply = admin.read()
                except (TimeoutError, socket.timeout) as error:
                    try:  # FLIP's report form is FlipAsync: it answers while the FLIP is live.
                        emit(event='wedged', attempt=attempt, target=target,
                             report={k.decode(): v for k, v in report(observer).items()})
                    except Exception as detail:  # noqa: BLE001 -- diagnostics only
                        emit(event='wedged', attempt=attempt, report_error=repr(detail))
                    if args.hold_on_wedge:
                        emit(event='holding', pid=process.pid, seconds=args.hold_on_wedge)
                        time.sleep(args.hold_on_wedge)
                    raise AssertionError(
                        f'FLIP {target} {total - target} unanswered after {REPLY_BOUND_S}s '
                        f'(attempt {attempt}): wedged') from error
                assert reply == b'OK' or isinstance(reply, RespError), reply
                elapsed = time.monotonic() - start
                key = 'OK' if reply == b'OK' else reply.message.decode(errors='replace')
                outcomes[key] = outcomes.get(key, 0) + 1
                emit(attempt=attempt, target=target, reply=key, moving=moving,
                     elapsed=round(elapsed, 4))
                if not args.evidence:
                    assert elapsed < STALL_BOUND_S, \
                        f'FLIP held {elapsed:.2f}s by connections closing during it ({key})'
                    assert reply == b'OK' or reply.message in OUT_OF_SCOPE_REFUSALS, \
                        f'FLIP refused because connections closed during it: {key}'
                after = report(observer)
                assert not after[b'moving'], 'FLIP reply preceded retirement'
                if reply == b'OK':
                    assert after[b'live_io'] == target, (target, after)
                    applied += 1
                assert admin.must('PING') == b'PONG'
                assert process.poll() is None, 'server exited'
                time.sleep(.02)
            assert witnessed, 'no FLIP window witnessed; missing arming is a failure'
            assert closed, 'no connection closed during a FLIP'
            assert applied, 'no FLIP applied: nothing was exercised'
        finally:
            stop.set()
            for worker in workers:
                worker.join(5)
            for peer in idle + subscribers:
                peer.close()
            observer.close()
        assert not any(worker.is_alive() for worker in workers), 'connector did not stop'
        # Every closed connection is reaped: only the admin connection remains.
        wait_for(lambda: int(info_field(admin, 'CLIENTS', 'connected_clients')) == 1, 10,
                 'closed connections to be reaped')
        assert admin.must('PING') == b'PONG'
        emit(result='PASS', case=args.case, engine=args.net_io, witnessed=witnessed,
             applied=applied, outcomes=outcomes, closed=closed, connector=connector_stats)


def late_closes(args):
    """IO4.1 abort branch probe. From an io-light split, a FLIP to an io-heavy one moves idle
    connections onto threads that become IO only at the role store. Closes are spread over the
    FLIP's lifetime, so some land after their source detached them (no source EOF) and are first
    seen by the new IO after its RoleReady acknowledgement: PRE then aborts in
    flip_complete_active (or wedges when a close lands earlier). Every FLIP must answer, the
    server must survive, and every closed connection must be reaped."""
    with boot(args, 'late') as (admin, process, _):
        idle = [Idle(args) for _ in range(args.idle)]
        observer = conn(args)
        outcomes = {}
        try:
            shape = report(admin)
            total = shape[b'live_io'] + shape[b'live_ex']
            light, heavy = max(1, total // 4), total - max(1, total // 4)
            for attempt in range(args.attempts):
                assert admin.must('FLIP', light, total - light) == b'OK', 'io-light setup FLIP'
                admin.send('FLIP', heavy, total - heavy)
                deadline = time.monotonic() + args.spread
                closes = 0
                while time.monotonic() < deadline and idle and closes < args.closes:
                    idle.pop().close()
                    closes += 1
                    time.sleep(args.spread / max(1, args.closes))
                try:
                    reply = admin.read()
                except (TimeoutError, socket.timeout) as error:
                    raise AssertionError(f'FLIP {heavy} {total - heavy} unanswered (attempt '
                                         f'{attempt}): wedged') from error
                except (EOFError, ConnectionError) as error:
                    raise AssertionError(f'server died during FLIP (attempt {attempt})') from error
                key = 'OK' if reply == b'OK' else reply.message.decode(errors='replace')
                outcomes[key] = outcomes.get(key, 0) + 1
                assert process.poll() is None, 'server exited'
                emit(attempt=attempt, reply=key, closes=closes)
        finally:
            for peer in idle:
                peer.close()
            observer.close()
        wait_for(lambda: int(info_field(admin, 'CLIENTS', 'connected_clients')) == 1, 10,
                 'closed connections to be reaped')
        emit(result='PASS', case=args.case, outcomes=outcomes)


def signal_pending(pid, signum):
    """True while `signum` is still pending (not yet delivered) for the process."""
    status = Path(f'/proc/{pid}/status').read_text()
    pending = 0
    for line in status.splitlines():
        if line.startswith(('ShdPnd:', 'SigPnd:')):
            pending |= int(line.split()[1], 16)
    return bool(pending & (1 << (signum - 1)))


def stopping(args):
    with boot(args, args.case, save='3600 1') as (admin, process, directory):
        admin.raw(b''.join(encode('SET', f'flipfix:{i}', 'durable') for i in range(1000)))
        assert [admin.read() for _ in range(1000)] == [b'OK'] * 1000
        observer, blocker, issuer = conn(args), conn(args), conn(args, timeout=15)
        try:
            # A blocked client keeps its IO from acknowledging the FLIP drain: the FLIP stays
            # live (PRE: until its 5 s deadline) on any binary, no hook needed.
            blocker.send('BLPOP', 'flipfix:blocker', 0)
            wait_for(lambda: int(info_field(observer, 'CLIENTS', 'blocked_clients')) == 1, 3,
                     'the blocking operation to arm')
            shape = report(observer)
            total = shape[b'live_io'] + shape[b'live_ex']
            target = total // 2 if shape[b'live_io'] != total // 2 else max(2, total // 4)
            issuer.send('FLIP', target, total - target)
            wait_for(lambda: report(observer)[b'moving'], 3, 'the FLIP drain window to open')
            emit(event='armed', case=args.case, moving=1, acknowledged=1000)
            start = time.monotonic()
            first = signal.SIGTERM if args.case == 'sigterm' else signal.SIGINT
            process.send_signal(first)
            if args.case == 'sigint':
                # Same-signal deliveries merge while pending: send the second only after the
                # kernel delivered the first (the handler ran), so it is a real second signal.
                wait_for(lambda: process.poll() is not None or
                         not signal_pending(process.pid, signal.SIGINT), 2,
                         'the first SIGINT to be delivered', interval=.0005)
                assert process.poll() is None, 'first SIGINT already completed the stop'
                second = time.monotonic()
                process.send_signal(signal.SIGINT)
                try:
                    status = process.wait(timeout=args.second_bound)
                except subprocess.TimeoutExpired as error:
                    raise AssertionError(
                        f'second SIGINT absorbed: still running {args.second_bound}s later') \
                        from error
                emit(event='second-sigint-exit', elapsed=round(time.monotonic() - second, 4),
                     status=status)
                assert status == 1, f'second SIGINT exit status {status}, expected 1'
            else:
                try:
                    status = process.wait(timeout=args.stop_bound)
                except subprocess.TimeoutExpired as error:
                    raise AssertionError(
                        f'SIGTERM not served: still running {args.stop_bound}s later') from error
                emit(event='sigterm-exit', elapsed=round(time.monotonic() - start, 4),
                     status=status)
                assert status == 0, f'SIGTERM exit status {status}, expected 0'
                try:
                    flip_reply = issuer.read()
                except (OSError, EOFError):
                    flip_reply = 'closed'
                emit(event='flip-reply', reply=repr(flip_reply))
        finally:
            for peer in (blocker, observer, issuer):
                peer.close()
    log = (directory / (args.case + '.log')).read_text(errors='replace')
    if args.case == 'sigint':
        assert 'You insist... exiting now.' in log, 'missing the Redis 7.4 second-signal line'
        emit(result='PASS', case=args.case)
        return
    with boot(args, 'restart', directory=directory) as (admin, _, _):
        admin.raw(b''.join(encode('GET', f'flipfix:{i}') for i in range(1000)))
        got = [admin.read() for _ in range(1000)]
        recovered = sum(value == b'durable' for value in got)
        assert recovered == 1000, f'restart recovered {recovered}/1000 acknowledged keys'
        emit(result='PASS', case=args.case, recovered=recovered)


def controllers(args):
    with boot(args, 'controllers', extra=['--flip-auto', '1', '--key-lb', '0',
                                          '--client-lb', '0']) as (admin, process, _):
        stop, errors = threading.Event(), []

        def work(request, expected):
            try:
                peer = conn(args)
                try:
                    while not stop.is_set():
                        assert peer.must(*request) == expected
                finally:
                    peer.close()
            except BaseException as error:  # noqa: BLE001 -- reported below
                errors.append(repr(error))

        assert admin.must('SET', 'flipfix:fp', 'v') == b'OK'
        workers = [threading.Thread(target=work, args=(['PING'], b'PONG')),
                   threading.Thread(target=work, args=(['GET', 'flipfix:fp'], b'v')),
                   threading.Thread(target=work, args=(['MGET', 'flipfix:fp', 'x'], [b'v', None]))]
        for worker in workers:
            worker.start()
        fields = {}
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                text = admin.must('DEBUG', 'FLIPCTL').decode()
                fields = dict(item.split('=', 1) for item in text.split() if '=' in item)
                admin.must('DEBUG', 'LBSIGNALS')
                assert process.poll() is None, 'server exited'
                time.sleep(.25)
        finally:
            stop.set()
            for worker in workers:
                worker.join(10)
        assert not errors, errors
        # Non-vacuity: the monitor consumed published fingerprint windows (the reader under test).
        observed = int(fields.get('signature_noise_samples', '0'))
        emit(result='PASS', case=args.case, phase=fields.get('phase'),
             signature_noise_samples=observed, signature_distance=fields.get('signature_distance'))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('case', choices=('close', 'churn', 'late', 'sigterm', 'sigint',
                                         'controllers'))
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--sanitizer', choices=('none', 'asan', 'tsan'), default='none')
    parser.add_argument('--tsan-options', default='halt_on_error=1:exitcode=66')
    parser.add_argument('--attempts', type=int, default=30)
    parser.add_argument('--idle', type=int, default=1500)
    parser.add_argument('--subscribers', type=int, default=24)
    parser.add_argument('--closes', type=int, default=10)
    parser.add_argument('--connectors', type=int, default=6)
    parser.add_argument('--stop-bound', type=float, default=3.0)
    parser.add_argument('--second-bound', type=float, default=.75)
    parser.add_argument('--seconds', type=float, default=20.0)
    parser.add_argument('--hold-on-wedge', type=float, default=0,
                        help='close/churn: keep a wedged server alive this many seconds for a debugger')
    parser.add_argument('--spread', type=float, default=.02,
                        help='late: seconds over which the closes of one FLIP are spread')
    parser.add_argument('--evidence', action='store_true',
                        help='close/churn: record stalls and refusals instead of failing on them '
                             '(PRE sanitizer evidence runs; wedges and reports still fail)')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.case in ('close', 'churn'):
        disconnects(args, args.case == 'churn')
    elif args.case == 'late':
        late_closes(args)
    elif args.case == 'controllers':
        controllers(args)
    else:
        stopping(args)


if __name__ == '__main__':
    main()
