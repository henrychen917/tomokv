#!/usr/bin/env python3
"""Focused PS5/PS7 oracle harness; fresh children/data, no benchmark or gate row."""
import argparse
import contextlib
from pathlib import Path
import subprocess
import sys
import time

from _lib import Conn, RespError, info, wait_ready
from persistfix import check_port_owner, guard_port


@contextlib.contextmanager
def boot(argv, cores, port, log_path):
    guard_port(port)
    with log_path.open('wb') as log:
        child = subprocess.Popen(['taskset', '-c', cores, *argv], stdout=log, stderr=log)
        try:
            # Redis and TomoKV have different log banners; both expose process_id.
            ready = wait_ready('127.0.0.1', port, timeout=20, process=child)
            ready.close()
            check_port_owner(port, child.pid)
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    raise AssertionError('owned child did not stop: ' + str(log_path))
            assert child.returncode == 0, log_path.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--oracle', type=Path, default=Path('/tmp/claude-1000/redis74/src/redis-server'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--cores', default='112-119')
    parser.add_argument('--load-cores', default='120-127')
    parser.add_argument('--port', type=int, default=24810)
    parser.add_argument('--mode', choices=('1s', '2s'), default='2s')
    parser.add_argument('--databases', type=int, choices=(1, 16), default=1)
    parser.add_argument('--expect-pre-failure', action='store_true')
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=False)
    target_dir, oracle_dir = args.root / 'target', args.root / 'oracle'
    target_dir.mkdir()
    oracle_dir.mkdir()
    target = [str(args.binary.resolve()), '--bind', '127.0.0.1', '--port', str(args.port),
              '--shards', '16', '--ratio', '6:2', '--thread-mode', args.mode,
              '--databases', str(args.databases), '--dir', str(target_dir), '--save', '',
              '--appendonly', 'yes', '--appendfsync', 'no', '--auto-aof-rewrite-percentage', '0']
    oracle = [str(args.oracle.resolve()), '--bind', '127.0.0.1', '--port', str(args.port + 1),
              '--dir', str(oracle_dir), '--save', '', '--appendonly', 'yes', '--appendfsync', 'no',
              '--auto-aof-rewrite-percentage', '0', '--protected-mode', 'no']
    with boot(target, args.cores, args.port, args.root / 'target.log'), \
            boot(oracle, args.load_cores, args.port + 1, args.root / 'oracle.log'):
        command = ['taskset', '-c', args.load_cores, sys.executable, 'tests/differ.py',
                   '127.0.0.1', str(args.port), '127.0.0.1', str(args.port + 1), 'psfix', '7']
        for protocol in ([], ['-3']):
            result = subprocess.run(command + protocol, capture_output=True, text=True, timeout=90)
            output = result.stdout + result.stderr
            (args.root / ('differ-resp3.log' if protocol else 'differ-resp2.log')).write_text(output)
            print(output, end='', flush=True)
            if args.expect_pre_failure:
                assert result.returncode != 0 and 'immutable' in output, output
                print('PSFIX PRE CONTROL: differential rejected immutable aof-load-truncated')
                return
            assert result.returncode == 0, result.returncode

        conn = Conn('127.0.0.1', args.port)
        try:
            before = int(info(conn, 'persistence')['rdb_saves'])
            moved = args.root / 'target-moved'
            target_dir.rename(moved)
            try:
                reply = conn.cmd('SAVE')
                assert isinstance(reply, RespError), reply
                assert int(info(conn, 'persistence')['rdb_saves']) == before
            finally:
                moved.rename(target_dir)
            conn.must('SAVE')
            assert int(info(conn, 'persistence')['rdb_saves']) == before + 1
            print('PSFIX failed SAVE leaves count unchanged; successful retry increments once')
            before = int(info(conn, 'persistence')['rdb_saves'])
            rewrites = int(info(conn, 'persistence')['aof_rewrites'])
            conn.must('BGREWRITEAOF')
            deadline = time.monotonic() + 15
            while True:
                fields = info(conn, 'persistence')
                if int(fields['aof_rewrites']) == rewrites + 1 and fields['aof_rewrite_in_progress'] == '0':
                    break
                assert time.monotonic() < deadline, 'AOF rewrite did not complete'
                time.sleep(.01)
            assert int(fields['rdb_saves']) == before
            print('PSFIX AOF rewrite completes without incrementing rdb_saves')
        finally:
            conn.close()
    print('PSFIX PASS: %s databases=%d RESP2/RESP3' % (args.mode, args.databases))


if __name__ == '__main__':
    main()
