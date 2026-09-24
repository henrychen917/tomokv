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

from _lib import Conn, encode
from mdbqsbr_live import wait_parked, no_core_dump
from shutdown_report import load_report, require_io_conservation

ROOT = Path(__file__).resolve().parents[1]


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
            productive('127.0.0.1', args.port, 0)
            parks = [wait_parked(proc)]
            if args.mode == '2s':
                assert control.cmd('FLIP', 3, 5) == b'OK', 'manual shrink must finish'
                productive('127.0.0.1', args.port, 1)
                assert control.cmd('FLIP', 6, 2) == b'OK', 'manual grow must finish'
                productive('127.0.0.1', args.port, 2)
                parks.append(wait_parked(proc))
            control.close(); control = None
            parks.append(wait_parked(proc))
            (directory / 'park-witness.json').write_text(json.dumps(parks, indent=2) + '\n')
            # TERM while the kernel park is witnessed; no unrelated process is signalled.
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=15)
            assert proc.returncode == 0, 'shutdown failed'
        finally:
            if control is not None:
                control.close()
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)
    report = load_report(log_path)
    if args.legacy_control:
        try:
            require_io_conservation(report, edges=False)
        except SystemExit as error:
            assert 'completed interval is not exact' in str(error), str(error)
            return dict(legacy_control='REJECTED', reason=str(error))
        raise AssertionError('legacy dropped-window accounting was accepted')
    return require_io_conservation(report, edges=args.edges)


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
