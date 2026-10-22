#!/usr/bin/env python3
"""IO4.9: Redis hz grammar, clamps, live updates, dynamic cadence and file/rewrite."""
import time
import select
from pathlib import Path
from _iofix import arguments, Listener, emit, info


def wait_hz(c, value):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        actual = int(info(c, 'server')[b'hz'])
        if actual == value:
            return
        time.sleep(.01)
    raise AssertionError(('effective hz', actual, value))


def switches(pid):
    total = 0
    for task in Path(f'/proc/{pid}/task').iterdir():
        for line in (task / 'status').read_text().splitlines():
            if line.startswith('voluntary_ctxt_switches:'):
                total += int(line.split()[1])
    return total


def client_share(server):
    control = server.connect()
    assert control.cmd('CONFIG', 'SET', 'hz', '1', 'dynamic-hz', 'no') == b'OK'
    clients = [server.connect() for _ in range(256)]
    for client in clients:
        assert client.cmd('PING') == b'PONG'
    assert control.cmd('CONFIG', 'SET', 'timeout', '1') == b'OK'
    # Redis's strict whole-second idle test plus a 1 Hz beat can take three seconds.
    # A stale clients/10 share needs ten beats to visit this witnessed population.
    pending = {client.sock for client in clients}
    start = time.monotonic()
    while pending:
        remaining = 3.5 - (time.monotonic() - start)
        assert remaining > 0, ('client share did not follow hz', len(pending))
        ready, _, _ = select.select(list(pending), [], [], remaining)
        for sock in ready:
            assert sock.recv(1) == b'', 'idle client received unexpected data'
            pending.remove(sock)
    emit(client_share_clients=len(clients), client_share_seconds=time.monotonic() - start)


def run(args):
    failures = []
    def check(phase, action):
        try:
            action()
        except Exception as error:
            failures.append((phase, repr(error)))
            emit(phase=phase, failure=repr(error))

    commands = [('CONFIG', 'GET', 'hz'), ('CONFIG', 'GET', 'dynamic-hz')]
    for value in ('0', '1', '20', '500', '501', '2147483647', '-1', '2147483648',
                  '01', '+1', '-0', '1.5', '', 'nan', '9223372036854775808'):
        commands += [('CONFIG', 'SET', 'hz', value), ('CONFIG', 'GET', 'hz')]
    for value in ('no', 'yes', 'NO', 'YES', '1', '0', 'maybe', ''):
        commands += [('CONFIG', 'SET', 'dynamic-hz', value), ('CONFIG', 'GET', 'dynamic-hz')]
    commands += [('CONFIG', 'SET', 'hz', '10', 'HZ', '30'),
                 ('CONFIG', 'SET', 'dynamic-hz', 'yes', 'DYNAMIC-HZ', 'no'),
                 ('CONFIG', 'SET', 'HZ', 'junk'),
                 ('CONFIG', 'SET', 'DYNAMIC-HZ', 'junk'),
                 ('CONFIG', 'SET', 'hz', '20', 'dynamic-hz', 'invalid'),
                 ('CONFIG', 'GET', 'hz'), ('CONFIG', 'GET', 'dynamic-hz')]
    with Listener(args, 'oracle', oracle=True) as oracle, Listener(args, 'target') as target:
        r, t = oracle.connect(), target.connect()
        differences = []
        for command in commands:
            expected, actual = r.cmd(*command), t.cmd(*command)
            emit(command=command, oracle=expected, target=actual)
            if expected != actual:
                differences.append((command, expected, actual))
        if differences:
            failures.append(('oracle config replies', differences))
        for listener, c in ((oracle, r), (target, t)):
            def dynamic():
                assert c.cmd('CONFIG', 'SET', 'hz', '1', 'dynamic-hz', 'yes') == b'OK'
                clients = [listener.connect() for _ in range(205)]
                for client in clients:
                    assert client.cmd('PING') == b'PONG'
                wait_hz(c, 2)
                assert info(c, 'server')[b'configured_hz'] == b'1'
                assert c.cmd('CONFIG', 'SET', 'dynamic-hz', 'no') == b'OK'
                wait_hz(c, 1)
                for client in clients:
                    client.close()
            check('dynamic hz ' + ('oracle' if listener is oracle else 'target'), dynamic)
        # Witness the scheduler, not just CONFIG/INFO strings: a fixed 10 Hz client cron
        # cannot generate the high-rate idle parks on an otherwise idle server.
        def cadence():
            samples = {}
            for hz in (10, 100):
                assert t.cmd('CONFIG', 'SET', 'hz', hz) == b'OK'
                time.sleep(1.1)  # the previous 1 Hz timer is allowed to finish
                before = switches(target.process.pid)
                time.sleep(.5)
                samples[hz] = switches(target.process.pid) - before
            emit(cron_wait_switches=samples)
            assert samples[100] > 2 * samples[10], ('client cron stayed at 10 Hz', samples)
        check('cron cadence', cadence)
        check('oracle client share', lambda: client_share(oracle))
        check('target client share', lambda: client_share(target))
    for oracle in (True, False):
        name = 'file-oracle' if oracle else 'file-target'
        config = args.output / (name + '.conf')
        config.write_text('hz 0\ndynamic-hz no\n')
        def rewrite():
            with Listener(args, name, oracle=oracle, config=config) as server:
                c = server.connect()
                assert c.cmd('CONFIG', 'GET', 'hz') == [b'hz', b'1']
                assert c.cmd('CONFIG', 'GET', 'dynamic-hz') == [b'dynamic-hz', b'no']
                assert c.cmd('CONFIG', 'SET', 'hz', '2147483647', 'dynamic-hz', 'yes') == b'OK'
                assert c.cmd('CONFIG', 'REWRITE') == b'OK'
        def reload():
            with Listener(args, name + '-reload', oracle=oracle, config=config) as server:
                c = server.connect()
                assert c.cmd('CONFIG', 'GET', 'hz') == [b'hz', b'500']
                assert c.cmd('CONFIG', 'GET', 'dynamic-hz') == [b'dynamic-hz', b'yes']
        check(name + ' rewrite', rewrite)
        check(name + ' reload', reload)
    assert not failures, failures
    emit(result='PASS IO4.9', mode=args.mode, engine=args.net_io)


if __name__ == '__main__':
    args = arguments(__doc__).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)
