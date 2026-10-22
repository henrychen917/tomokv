#!/usr/bin/env python3
"""IO4.17: signal starts the shutdown save immediately; failure/retry remains live."""
import signal
import time
from _iofix import arguments, Listener, emit, info, cpu_times


def fresh_beat(c):
    before = int(info(c, 'persistence')[b'rdb_save_cron_checks'])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        after = int(info(c, 'persistence')[b'rdb_save_cron_checks'])
        if after > before:
            return
        time.sleep(.003)
    raise AssertionError('save-cron beat never opened')


def run(args):
    failures = []
    for oracle in (True, False):
        kind = 'oracle' if oracle else 'target'
        for sig in (signal.SIGTERM, signal.SIGINT):
            name = f'{kind}-{sig.name}'
            with Listener(args, name, oracle=oracle,
                          extra=['--save', '3600 1', '--dbfilename', 'saved.rdb']) as server:
                c = server.connect()
                expected = c.cmd('SET', 'iofix:shutdown', sig.name)
                assert expected == b'OK'
                if not oracle:
                    fresh_beat(c)  # force the PRE one-second blind interval, without a lucky phase
                started = time.monotonic()
                server.process.send_signal(sig)
                server.process.wait(timeout=12)
                elapsed = time.monotonic() - started
                emit(kind=kind, signal=sig.name, seconds=elapsed, exit=server.process.returncode)
                assert server.process.returncode == 0
                assert (server.directory / 'saved.rdb').is_file()
                directory = server.directory
                if not oracle and elapsed >= .40:
                    failures.append((sig.name, 'waited for save cron', elapsed))
            with Listener(args, name + '-reload', oracle=oracle, directory=directory,
                          extra=['--dbfilename', 'saved.rdb']) as server:
                assert server.connect().cmd('GET', 'iofix:shutdown') == sig.name.encode()
        # A failed shutdown save must keep serving; a second signal must still wake the loop.
        with Listener(args, kind + '-failed-save', oracle=oracle,
                      extra=['--save', '3600 1', '--dbfilename', 'saved.rdb']) as server:
            c = server.connect()
            assert c.cmd('SET', 'iofix:retry', 'retained') == b'OK'
            obstruction = server.directory / 'saved.rdb'
            obstruction.mkdir()
            server.process.send_signal(signal.SIGTERM)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                content = open(server.log.name, 'rb').read()
                if b'Errors trying to SHUTDOWN' in content:
                    break
                time.sleep(.01)
            else:
                raise AssertionError('failed save never reached the shutdown error')
            assert server.process.poll() is None
            assert c.cmd('GET', 'iofix:retry') == b'retained'
            before = cpu_times(server.process.pid)
            time.sleep(.2)
            after = cpu_times(server.process.pid)
            cpu = sum(after[tid] - ns for tid, ns in before.items() if tid in after) / 1e9
            emit(kind=kind, failed_save_idle_cpu_seconds=cpu)
            assert cpu < .05, 'request doorbell stayed readable after failed save'
            obstruction.rmdir()
            if not oracle:
                fresh_beat(c)
            started = time.monotonic()
            server.process.send_signal(signal.SIGTERM)
            server.process.wait(timeout=12)
            elapsed = time.monotonic() - started
            assert server.process.returncode == 0
            assert obstruction.is_file()
            if not oracle and elapsed >= .40:
                failures.append(('retry SIGTERM', elapsed))
        # Explicit NOSAVE must override configured save clauses, including signal-stop defaults.
        with Listener(args, kind + '-nosave', oracle=oracle,
                      extra=['--save', '3600 1', '--dbfilename', 'saved.rdb']) as server:
            c = server.connect()
            assert c.cmd('SET', 'iofix:nosave', 'discard') == b'OK'
            c.send('SHUTDOWN', 'NOSAVE')
            server.process.wait(timeout=5)
            assert server.process.returncode == 0
            assert not (server.directory / 'saved.rdb').exists()
    assert not failures, failures
    emit(result='PASS IO4.17', mode=args.mode, engine=args.net_io)


if __name__ == '__main__':
    args = arguments(__doc__).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)
