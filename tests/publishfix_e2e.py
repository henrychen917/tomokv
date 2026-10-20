#!/usr/bin/env python3
"""Directed lost-publication control; PRE fails after preserving all observations."""
import argparse
import hashlib
import os
from pathlib import Path
import time

import aoffix2 as h
from aoforder import stats, wait_for, keys_on_two_owners
import _lib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--port', type=int, default=25810)
    a = p.parse_args()
    assert 25800 <= a.port <= 25899
    assert set(os.sched_getaffinity(0)) <= set(range(104, 112))
    a.binary, a.artifacts = a.binary.resolve(), a.artifacts.resolve()
    a.artifacts.mkdir(parents=True, exist_ok=False)
    a.mode, a.engine, a.ratio, a.cores, a.oracle = '2s', 'uring', '4:4', '96-103', False
    h.ARGS = a
    park = a.artifacts / 'park'
    os.environ['TOMO_PUBLISH_PARK'] = str(park)
    h.emit('arm', binary=str(a.binary), sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest())
    options = h.aof('everysec') + ['--atomic', '1']
    with h.Server(options) as server:
        admin, first, second = (server.client(timeout=10) for _ in range(3))
        owners = _lib.topology(admin).shard_owner
        ka = keys_on_two_owners(admin, prefix='publishfix-a:')
        excluded = {owners[admin.cmd('DEBUG', 'SHARD', k)] for k in ka}
        kb = keys_on_two_owners(admin, excluded, prefix='publishfix-b:')
        kc = keys_on_two_owners(admin, prefix='publishfix-c:')
        assert len(excluded | {owners[admin.cmd('DEBUG', 'SHARD', k)] for k in kb}) == 4
        before = stats(admin)
        park.touch()
        try:
            first.send('MSET', ka[0], 'A', ka[1], 'A')
            wait_for(lambda: Path(str(park) + '.entered').exists(), 'window not entered')
            assert second.cmd('MSET', kb[0], 'B', kb[1], 'B') == b'OK'
            held = stats(admin)
            assert held['atomic_commit_windows'] == before['atomic_commit_windows'] + 1
        finally:
            park.unlink(missing_ok=True)
        assert first.read() == b'OK'
        read_before = stats(admin)
        live = admin.cmd('MGET', *kb)
        read_after = stats(admin)
        time.sleep(1)
        delayed = admin.cmd('MGET', *kb)
        assert admin.cmd('MSET', kc[0], 'C', kc[1], 'C') == b'OK'
        live2 = admin.cmd('MGET', *kb)
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = admin.cmd('MGET', *kb)
        h.emit('visibility', live=live, delayed=delayed, live2=live2, reloaded=reloaded,
               windows=held['atomic_commit_windows'] - before['atomic_commit_windows'],
               holds=read_after['atomic_commit_holds'] - read_before['atomic_commit_holds'])
    with h.Server(options) as server:
        restarted = server.client().cmd('MGET', *kb)
        h.emit('restart', restarted=restarted)
    assert live2 == reloaded == restarted == [b'B', b'B'], 'kick/replay must preserve B'
    assert live == delayed == live2, 'acknowledged B was orphaned until an unrelated kick'


if __name__ == '__main__':
    main()
