#!/usr/bin/env python3
"""Mainline-only real boots: parked SWAPDB, load, BLPOP, and bounded shutdown.

No importing or --self-test path launches a server. Normal invocation owns each
child PID and always reaps it, including deliberately broken no-wake children.
The long-park positive/negative twins change only the idle timeout in both arms;
the negative additionally removes the database eventfd writes. This makes a
missing wake observable independently of the existing 50 ms fallback tick.
"""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import subprocess
import threading
import time

from _lib import Conn, info, lbsignals

ROOT = Path(__file__).resolve().parents[1]
WORKERS = 8
TICK = int(re.search(r'kWaitTimeoutMs = (\d+)',
                    (ROOT / 'src/net/uring.h').read_text()).group(1)) / 1000
GRACE = 2 * TICK * (WORKERS + 1)
SHUTDOWN = 3 * GRACE


class Unarmed(AssertionError):
    pass


def require(value, message):
    if not value:
        raise AssertionError(message)


def cpus(value):
    result = set()
    for word in value.split(','):
        if '-' in word:
            a, b = map(int, word.split('-'))
            result.update(range(a, b + 1))
        else:
            result.add(int(word))
    require(len(result) == WORKERS, 'live proof requires exactly eight allowed cores')
    return value


def park_snapshot(pid):
    """Kernel wait witness; never replace this by a guessed sleep interval."""
    rows = {}
    for task in (Path('/proc') / str(pid) / 'task').iterdir():
        if int(task.name) == pid:
            continue  # the supervisor's condition-variable wait is not a worker
        try:
            wait = (task / 'wchan').read_text().strip()
            if 'io_cqring' in wait or 'io_uring' in wait or 'ep_poll' in wait:
                rows[task.name] = wait
        except FileNotFoundError:
            pass
    return rows


def wait_parked(proc):
    # >=4 parked workers excludes the admin's own IO and BOTH split executors:
    # even if the admin wakes, an unrelated participant must need a doorbell.
    deadline = time.monotonic() + SHUTDOWN
    prior = {}
    while time.monotonic() < deadline:
        require(proc.poll() is None, 'server exited before parked window')
        current = park_snapshot(proc.pid)
        stable = {tid: wait for tid, wait in current.items() if tid in prior}
        if len(stable) >= WORKERS // 2:
            return stable
        prior = current
        time.sleep(TICK / 4)
    raise Unarmed('fewer than four physical workers witnessed in kernel ring waits')


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def boot(binary, args, directory, log):
    command = ['taskset', '-c', args.cores, str(binary), '--bind', '127.0.0.1',
               '--port', str(args.port), '--thread-mode', args.mode,
               '--shards', '16', '--ratio', '6:2', '--databases', '16',
               '--read-local', str(args.read_local), '--atomic', str(args.atomic),
               '--enable-debug-command', 'yes', '--save', '', '--protected-mode', 'no']
    env = dict(os.environ)
    env.pop('TOMOKV_L3_DOMAINS', None)  # discover the explicitly pinned eight cores
    (directory / 'command.json').write_text(json.dumps(command) + '\n')
    proc = subprocess.Popen(command, cwd=directory, env=env, stdout=log,
                            stderr=subprocess.STDOUT, preexec_fn=no_core_dump)
    return proc


def connect_ready(proc, port):
    deadline = time.monotonic() + WORKERS * SHUTDOWN
    while time.monotonic() < deadline:
        require(proc.poll() is None, 'server failed during boot; see server.log')
        conn = None
        try:
            conn = Conn('127.0.0.1', port, timeout=GRACE)
            require(conn.cmd('PING') == b'PONG', 'owned server PING failed')
            return conn
        except (ConnectionError, OSError, EOFError):
            if conn:
                conn.close()
            time.sleep(TICK)
    raise AssertionError('boot deadline expired')


def stop(proc):
    require(proc.poll() is None, 'server crashed before shutdown')
    start = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        result = proc.wait(timeout=SHUTDOWN)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError('clean shutdown deadline expired') from exc
    require(result == 0, f'unclean shutdown exit={result}')
    return time.monotonic() - start


def cleanup(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=SHUTDOWN)  # owned PID only; never pkill/killall/port killing


def run_case(binary, args, case, arm, attempt):
    directory = args.output / f'{case}-{arm}-{attempt}'
    directory.mkdir(parents=True)
    conns, load_threads, failures = [], [], []
    halt = threading.Event()
    loaded = threading.Event()
    counts = [0]
    proc = None
    result = dict(case=case, arm=arm, mode=args.mode, read_local=args.read_local,
                  atomic=args.atomic, grace_seconds=GRACE, shutdown_seconds=SHUTDOWN)
    try:
        with (directory / 'server.log').open('wb') as log:
            proc = boot(binary, args, directory, log)
        admin = connect_ready(proc, args.port)
        conns.append(admin)
        require(info(admin, 'server')['thread_mode'] == args.mode, 'wrong boot mode')
        topology = lbsignals(admin)
        require(len(topology.threads) == WORKERS and len(topology.shards) == 16,
                'boot did not preserve gate geometry')
        require(admin.cmd('CONFIG', 'GET', 'databases') == [b'databases', b'16'],
                'boot did not enable sixteen databases')
        if case == 'load':
            load = Conn('127.0.0.1', args.port, timeout=GRACE)
            conns.append(load)
            require(load.cmd('SELECT', 2) == b'OK', 'load namespace')

            def write_load():
                try:
                    while not halt.is_set():
                        value = str(counts[0]).encode()
                        require(load.cmd('SET', 'mdbqsbr:load', value) == b'OK', 'load SET')
                        require(load.cmd('GET', 'mdbqsbr:load') == value, 'load RYOW')
                        counts[0] += 1
                        if counts[0] >= WORKERS:
                            loaded.set()
                except BaseException as error:
                    if not halt.is_set():
                        failures.append(repr(error))
                    loaded.set()

            writer = threading.Thread(target=write_load, daemon=True)
            load_threads.append(writer)
            writer.start()
            require(loaded.wait(SHUTDOWN) and counts[0] >= WORKERS and not failures,
                    f'load window never opened: {failures}')
        elif case == 'blpop':
            waiter = Conn('127.0.0.1', args.port, timeout=GRACE)
            conns.append(waiter)
            waiter.send('BLPOP', 'mdbqsbr:block', 0)
            deadline = time.monotonic() + GRACE
            while int(info(admin, 'clients')['blocked_clients']) != 1:
                require(time.monotonic() < deadline, 'BLPOP never parked')
                time.sleep(TICK / 4)

        result['parked'] = wait_parked(proc)
        baseline = counts[0]
        replies = []
        # Three real swaps create two retirements even on a brand-new boot.
        # Failure classification applies ONLY to these replies, never boot or
        # arming. Crashes, assertion failures and unrelated timeouts stay red.
        for index in range(3):
            if index:
                result[f'parked_before_{index}'] = wait_parked(proc)
            begin = time.monotonic()
            try:
                reply = admin.cmd('SWAPDB', 0, 1)
            except socket.timeout:
                require(arm == 'no-wake' and proc.poll() is None,
                        'SWAPDB timed out without the intended live negative')
                result['expected_timeout'] = True
                result['timeout_at_swap'] = index
                break
            require(reply == b'OK' and time.monotonic() - begin <= GRACE,
                    'SWAPDB missed its reply deadline')
            replies.append(time.monotonic() - begin)
        else:
            require(arm != 'no-wake', 'no-wake control answered: missing wake was not detected')
            if case == 'load':
                deadline = time.monotonic() + GRACE
                while counts[0] <= baseline and not failures:
                    require(time.monotonic() < deadline, 'load made no progress across SWAPDB')
                    time.sleep(TICK / 4)
                require(not failures, f'load failed: {failures}')
            if case == 'blpop':
                require(admin.cmd('RPUSH', 'mdbqsbr:block', 'after-swap') == 1, 'BLPOP wake source')
                require(waiter.read() == [b'mdbqsbr:block', b'after-swap'],
                        'blocked logical namespace did not follow SWAPDB')
        result['reply_seconds'] = replies
        result['load_batches'] = counts[0]
        halt.set()
        # Signal stop while the connections are still open, including a BLPOP
        # and queued commands in the broken arm. No grace ack from a joined
        # worker may be needed to finish this shutdown.
        result['shutdown_elapsed_seconds'] = stop(proc)
        output = (directory / 'server.log').read_text(errors='replace')
        require('shutdown_report {' in output, 'missing clean final shutdown report')
        require('fatal: database' not in output, 'database deadline aborted this supposedly clean run')
        print(f'PASS mdbqsbr live {case} {arm}: {json.dumps(result, sort_keys=True)}', flush=True)
        return result
    finally:
        halt.set()
        if proc is not None:
            # Even a failed positive/arming window cannot strand a gate server.
            # Close only after death so no makefile reader races its own thread.
            cleanup(proc)
        for writer in load_threads:
            writer.join(SHUTDOWN)
            require(not writer.is_alive(), 'load thread did not finish within shutdown bound')
        for conn in conns:
            conn.close()
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)  # unwind run_case's owned-child cleanup

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--parked-binary', type=Path, required=True)
    parser.add_argument('--no-wake-binary', type=Path, required=True)
    parser.add_argument('--mode', choices=['1s', '2s'], required=True)
    parser.add_argument('--read-local', type=int, choices=[0, 1], required=True)
    parser.add_argument('--atomic', type=int, choices=[0, 1], required=True)
    parser.add_argument('--cores', type=cpus, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    arms = [('production', args.binary.resolve()), ('parked', args.parked_binary.resolve()),
            ('no-wake', args.no_wake_binary.resolve())]
    for _, binary in arms:
        require(binary.is_file(), f'missing real-boot arm: {binary}')
    for case in ['idle', 'load', 'blpop']:
        for arm, binary in arms:
            for attempt in range(WORKERS):
                try:
                    run_case(binary, args, case, arm, attempt)
                    break
                except Unarmed:
                    if attempt + 1 == WORKERS:
                        raise
                    print(f'REARM {case} {arm}: fresh boot {attempt + 1}', flush=True)


if __name__ == '__main__':
    main()
