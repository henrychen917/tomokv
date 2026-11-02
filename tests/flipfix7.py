#!/usr/bin/env python3
"""Bounded FLIP liveness witnesses, fresh 6:2/16-shard boot for every leg/attempt.

PRE evidence uses a read-only debugger snapshot after the one-second stall bound.
An unopened late-output window is retried on fresh state, then fails. No rates.
"""
import argparse
import contextlib
import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
import traceback

from _lib import Conn, RespError, encode
import snapfix as s
import tls

ROOT = Path(__file__).resolve().parents[1]


def snapshot(b, args, directory):
    ns = 'tomo_db0' if args.databases == 1 else 'tomo'
    cmd = ['taskset', '-c', args.cores, 'gdb', '-q', '-batch', '-p', str(b.proc.pid),
           '-ex', 'set print elements 8', '-ex', 'set print repeats 0',
           '-ex', "python namespace = '" + ns + "'",
           '-ex', 'source ' + str(ROOT / 'tools/flipfix7_snapshot.py'), '-ex', 'detach']
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    (directory / 'snapshot.log').write_text(p.stdout + p.stderr)
    rows = [x.removeprefix('FLIPFIX7_SNAPSHOT ') for x in p.stdout.splitlines()
            if x.startswith('FLIPFIX7_SNAPSHOT ')]
    assert len(rows) == 1, p.stdout + p.stderr
    result = json.loads(rows[0])
    (directory / 'snapshot.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def thread_read(c, out, key):
    def run():
        start = time.monotonic()
        try:
            out[key] = c.read()
        except Exception as e:
            out[key] = repr(e)
        out[key + '_seconds'] = time.monotonic() - start
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def trial(args, directory, engine, atomic, case, attempt):
    stays = case.endswith('-stay')
    base = 'signal' if case in ('signal-int', 'sigint') else case.removesuffix('-stay')
    extra = ['--save', '3600 1'] if base == 'signal' else []
    if base == 'tls':
        cert = ROOT / 'build/flipfix7/certs'
        if not (cert / 'server.crt').exists():
            tls.generate(str(cert))
        extra += ['--tls-port', str(args.port + 1), '--tls-cert-file', str(cert / 'server.crt'),
                  '--tls-key-file', str(cert / 'server.key'), '--tls-ca-cert-file',
                  str(cert / 'ca.crt'), '--tls-auth-clients', 'no']
    b = s.Boot(args, directory, '2s', engine, atomic, False, extra)
    result = dict(case=case, engine=engine, atomic=atomic, databases=args.databases,
                  read_local=args.read_local, attempt=attempt)
    with contextlib.ExitStack() as stack:
        def conn(io, small=False):
            for _ in range(96):
                c = stack.enter_context(contextlib.closing(Conn('127.0.0.1', args.port,
                        timeout=30, rcvbuf=4096 if small else None)))
                if s.io_thread(c) == io:
                    return c
            raise AssertionError('IO placement never armed')
        try:
            held = conn(4 if base in ('blocked', 'blmove', 'tls') else 1, True)
            control, probe, writer = conn(0), conn(0), conn(5)
            observer = conn(0)
            if base == 'tls':
                for _ in range(96):
                    c = stack.enter_context(contextlib.closing(tls.Conn('127.0.0.1', args.port+1,
                                tls.context(str(cert)), timeout=30)))
                    if int(c.command('DEBUG', 'IO-THREAD')) == 4:
                        held = c
                        break
                else:
                    raise AssertionError('TLS connection never reached converting IO')
            control.raw(b''.join(encode('SET', f'flipfix7:ack:{i}', 'saved') for i in range(1000)))
            assert [control.read() for _ in range(1000)] == [b'OK'] * 1000
            result['acknowledged'] = 1000
            target = ((7, 1) if base == 'tls' else (5, 3)) if stays else ((1, 7) if base in (
                'blocked', 'tls', 'output', 'borrow', 'late-move') else (7, 1))
            before_io = s.io_thread(held) if base != 'tls' else int(held.command('DEBUG', 'IO-THREAD'))
            keys = []
            if base in ('blocked', 'blmove'):
                if base == 'blmove':
                    held.send('BLMOVE', 'flipfix7:list', 'flipfix7:dest', 'LEFT', 'RIGHT', 0)
                else:
                    held.send('BLPOP', 'flipfix7:list', 0)
                s.wait(lambda: s.stats(control, 'clients').get('blocked_clients') == 1,
                       'BLPOP never blocked')
            elif base == 'borrow':
                value = b'b' * (8 << 20)
                assert control.must('SET', 'flipfix7:borrow', value) == b'OK'
                if args.read_local:
                    # The lane intentionally copies. Its supported WATCH fallback
                    # executes GET on the owner and must arm a real FlatStore borrow.
                    assert held.must('WATCH', 'flipfix7:borrow') == b'OK'
                    result['borrow_owner_fallback'] = 'WATCH'
                held.send('GET', 'flipfix7:borrow')
                s.wait(lambda: control.must('DEBUG', 'BORROWCOUNT') > 0,
                       'large GET never armed an outstanding borrow')
                result['borrow_armed'] = True
                time.sleep(.05)
            elif base in ('late', 'late-move', 'signal', 'output'):
                keys = [(f'flipfix7:{i:04}:'.encode() + b'x' * 8192)[:8192] for i in range(1024)]
                elements = [f'e{x}' for x in range(3000)]
                for i in range(0, len(keys), 16):
                    writer.raw(b''.join(encode('RPUSH', k, *elements) for k in keys[i:i+16]))
                    assert [writer.read() for _ in range(16)] == [3000] * 16
                control.must('CONFIG', 'SET', 'notify-keyspace-events', 'Eg')
                held.send('SUBSCRIBE', '__keyevent@0__:del')
                assert held.read() == [b'subscribe', b'__keyevent@0__:del', 1]
                writer.send('DEL', *keys)
                result['delete_thread'] = None
                delete = thread_read(writer, result, 'deleted')
                if base == 'output':
                    delete.join(30)
                    assert result['deleted'] == 1024
                    time.sleep(.05)
                else:
                    time.sleep((.004, .008, .001, .016, .002, .032)[attempt % 6])
            signal_watch = None
            if base == 'signal' and args.arm == 'post':
                def send_signal():
                    until = time.monotonic() + 1
                    while time.monotonic() < until and b.proc.poll() is None:
                        report = observer.must('FLIP')
                        status = dict(zip(report[::2], report[1::2]))
                        if status.get(b'moving') == 1:
                            result['signal_during_flip'] = True
                            first = signal.SIGTERM if case == 'signal' else signal.SIGINT
                            b.proc.send_signal(first)
                            if case == 'sigint':
                                until = time.monotonic() + 2
                                while b.proc.poll() is None and time.monotonic() < until:
                                    pending = 0
                                    try:
                                        status_lines = Path(f'/proc/{b.proc.pid}/status').read_text().splitlines()
                                    except FileNotFoundError:
                                        break
                                    for line in status_lines:
                                        if line.startswith(('ShdPnd:', 'SigPnd:')):
                                            pending |= int(line.split()[1], 16)
                                    if not pending & (1 << (signal.SIGINT - 1)):
                                        break
                                    time.sleep(.0005)
                                if b.proc.poll() is not None:
                                    result['first_signal_exited'] = True
                                    result['unarmed'] = True
                                else:
                                    result['second_signal_sent'] = True
                                    result['second_signal_started'] = time.monotonic()
                                    b.proc.send_signal(signal.SIGINT)
                            return
                signal_watch = threading.Thread(target=send_signal, daemon=True)
                signal_watch.start()
            start = time.monotonic()
            control.send('FLIP', *target)
            ft = thread_read(control, result, 'flip')
            # Established unrelated connection; exactly one PING across the transition.
            probe.send('PING')
            pt = thread_read(probe, result, 'ping')
            ft.join(1)
            if ft.is_alive() and b.proc.poll() is None:
                diag = snapshot(b, args, directory)
                result['stage'] = diag['stage']
                result['clauses'] = [{k: c[k] for k in ('io', 'id_', 'send_inflight_',
                    'barrier_owners_', 'connection_flags_', 'tls_slot_', 'obuf_bytes_')}
                    for c in diag['clients'] if c['obuf_bytes_'] or c['connection_flags_'] & 128
                    or c['tls_slot_'] != 4294967295]
            if signal_watch:
                signal_watch.join(2)
                if result.get('signal_during_flip'):
                    bound = args.second_bound if result.get('second_signal_sent') else args.signal_bound
                    result['signal_exit'] = b.wait_exit(bound)
                    result['saved'] = (directory / 'dump.tomo').exists()
                    if result.get('second_signal_sent'):
                        result['second_signal_seconds'] = time.monotonic() - result['second_signal_started']
                        assert result['second_signal_seconds'] < args.second_bound, result
                        assert 'You insist... exiting now.' in b.log.read_text(errors='replace'), result
                else:
                    result['unarmed'] = True
            if case == 'signal' and args.arm == 'pre':
                # PRE must have crossed commit; never count a precommit refusal as IO5.1.
                if 'ClientInstall' not in result.get('stage', ''):
                    result['unarmed'] = True
                else:
                    b.proc.send_signal(signal.SIGTERM)
                    result['signal_exit'] = b.wait_exit(args.signal_bound)
                    result['saved'] = (directory / 'dump.tomo').exists()
            if b.proc.poll() is None:
                ft.join(6)
                if ft.is_alive():
                    result['wedge'] = True
                if args.arm == 'post' and not ft.is_alive():
                    counters = s.stats(observer)
                    result['counters'] = {k: v for k, v in counters.items() if k.startswith('flip_')}
                    if case in ('late', 'late-move'):
                        result['unarmed'] = not (counters.get('flip_late_output', 0) +
                                                 counters.get('flip_output_transferred', 0))
                        if case == 'late':
                            # Initial non-draining output could now be retained; that
                            # is D18.3, not proof of the post-IoDrain publication window.
                            result['unarmed'] |= counters.get('flip_skipped_output', 0) != 0
                        if case == 'late-move':
                            result['unarmed'] = not counters.get('flip_output_transferred', 0)
                # Release the blocker and verify EVERY payload, not just the FLIP reply.
                if keys:
                    held.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
                    held.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_WINDOW_CLAMP, 4 << 20)
                    received = [held.read() for _ in keys]
                    assert sorted(x[2] for x in received) == sorted(keys)
                    assert all(x[:2] == [b'message', b'__keyevent@0__:del'] for x in received)
                    result['notifications'] = len(received)
                    delete.join(30)
                    assert result['deleted'] == 1024, result
                ft.join(10)
                pt.join(10)
                assert not ft.is_alive() and not pt.is_alive(), result
                if base in ('blocked', 'blmove'):
                    assert writer.must('LPUSH', 'flipfix7:list', 'v') == 1
                    assert held.read() == ([b'flipfix7:list', b'v'] if base == 'blocked' else b'v')
                    if base == 'blmove':
                        assert writer.must('LRANGE', 'flipfix7:dest', 0, -1) == [b'v']
                elif base == 'tls':
                    assert held.command('PING') == b'PONG'
                if base == 'borrow':
                    held.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
                    held.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_WINDOW_CLAMP, 4 << 20)
                    assert held.read() == value
                    result['borrow_bytes'] = len(value)
                    s.wait(lambda: writer.must('DEBUG', 'BORROWCOUNT') == 0,
                           'borrow release did not reach the installed owner')
                    result['borrow_released'] = True
                    if args.read_local:
                        assert held.must('UNWATCH') == b'OK'
                if keys:
                    held.send('UNSUBSCRIBE')
                    assert held.read() == [b'unsubscribe', b'__keyevent@0__:del', 0]
                result['held_io_after'] = (s.io_thread(held) if base != 'tls' else
                                           int(held.command('DEBUG', 'IO-THREAD')))
                if stays or base in ('blocked', 'tls', 'output', 'borrow'):
                    assert result['held_io_after'] == before_io, result
                assert writer.must('GET', 'flipfix7:ack:0') == b'saved'
            if args.arm == 'post' and base in ('blocked', 'blmove', 'tls', 'output', 'borrow'):
                kind = 'blocked' if base == 'blmove' else 'output' if base == 'borrow' else base
                counter = 'flip_' + ('skipped_' if stays else 'refused_') + kind
                assert result['counters'].get(counter, 0) > 0, (counter, result)
                if stays:
                    assert result['flip'] == b'OK', result
                else:
                    phrase = {'blocked': 'blocked connection', 'tls': 'TLS connection',
                              'output': 'non-draining output'}[kind]
                    assert phrase in str(result['flip']), result
                    result['refusal_stage'] = 'IoDrain'
                    result['refusal_stage_source'] = 'flip_immovable_refused production call site'
                    result['failing_clause'] = phrase
            result['elapsed'] = time.monotonic() - start
        finally:
            # PRE signal witness may require SIGKILL; that result is evidence, never a pass.
            if b.exit is None:
                b.stop()
            result['exit'] = b.exit
    if case in ('signal', 'signal-int') and result.get('signal_exit'):
        with s.Boot(args, directory, '2s', engine, atomic, False, name='restart') as restart:
            values = restart.c.must('MGET', *[f'flipfix7:ack:{i}' for i in range(1000)])
            result['reloaded_acknowledged'] = sum(x == b'saved' for x in values)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--cores', default='48-55')
    ap.add_argument('--port', type=int, default=21000)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--arm', choices=('pre','post'), required=True)
    ap.add_argument('--cases', default='blocked,tls,late,signal')
    ap.add_argument('--engines', default='uring,epoll')
    ap.add_argument('--databases', type=int, default=16)
    ap.add_argument('--read-local', type=int, default=0)
    ap.add_argument('--atomics', default='0,1')
    ap.add_argument('--stall', type=float, default=30)
    ap.add_argument('--signal-bound', type=float, default=12)
    ap.add_argument('--second-bound', type=float, default=.75)
    args = ap.parse_args()
    os.environ['LC_ALL'] = 'C'
    args.output.mkdir(parents=True, exist_ok=True)
    # Allow the read-only sibling debugger to inspect only these owned test children.
    # PR_SET_PTRACER is inherited across exec; it does not change production sources.
    popen = subprocess.Popen
    def launch(*a, **kw):
        if isinstance(a[0], list) and str(Path(args.binary).resolve()) in a[0]:
            kw['preexec_fn'] = lambda: ctypes.CDLL(None).prctl(0x59616d61, ctypes.c_ulong(-1).value, 0, 0, 0)
        return popen(*a, **kw)
    subprocess.Popen = launch
    rows = []
    for engine in args.engines.split(','):
        for atomic in map(int, args.atomics.split(',')):
            for case in args.cases.split(','):
                for attempt in range(48 if case in ('late','late-move','signal','signal-int','sigint') else 1):
                    directory = args.output / f'{engine}-a{atomic}-d{args.databases}-r{args.read_local}-{case}-{attempt}'
                    try:
                        row = trial(args, directory, engine, atomic, case, attempt)
                    except Exception:
                        row = dict(case=case, error=traceback.format_exc())
                    row = json.loads(json.dumps(row, default=str))
                    (directory / 'result.json').write_text(json.dumps(row, indent=2)+'\n')
                    print(json.dumps(row), flush=True)
                    if 'error' in row:
                        raise AssertionError(row)
                    if args.arm == 'pre':
                        if case in ('late', 'signal') and 'ClientInstall' not in row.get('stage', ''):
                            continue
                        assert row.get('flip_seconds', 99) >= 1, row
                        assert 'stage' in row and row['clauses'], row
                    else:
                        if case not in ('signal', 'signal-int', 'sigint'):
                            assert row['flip_seconds'] < 1 and row['ping_seconds'] < 1, row
                        if row.get('unarmed'):
                            continue
                        if case == 'sigint':
                            assert row.get('second_signal_sent'), row
                            assert row['signal_exit'] == dict(rc=1, forced=False), row
                        elif case in ('signal', 'signal-int'):
                            assert row['signal_exit'] == dict(rc=0, forced=False), row
                            assert row['saved'] and row['reloaded_acknowledged'] == 1000, row
                        else:
                            assert row['flip_seconds'] < 1 and row['ping_seconds'] < 1, row
                    rows.append(row)
                    break
                else:
                    raise AssertionError('late-output window never armed on fresh state')
    (args.output / 'summary.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('PASS flipfix7', args.arm, len(rows), flush=True)

if __name__ == '__main__':
    main()
