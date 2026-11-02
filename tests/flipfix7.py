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
    extra = ['--save', '3600 1'] if case == 'signal' else []
    if case == 'tls':
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
            held = conn(4 if case in ('blocked', 'tls') else 1, True)
            control, probe, writer = conn(0), conn(0), conn(5)
            if case == 'tls':
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
            target = (1, 7) if case in ('blocked', 'tls') else (7, 1)
            keys = []
            if case == 'blocked':
                held.send('BLPOP', 'flipfix7:list', 0)
                s.wait(lambda: s.stats(control, 'clients').get('blocked_clients') == 1,
                       'BLPOP never blocked')
            elif case in ('late', 'signal', 'output'):
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
                if case == 'output':
                    delete.join(30)
                    assert result['deleted'] == 1024
                    time.sleep(.05)
                else:
                    time.sleep((.004, .008, .001, .016, .002, .032)[attempt % 6])
            start = time.monotonic()
            control.send('FLIP', *target)
            ft = thread_read(control, result, 'flip')
            # Established unrelated connection; exactly one PING across the transition.
            probe.send('PING')
            pt = thread_read(probe, result, 'ping')
            ft.join(1)
            if ft.is_alive():
                diag = snapshot(b, args, directory)
                result['stage'] = diag['stage']
                result['clauses'] = [{k: c[k] for k in ('io', 'id_', 'send_inflight_',
                    'barrier_owners_', 'connection_flags_', 'tls_slot_', 'obuf_bytes_')}
                    for c in diag['clients'] if c['obuf_bytes_'] or c['connection_flags_'] & 128
                    or c['tls_slot_'] != 4294967295]
            if case == 'signal':
                # PRE must have crossed commit; never count a precommit refusal as IO5.1.
                if 'ClientInstall' not in result.get('stage', ''):
                    result['unarmed'] = True
                else:
                    b.proc.send_signal(signal.SIGTERM)
                    result['signal_exit'] = b.wait_exit(12)
                    result['saved'] = (directory / 'dump.tomo').exists()
            if b.proc.poll() is None:
                ft.join(6)
                if ft.is_alive():
                    result['wedge'] = True
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
                if case == 'blocked':
                    assert writer.must('LPUSH', 'flipfix7:list', 'v') == 1
                    assert held.read() == [b'flipfix7:list', b'v']
                elif case == 'tls':
                    assert held.command('PING') == b'PONG'
                assert writer.must('GET', 'flipfix7:ack:0') == b'saved'
            result['elapsed'] = time.monotonic() - start
        finally:
            # PRE signal witness may require SIGKILL; that result is evidence, never a pass.
            if b.exit is None:
                b.stop()
            result['exit'] = b.exit
    if case == 'signal' and result.get('signal_exit'):
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
                for attempt in range(48 if case in ('late','signal') else 1):
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
                        assert row['flip_seconds'] < 1 and row['ping_seconds'] < 1, row
                    rows.append(row)
                    break
                else:
                    raise AssertionError('late-output window never armed on fresh state')
    (args.output / 'summary.json').write_text(json.dumps(rows, indent=2)+'\n')
    print('PASS flipfix7', args.arm, len(rows), flush=True)

if __name__ == '__main__':
    main()
