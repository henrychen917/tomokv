#!/usr/bin/env python3
"""Directed F3 reproduction. Owns only its subprocess and its artifact directory."""

import argparse
import hashlib
import json
from pathlib import Path
import select
import time

import aoffix2 as h
import _lib


def stats(client):
    return {k: int(v) for line in client.cmd('INFO', 'stats').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)] if v.isdigit()}


def wait_for(predicate, reason, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.005)
    raise AssertionError(reason)


def keys_on_two_owners(client):
    owners = _lib.topology(client).shard_owner
    keys = {}
    for i in range(4096):
        key = f'aoforder:{i}'
        sid = client.cmd('DEBUG', 'SHARD', key)
        keys.setdefault(owners[sid], (key, sid))
        if len(keys) == 2:
            picked = list(keys.items())
            h.emit('geometry', keys=picked)
            return [v[0] for _, v in picked]
    raise AssertionError('two shard owners were not found')


def single():
    options = h.aof(h.ARGS.policy) + ['--atomic', '1', '--databases', str(h.ARGS.databases)]
    with h.Server(options) as server:
        admin, group, writer = (server.client(timeout=10) for _ in range(3))
        keys = keys_on_two_owners(admin)
        for key in keys:
            assert admin.cmd('SET', key, '0') == b'OK'
        before = stats(admin)
        assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '1') == b'OK'
        try:
            group.send('MSET', keys[0], '1', keys[1], '1')
            armed = wait_for(lambda: (s if (s := stats(admin))['atomic_pending_entries'] >= 2
                                     else None), 'group did not install on both shards')
            assert not select.select([group.s], [], [], 0)[0], 'held group replied'
            writer.send('SET', keys[0], '9')
            wait_for(lambda: admin.cmd('GET', keys[0]) == b'9',
                     'plain SET did not execute beneath the undecided group')
            h.emit('armed', before=before, after=armed,
                   held_values=admin.cmd('MGET', *keys),
                   plain_reply_ready=bool(select.select([writer.s], [], [], 0)[0]))
        finally:
            assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '0') == b'OK'
        assert group.read() == b'OK'
        assert writer.read() == b'OK'
        live = admin.cmd('MGET', *keys)
        assert live == [b'1', b'1'], live
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = admin.cmd('MGET', *keys)
        h.emit('loadaof', live=live, reloaded=reloaded, equal=live == reloaded)
    with h.Server(options) as server:
        restarted = server.client().cmd('MGET', *keys)
        h.emit('restart', live=live, restarted=restarted, equal=live == restarted)
    assert reloaded == live and restarted == live, 'F3: AOF replay differs from live state'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--policy', choices=('no', 'everysec', 'always'), default='everysec')
    parser.add_argument('--engine', choices=('uring', 'epoll'), default='uring')
    parser.add_argument('--cores', default='96-103')
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--port', type=int, default=25700)
    parser.add_argument('--databases', type=int, choices=(1, 16), default=16)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.artifacts = args.artifacts.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    args.oracle = False
    h.ARGS = args
    h.emit('arm', binary=str(args.binary),
           sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
           mode=args.mode, policy=args.policy, databases=args.databases)
    single()


if __name__ == '__main__':
    main()
