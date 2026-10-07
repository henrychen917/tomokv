#!/usr/bin/env python3
"""Focused PS5/PS7 oracle harness; fresh children/data, no benchmark or gate row."""
import argparse
import contextlib
from pathlib import Path
import random
import subprocess
import sys
import time

from _lib import Conn, RespError, encode, info, wait_ready
from persistfix import check_port_owner, guard_port
from _save_timeout import save_reply_timeout, save_timeout_seconds


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


def seed_save_load(peers, keys):
    """Distinct incompressible values keep the directed BGSAVE overlap measurable."""
    rng = random.Random(7)
    for start in range(0, keys, 128):
        count = min(128, keys - start)
        payload = b''.join(encode('SET', 'psfix:save-load:%d' % index, rng.randbytes(4096))
                           for index in range(start, start + count))
        for peer in peers:
            peer.raw(payload)
        for peer in peers:
            for _ in range(count):
                assert peer.read() == b'OK', 'save-load seed write failed'
    print('PSFIX save-load seeded %d keys / %d value bytes per peer' % (keys, keys * 4096), flush=True)


def run_differ(command, log_path, load_peers, save_bytes=0):
    budget_bytes = save_bytes
    if save_bytes and load_peers:
        # differ sizes each peer's SAVE from used_memory. Include the larger
        # peer's allocator/key overhead in the enclosing process budget too.
        budget_bytes = max(save_bytes, *(int(info(peer, 'memory')['used_memory'])
                                         for peer in load_peers))
    if load_peers:
        # Start one independent save on EACH peer, then run the differential leg while
        # those jobs are active. Further injections inside rdb_saves' exact +1 interval
        # would invalidate the count premise and race even a correct pre-save barrier.
        for peer in load_peers:
            assert info(peer, 'persistence')['rdb_bgsave_in_progress'] == '0'
        for peer in load_peers:
            assert peer.must('BGSAVE') == b'Background saving started'
        time.sleep(.101)
        for label, peer in zip(('target', 'oracle'), load_peers):
            assert info(peer, 'persistence')['rdb_bgsave_in_progress'] == '1', (
                'PSFIX save-load never armed for >100 ms on %s; increase --bgsave-load-keys' % label)
    # Four synchronous saves per differential leg. The process watchdog must
    # contain their socket budgets plus the unchanged both-peer idle barriers.
    timeout = 4 * save_timeout_seconds(budget_bytes) + 12 * 10 + 30 if save_bytes else 90
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    output = result.stdout + result.stderr
    log_path.write_text(output)
    print(output, end='', flush=True)
    if load_peers and result.returncode == 0:
        assert any('PSFIX idle barrier before target SAVE:' in line and
                   'busy_peers=target,oracle' in line for line in output.splitlines()), (
            'PSFIX save-load did not overlap the real before-save barrier on BOTH peers; '
            'increase --bgsave-load-keys; see ' + str(log_path))
    return result.returncode, output


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
    parser.add_argument('--atomic', type=int, choices=(0, 1), default=0)
    parser.add_argument('--seeds', type=int, nargs='+', default=[7])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--bgsave-load-keys', type=int, default=0,
                        help='0 disables; directed overlap proof uses 4096-byte values per key')
    parser.add_argument('--expect-pre-failure', action='store_true')
    args = parser.parse_args()
    if args.repeats < 1 or args.bgsave_load_keys < 0:
        parser.error('--repeats must be positive; --bgsave-load-keys must be nonnegative')
    if args.expect_pre_failure and args.bgsave_load_keys:
        parser.error('--expect-pre-failure cannot use the save-load proof')
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=False)
    target_dir, oracle_dir = args.root / 'target', args.root / 'oracle'
    target_dir.mkdir()
    oracle_dir.mkdir()
    target = [str(args.binary.resolve()), '--bind', '127.0.0.1', '--port', str(args.port),
              '--shards', '16', '--thread-mode', args.mode,
              '--databases', str(args.databases), '--atomic', str(args.atomic),
              '--dir', str(target_dir), '--save', '',
              '--appendonly', 'yes', '--appendfsync', 'no', '--auto-aof-rewrite-percentage', '0']
    if args.mode == '2s':
        target += ['--ratio', '6:2']
    oracle = [str(args.oracle.resolve()), '--bind', '127.0.0.1', '--port', str(args.port + 1),
              '--dir', str(oracle_dir), '--save', '', '--appendonly', 'yes', '--appendfsync', 'no',
              '--auto-aof-rewrite-percentage', '0', '--protected-mode', 'no']
    with boot(target, args.cores, args.port, args.root / 'target.log'), \
            boot(oracle, args.load_cores, args.port + 1, args.root / 'oracle.log'):
        if args.expect_pre_failure:
            client = Conn('127.0.0.1', args.port)
            try:
                fields = info(client, 'persistence')
                assert 'loading' not in fields and 'rdb_saves' not in fields
                assert 'aof_rewrite_completions' in fields and 'aof_rewrite_consecutive_failures' in fields
                print('PSFIX PRE INFO:', ' '.join(fields), flush=True)
            finally:
                client.close()
        load_peers = []
        try:
            if args.bgsave_load_keys:
                for port in (args.port, args.port + 1):
                    load_peers.append(Conn('127.0.0.1', port))
                seed_save_load(load_peers, args.bgsave_load_keys)
            for repeat in range(1, args.repeats + 1):
                for seed in args.seeds:
                    command = ['taskset', '-c', args.load_cores, sys.executable, 'tests/differ.py',
                               '127.0.0.1', str(args.port), '127.0.0.1', str(args.port + 1), 'psfix', str(seed)]
                    for protocol in ([], ['-3']):
                        name = 'differ-resp3' if protocol else 'differ-resp2'
                        if args.repeats != 1 or args.seeds != [7]:
                            name += '-r%d-s%d' % (repeat, seed)
                        status, output = run_differ(command + protocol, args.root / (name + '.log'),
                                                   load_peers, args.bgsave_load_keys * 4096)
                        if args.expect_pre_failure:
                            assert status != 0 and 'immutable' in output, output
                            print('PSFIX PRE CONTROL: differential rejected immutable aof-load-truncated')
                            return
                        assert status == 0, status
        finally:
            for peer in load_peers:
                peer.close()

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
            with save_reply_timeout(conn.sock, args.bgsave_load_keys * 4096):
                conn.must('SAVE')
            assert int(info(conn, 'persistence')['rdb_saves']) == before + 1
            print('PSFIX failed SAVE leaves count unchanged; successful retry increments once')
            before = int(info(conn, 'persistence')['rdb_saves'])
            rewrites = int(info(conn, 'persistence')['aof_rewrites'])
            conn.must('BGREWRITEAOF')
            rewrite_timeout = save_timeout_seconds(args.bgsave_load_keys * 4096) if args.bgsave_load_keys else 15
            deadline = time.monotonic() + rewrite_timeout
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
