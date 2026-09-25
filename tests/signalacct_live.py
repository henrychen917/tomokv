#!/usr/bin/env python3
"""MAINLINE ONLY: productive IO, idle, and IO->EX->IO conservation proof.

Never a benchmark. Each unentered mechanism window gets a fresh process, at most
three attempts, then FAIL. Endpoint tolerance is fixed in shutdown_report.py.
Use the witness build (real sweep service, cold diagnostics) for --edges. The
legacy PAD control must fail the completed-interval equality, not a boot check.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from _lib import Conn, RespError, encode
from mdbqsbr_live import wait_parked, no_core_dump
from shutdown_report import load_report, require_io_conservation

ROOT = Path(__file__).resolve().parents[1]


class ReplyCapture:
    """Record the bytes consumed by the real RESP parser, including partial replies."""
    def __init__(self, reader):
        self.reader = reader
        self.data = bytearray()

    def read(self, *args):
        data = self.reader.read(*args)
        self.data.extend(data)
        return data

    def readline(self, *args):
        data = self.reader.readline(*args)
        self.data.extend(data)
        return data


def manual_flip(control, io, ex, directory, events):
    event = dict(command=['FLIP', io, ex], timeout_s=15)
    reader = control.file
    capture = ReplyCapture(reader)
    control.file = capture
    begin = time.monotonic_ns()
    try:
        reply = control.cmd('FLIP', io, ex)
        event.update(reply=repr(reply), reply_type=type(reply).__name__,
                     classification='ok' if reply == b'OK' else
                         'server-error' if isinstance(reply, RespError) else 'unexpected-reply')
    except Exception as error:
        event.update(exception=repr(error), classification=
                     'timeout' if isinstance(error, TimeoutError) else 'transport-or-parser-error')
        raise
    finally:
        event.update(elapsed_ns=time.monotonic_ns() - begin,
                     wire_hex=capture.data.hex(), wire_repr=repr(bytes(capture.data)))
        control.file = reader
        events.append(event)
        (directory / 'flips.json').write_text(json.dumps(events, indent=2) + '\n')
    if reply != b'OK':
        raise AssertionError('manual FLIP failed: ' + json.dumps(event))


def failure_receipt(args, directory, proc, phase, error, events):
    """Best-effort diagnostics never replace the original failure or reuse a timed-out reader."""
    receipt = dict(phase=phase, error=repr(error), flips=events,
                   server_returncode=proc.poll(), info_flip={}, info_error=None)
    probe = None
    try:
        if receipt['server_returncode'] is not None:
            raise RuntimeError('server already exited; INFO unavailable')
        probe = Conn('127.0.0.1', args.port, timeout=2)
        reply = probe.cmd('INFO', 'ALL')
        receipt['info_reply'] = repr(reply)
        if not isinstance(reply, bytes):
            raise AssertionError('INFO returned ' + repr(reply))
        for line in reply.decode('utf-8', 'replace').splitlines():
            key, sep, value = line.partition(':')
            if sep and (key.startswith(('flip_', 'flipctl_')) or
                        key in ('io_threads', 'ex_threads', 'connected_clients')):
                receipt['info_flip'][key] = value
    except Exception as diagnostic_error:
        receipt['info_error'] = repr(diagnostic_error)
    finally:
        if probe is not None:
            probe.close()
    with (directory / 'server.log').open('rb') as log:
        log.seek(0, 2)
        log.seek(max(0, log.tell() - 16384))
        tail = log.read()
    receipt.update(server_stderr_tail=tail.decode('utf-8', 'replace'),
                   server_stderr_tail_hex=tail.hex())
    rendered = json.dumps(receipt, indent=2) + '\n'
    (directory / 'failure.json').write_text(rendered)
    print(rendered, file=sys.stderr, flush=True)


def productive(host, port, sequence):
    def worker(index):
        c = Conn(host, port, timeout=15)
        try:
            key = 'signalacct:%d:%d' % (sequence, index)
            for turn in range(64):
                value = '%d:%d' % (sequence, turn)
                c.raw(b''.join(encode('SET', key, value) + encode('GET', key) for _ in range(16)))
                for _ in range(16):
                    assert c.read() == b'OK', 'productive SET reply'
                    assert c.read() == value.encode(), 'same-connection RYOW reply'
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(worker, range(24)))


def attempt(args, index):
    directory = args.output / ('attempt-%d' % index)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / 'server.log'
    command = ['taskset', '-c', args.cores, str(args.binary.resolve()), '--bind', '127.0.0.1',
               '--port', str(args.port), '--thread-mode', args.mode, '--shards', '16',
               '--read-local', str(args.read_local), '--overlap', str(args.overlap),
               '--reorder', str(args.reorder), '--databases', str(args.databases),
               '--net-io', args.net_io, '--flip-auto', '0', '--enable-debug-command', 'yes',
               '--save', '', '--protected-mode', 'no']
    if args.mode == '2s':
        command += ['--ratio', '6:2']
    (directory / 'argv.json').write_text(json.dumps(command, indent=2) + '\n')
    with log_path.open('wb') as log:
        proc = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                preexec_fn=no_core_dump)
        control = None
        events = []
        phase = 'boot'
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise AssertionError('boot failed: ' + log_path.read_text()[-3000:])
                try:
                    control = Conn('127.0.0.1', args.port, timeout=1)
                    assert control.cmd('PING') == b'PONG'
                    break
                except (OSError, EOFError):
                    if control is not None:
                        control.close(); control = None
                    time.sleep(0.025)
            assert control is not None, 'boot readiness never fired'
            control.sock.settimeout(15)
            phase = 'productive-0'
            productive('127.0.0.1', args.port, 0)
            phase = 'park-before-flip'
            parks = [wait_parked(proc)]
            if args.mode == '2s':
                phase = 'manual-shrink'
                manual_flip(control, 3, 5, directory, events)
                phase = 'productive-1'
                productive('127.0.0.1', args.port, 1)
                phase = 'manual-grow'
                manual_flip(control, 6, 2, directory, events)
                phase = 'productive-2'
                productive('127.0.0.1', args.port, 2)
                phase = 'park-after-flip'
                parks.append(wait_parked(proc))
            control.close(); control = None
            phase = 'park-before-stop'
            parks.append(wait_parked(proc))
            (directory / 'park-witness.json').write_text(json.dumps(parks, indent=2) + '\n')
            # TERM while the kernel park is witnessed; no unrelated process is signalled.
            proc.send_signal(signal.SIGTERM)
            phase = 'shutdown'
            proc.wait(timeout=15)
            assert proc.returncode == 0, 'shutdown failed'
        except Exception as error:
            failure_receipt(args, directory, proc, phase, error, events)
            raise
        finally:
            if control is not None:
                control.close()
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)
    try:
        report = load_report(log_path)
        if args.legacy_control:
            try:
                require_io_conservation(report, edges=False)
            except SystemExit as error:
                assert 'completed interval is not exact' in str(error), str(error)
                return dict(legacy_control='REJECTED', reason=str(error))
            raise AssertionError('legacy dropped-window accounting was accepted')
        return require_io_conservation(report, edges=args.edges)
    except (Exception, SystemExit) as error:
        failure_receipt(args, directory, proc, 'conservation', error, events)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cores', default='0-7')
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--read-local', type=int, choices=(0, 1), required=True)
    parser.add_argument('--overlap', type=int, choices=(0, 1), required=True)
    parser.add_argument('--reorder', type=int, choices=(0, 1), required=True)
    parser.add_argument('--databases', type=int, choices=(1, 16), default=1)
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--port', type=int, default=16739)
    parser.add_argument('--edges', action='store_true')
    parser.add_argument('--legacy-control', action='store_true')
    args = parser.parse_args()
    args.output = args.output.resolve()
    errors = []
    for index in range(1, 4):
        try:
            result = attempt(args, index)
        except SystemExit as error:
            # Only an unentered window is rearmed. A conservation defect is final.
            if 'window never opened' not in str(error):
                raise
            errors.append(str(error))
            continue
        print(json.dumps(dict(result=result, attempts=index), indent=2))
        return 0
    raise AssertionError('unentered mechanism window after three fresh boots: ' + repr(errors))


if __name__ == '__main__':
    sys.exit(main())
