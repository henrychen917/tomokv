#!/usr/bin/env python3
"""OBJECT IDLETIME must resolve, and must not expire, a foreign atomic candidate."""
import argparse
import hashlib
from pathlib import Path
import select
import time

import aoffix2 as h
from hexpread import stats, keys, wait_for, deadline_passed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    args = p.parse_args()
    args.binary, args.artifacts = args.binary.resolve(), args.artifacts.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    args.oracle, args.engine = False, 'uring'
    h.ARGS = args
    h.emit('arm', binary=str(args.binary), mode=args.mode,
           sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest())
    with h.Server(['--atomic', '1', '--databases', '16']) as server:
        c, group = server.client(timeout=10), server.client(timeout=10)
        a, b, _ = keys(c)
        assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == b'OK'
        for attempt in range(3):
            assert c.cmd('FLUSHDB') == b'OK'
            assert c.cmd('SET', a, 'old') == b'OK'
            assert c.cmd('SET', b, 'candidate') == b'OK'
            deadline = time.time_ns() // 1_000_000 + 700
            assert c.cmd('PEXPIREAT', b, deadline) == 1
            before = stats(c)
            assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1) == b'OK'
            try:
                group.send('RENAME', b, a)
                installed = wait_for(lambda: stats(c)['atomic_pending_entries'] >= 2,
                                     'RENAME did not install on both owners')
                assert not select.select([group.s], [], [], 0)[0]
                if time.time_ns() // 1_000_000 >= deadline:
                    h.emit('missed_arm', attempt=attempt)
                    armed = False
                else:
                    armed = True
                    assert c.cmd('GET', a) == b'old'
                    assert c.cmd('PTTL', a) == -1
                    deadline_passed(deadline)
                    ordinary = c.cmd('GET', a)
                    idle = c.cmd('OBJECT', 'IDLETIME', a)
                    after = stats(c)
                    h.emit('parked_object', installed=installed, ordinary=ordinary, idle=idle,
                           expired_before=before['expired_keys'], expired_after=after['expired_keys'])
            finally:
                assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == b'OK'
            assert group.read() == b'OK'
            if armed:
                break
        else:
            raise AssertionError('three fresh RENAME arms missed the live candidate window')
        assert ordinary == b'old'
        assert idle == 0, 'OBJECT looked at the expired candidate instead of the persistent predecessor'
        assert after['expired_keys'] == before['expired_keys'], 'OBJECT physically erased a candidate'
    h.emit('pass')


if __name__ == '__main__':
    main()
