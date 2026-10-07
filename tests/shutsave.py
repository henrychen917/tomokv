#!/usr/bin/env python3
"""Maintainer-only wire proof: terminal shutdown during an observed large save."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import select
import signal
import subprocess
import time

from _lib import Conn, info, wait_ready
from persistfix import check_port_owner, guard_port
from psfix import seed_save_load


@contextlib.contextmanager
def boot(args, directory, label, appendonly):
    guard_port(args.port)
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()),
            '--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(directory),
            '--shards', '16', '--databases', '16', '--atomic', '1',
            '--thread-mode', args.mode, '--net-io', args.net_io, '--save', '',
            '--appendonly', appendonly, '--appendfsync', 'no',
            '--auto-aof-rewrite-percentage', '0', '--enable-debug-command', 'yes',
            '--client-lb', '0']
    if args.mode == '2s':
        argv += ['--ratio', '6:2']
    path = directory / (label + '.log')
    (directory / (label + '.argv.json')).write_text(json.dumps(argv) + '\n')
    with path.open('wb') as log:
        process = subprocess.Popen(argv, stdout=log, stderr=log)
        conn = None
        try:
            conn = wait_ready('127.0.0.1', args.port, timeout=30, process=process)
            check_port_owner(args.port, process.pid)
            yield process, conn, path
        finally:
            if conn:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def stop_peer(args, saving):
    owner = saving.must('DEBUG', 'IO-THREAD')
    for _ in range(64):
        peer = Conn('127.0.0.1', args.port, timeout=10)
        if peer.must('DEBUG', 'IO-THREAD') != owner:
            return peer
        peer.close()
    raise AssertionError('different shutdown IO owner never armed in 64 connections')


def attempt(args, directory):
    snapshot = directory / 'dump.tomo'
    with boot(args, directory, 'write', 'yes') as (process, conn, log):
        assert conn.must('SET', 'shutsave:baseline', 'old') == b'OK'
        assert conn.must('SAVE') == b'OK'
        baseline = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        seed_save_load([conn], args.keys)
        peer = stop_peer(args, conn)
        try:
            conn.send(args.operation)
            if args.operation == 'BGSAVE':
                assert conn.read() == b'Background saving started'
            deadline = time.monotonic() + 10
            witness = None
            while time.monotonic() < deadline and process.poll() is None:
                partial = list(directory.glob('dump.tomo.tmp.*'))
                for path in partial:
                    try:
                        size = path.stat().st_size
                    except FileNotFoundError:
                        continue
                    # Observe a real written prefix well before the full data image.
                    if 65536 <= size < args.keys * 4096 // 2:
                        witness = dict(path=str(path), bytes=size)
                        break
                if witness:
                    break
                if args.operation == 'SAVE' and select.select([conn.sock], [], [], 0)[0]:
                    assert conn.read() == b'OK', 'SAVE failed while arming'
                    break
                time.sleep(.001)
            if witness is None:
                print('INVALID arming: no partial-save window; fresh-state retry', flush=True)
                return None
            start = time.monotonic()
            if args.action == 'sigterm':
                process.send_signal(signal.SIGTERM)
            else:
                peer.send('SHUTDOWN', *(['NOSAVE'] if args.action == 'nosave' else []))
            status = process.wait(timeout=max(.001, 10 - (time.monotonic() - start)))
            elapsed = time.monotonic() - start
            text = log.read_text()
            if args.expect_pre_fatal:
                assert status != 0 and 'fatal: database worker shutdown timeout' in text, text
                return dict(witness=witness, status=status, elapsed=elapsed,
                            result='PRE worker-shutdown fatal reproduced')
            assert status == 0 and elapsed <= 10, (status, elapsed, text)
            assert 'fatal: database' not in text, text
        finally:
            peer.close()
    assert not list(directory.glob('dump.tomo.tmp.*')), 'abandoned snapshot temporary file remains'
    after = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    # Disable AOF for this boot: success must validate/load the actual snapshot,
    # rather than silently recovering the acknowledged writes from the journal.
    with boot(args, directory, 'snapshot-check', 'no') as (process, conn, log):
        assert conn.must('GET', 'shutsave:baseline') == b'old'
        count = conn.must('DBSIZE', 'NOW')
        expected = 1 if after == baseline else args.keys + 1
        assert count == expected, ('snapshot key count', count, expected)
        if after != baseline:
            for index in (0, args.keys - 1):
                value = conn.must('GET', 'psfix:save-load:%d' % index)
                assert isinstance(value, bytes) and len(value) == 4096
        conn.send('SHUTDOWN', 'NOSAVE')
        assert process.wait(timeout=10) == 0, log.read_text()
    return dict(witness=witness, status=status, elapsed=elapsed, snapshot_sha256=after,
                result='completed' if after != baseline else 'cleanly abandoned', keys=count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--cores', default='112-119')
    parser.add_argument('--port', type=int, default=18340)
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--operation', choices=('SAVE', 'BGSAVE'), default='SAVE')
    parser.add_argument('--action', choices=('sigterm', 'nosave', 'shutdown'), required=True)
    parser.add_argument('--keys', type=int, default=131072)
    parser.add_argument('--expect-pre-fatal', action='store_true')
    args = parser.parse_args()
    if args.keys < 64:
        parser.error('--keys must be at least 64 to witness a written prefix')
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=False)
    for retry in range(1, 4):
        directory = args.root / ('attempt-%d' % retry)
        directory.mkdir()
        result = attempt(args, directory)
        if result is not None:
            result.update(mode=args.mode, operation=args.operation, action=args.action,
                          net_io=args.net_io, value_bytes=args.keys * 4096,
                          server_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest())
            (args.root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            print('SHUTSAVE PASS: ' + json.dumps(result), flush=True)
            return
    raise AssertionError('partial-save shutdown window never armed in three fresh datasets')


if __name__ == '__main__':
    main()
