#!/usr/bin/env python3
"""WB4.1: a real remote LPOS holds one FIFO entry; idle IO CPU must stay bounded."""
import select
import os
from pathlib import Path
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
            cores = sorted(os.sched_getaffinity(server.process.pid))
            def owner_tid(index):
                found = [tid for tid in before if os.sched_getaffinity(tid) == {cores[index]}
                         and not Path(f'/proc/{tid}/comm').read_text().startswith('iou-')]
                assert len(found) == 1, ('worker affinity is ambiguous', index, found)
                return found[0]
            io_tid, list_tid = owner_tid(io_owner), owner_tid(owner)
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
            io_cpu = (after[io_tid] - before[io_tid]) / 1e9
            list_cpu = (after[list_tid] - before[list_tid]) / 1e9
            assert list_cpu > .10, ('LPOS window never opened', list_cpu)
            if policy:
                assert held > 0, 'no deferred prefix was witnessed'
            emit(arm=name, io_owner=io_owner, list_owner=owner, holds=held, wall_seconds=wall,
                 top_cpu_seconds=cpu[:3], io_tid=io_tid, list_tid=list_tid,
                 io_cpu_seconds=io_cpu, list_cpu_seconds=list_cpu,
                 second_busy_cpu_seconds=cpu[1][0])
            # Directly measure the proven connection owner. Retain the independent rank check:
            # LPOS's owner must be the only sustained CPU consumer in this isolated workload.
            if io_cpu > wall * .15 or cpu[1][0] > wall * .15:
                failures.append((name, 'deferred IO busy-spun', io_cpu, cpu[1][0], wall))
            assert c.cmd('SET', 'iofix:after', name) == b'OK'
            assert c.cmd('GET', 'iofix:after') == name.encode()
    assert not failures, failures
    emit(result='PASS WB4.1', mode=args.mode, engine=args.net_io)


if __name__ == '__main__':
    args = arguments(__doc__).parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)
