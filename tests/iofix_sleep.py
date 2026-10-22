#!/usr/bin/env python3
"""IO4.10: every worker pauses, exact oracle replies, pipelines and EXEC survive."""
import os
from pathlib import Path
import select
import time
from _iofix import arguments, Listener, emit, encode, info, cpu_times


def workers(pid):
    return [int(path.name) for path in Path(f'/proc/{pid}/task').iterdir()
            if len(os.sched_getaffinity(int(path.name))) == 1]


def paused(pid, tids):
    return all('futex' in Path(f'/proc/{pid}/task/{tid}/wchan').read_text() for tid in tids)


def replies(server):
    c = server.connect()
    out = []
    for value in ('0', '-1', 'garbage', 'nan', 'inf', '0.0000001', '.002tail', ' 0.002', '1.01'):
        start = time.monotonic()
        reply = c.cmd('DEBUG', 'SLEEP', value)
        elapsed = time.monotonic() - start
        emit(sleep=value, reply=reply, seconds=elapsed)
        assert reply == b'OK'
        if value == '1.01':
            assert elapsed >= 1, 'old timeout-derived ceiling still active'
        out.append(reply)
    assert c.cmd('MULTI') == b'OK'
    for command in (('SET', 'iofix:order', 'before'), ('DEBUG', 'SLEEP', '.03'),
                    ('SET', 'iofix:order', 'after'), ('GET', 'iofix:order')):
        assert c.cmd(*command) == b'QUEUED'
    start = time.monotonic()
    out.append(c.cmd('EXEC'))
    assert time.monotonic() - start >= .03
    # A disconnect does not cancel Redis's sleep, and DEBUG SLEEP isn't a blocked-client command.
    blocked = info(c, 'clients')[b'blocked_clients']
    sleeper = server.connect()
    sleeper.send('DEBUG', 'SLEEP', '.35')
    time.sleep(.08)
    sleeper.close()
    start = time.monotonic()
    out.append(c.cmd('PING'))
    assert time.monotonic() - start >= .20, 'disconnect cancelled the global sleep'
    assert info(c, 'clients')[b'blocked_clients'] == blocked
    return out


def witness(server, mode, transaction=False):
    c = server.connect()
    owners = {}
    expected_ios = 8 if mode == '1s' else 6
    for _ in range(512):
        candidate = server.connect()
        owner = candidate.cmd('DEBUG', 'IO-THREAD')
        if owner in owners:
            candidate.close()
        else:
            owners[owner] = candidate
        if len(owners) == expected_ios:
            break
    assert len(owners) == expected_ios, ('missing IO owners', owners)
    tids = workers(server.process.pid)
    assert len(tids) == 8, ('worker geometry', tids)
    if transaction:
        assert c.cmd('MULTI') == b'OK'
        assert c.cmd('DEBUG', 'SLEEP', '.5') == b'QUEUED'
    started = time.monotonic()
    c.send(*(('EXEC',) if transaction else ('DEBUG', 'SLEEP', '.5')))
    deadline = started + 2
    while time.monotonic() < deadline and not paused(server.process.pid, tids):
        if select.select([c.sock], [], [], 0)[0]:
            raise AssertionError('sleep replied without an all-worker pause')
        time.sleep(.001)
    assert paused(server.process.pid, tids), 'all-worker pause never opened'
    before = cpu_times(server.process.pid)
    expected = {}
    for owner, conn in owners.items():
        commands = [('PING',)]
        want = [b'PONG']
        for n in range(24):
            key, value = f'iofix:{owner}:{n}', f'value:{n}'
            commands += [('SET', key, value), ('GET', key)]
            want += [b'OK', value.encode()]
        conn.raw(b''.join(encode(*command) for command in commands))
        expected[owner] = want
    assert not select.select([conn.sock for conn in owners.values()], [], [], .10)[0], \
        'a worker processed commands during the witnessed global pause'
    after = cpu_times(server.process.pid)
    assert sum(after[tid] - before[tid] for tid in tids) < 30_000_000, 'paused workers busy-spun'
    assert c.read() == ([b'OK'] if transaction else b'OK')
    assert time.monotonic() - started >= .5
    for owner, conn in owners.items():
        assert [conn.read() for _ in expected[owner]] == expected[owner], 'lost/reordered pipeline'
        conn.close()
    emit(witness='all workers paused', transaction=transaction, tids=tids, owners=list(owners))


def run(args):
    with Listener(args, 'oracle', oracle=True) as oracle:
        expected = replies(oracle)
        emit(oracle=expected)
    variants = [[], ['--read-local', '1']]
    if args.mode == '1s':
        variants.append(['--read-local', '1', '--reorder', '1'])
    for index, extra in enumerate(variants):
        with Listener(args, f'target-{index}', extra=extra) as server:
            assert replies(server) == expected
            witness(server, args.mode)
            witness(server, args.mode, transaction=True)
    emit(result='PASS IO4.10', mode=args.mode, engine=args.net_io)


if __name__ == '__main__':
    args = arguments(__doc__).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)
