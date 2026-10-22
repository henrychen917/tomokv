#!/usr/bin/env python3
"""WB4.1: a real remote LPOS holds one FIFO entry; idle IO CPU must stay bounded."""
import select
import time
from _iofix import arguments, Listener, emit, encode, cpu_times


def populate(c):
    for base in range(0, 3_000_000, 10000):
        assert c.cmd('RPUSH', 'iofix:list', *(['payload'] * 10000)) == base + 10000


def run(args):
    payload = encode('PING') + encode('LPOS', 'iofix:list', 'absent') + encode('PING') * 3
    with Listener(args, 'oracle', oracle=True) as oracle:
        c = oracle.connect()
        populate(c)
        c.raw(payload)
        expected = [c.read() for _ in range(5)]
        assert expected == [b'PONG', None, b'PONG', b'PONG', b'PONG']
        emit(oracle_replies=expected)
    failures = []
    for policy, small, visits in ((0, 16, 3), (1, 16, 3), (1, 0, 3), (1, 16, 0)):
        name = f'policy-{policy}-S{small}-D{visits}'
        with Listener(args, name, extra=['--wb-policy', str(policy), '--wb-small-pipe', str(small),
                                        '--wb-complete-visits', str(visits)]) as server:
            c = server.connect()
            populate(c)
            owner = c.cmd('DEBUG', 'SHARDS', 'iofix:list')[0][1]
            for attempt in range(128):
                if c.cmd('DEBUG', 'IO-THREAD') != owner:
                    break
                c.close()
                c = server.connect()
            else:
                raise AssertionError('could not place the connection away from its list owner')
            io_owner = c.cmd('DEBUG', 'IO-THREAD')
            before = cpu_times(server.process.pid)
            started = time.monotonic()
            held = 0
            for _ in range(16):
                c.raw(payload)
                held += not select.select([c.sock], [], [], .002)[0]
                assert [c.read() for _ in range(5)] == expected
            wall = time.monotonic() - started
            after = cpu_times(server.process.pid)
            cpu = sorted(((after[tid] - ns) / 1e9, tid) for tid, ns in before.items()
                         if tid in after)[::-1]
            # One owner must really have run the slow command; a missing deferral window is red.
            assert cpu[0][0] > .10, ('LPOS window never opened', cpu)
            if policy:
                assert held > 0, 'no deferred prefix was witnessed'
            emit(arm=name, io_owner=io_owner, list_owner=owner, holds=held, wall_seconds=wall,
                 top_cpu_seconds=cpu[:3], io_cpu_upper_bound=cpu[1][0])
            # The only sustained CPU consumer may be LPOS's executor. All other threads together
            # should be nearly idle. This catches PRE's second fully occupied core independently
            # of thread names/placement and uses the kernel's CPU accounting, not loop counters.
            if cpu[1][0] > wall * .15:
                failures.append((name, 'deferred IO busy-spun', cpu[1][0], wall))
            assert c.cmd('SET', 'iofix:after', name) == b'OK'
            assert c.cmd('GET', 'iofix:after') == name.encode()
    assert not failures, failures
    emit(result='PASS WB4.1', mode=args.mode, engine=args.net_io)


if __name__ == '__main__':
    args = arguments(__doc__).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)
