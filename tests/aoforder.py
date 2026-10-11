#!/usr/bin/env python3
"""Directed F3 reproduction. Owns only its subprocess and its artifact directory."""

import argparse
import hashlib
import json
import os
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


def keys_on_two_owners(client, excluded=()):
    owners = _lib.topology(client).shard_owner
    keys = {}
    for i in range(4096):
        key = f'aoforder:{i}'
        sid = client.cmd('DEBUG', 'SHARD', key)
        if owners[sid] in excluded:
            continue
        keys.setdefault(owners[sid], (key, sid))
        if len(keys) == 2:
            picked = list(keys.items())
            h.emit('geometry', keys=picked)
            return [v[0] for _, v in picked]
    raise AssertionError('two shard owners were not found')


def single():
    options = h.aof(h.ARGS.policy) + ['--atomic', '1', '--databases', str(h.ARGS.databases)]
    with h.Server(options) as server:
        rewrite = h.ARGS.case == 'rewrite'
        admin, group, writer = (h.off_writer(server) for _ in range(3)) if rewrite else (
            server.client(timeout=10) for _ in range(3))
        roles = _lib.topology(admin).roles
        writer_tid = max(tid for tid, role in roles.items() if role in ('io', 'fused'))
        keys = keys_on_two_owners(admin, (writer_tid,) if rewrite else ())
        for key in keys:
            assert admin.cmd('SET', key, '0') == b'OK'
        marker = server.data / 'appendonlydir/debug-aof-rewrite-stage'
        try:
            if rewrite:
                assert admin.cmd('DEBUG', 'AOF-REWRITE-PAUSE', 'before-manifest') == b'OK'
                admin.cmd('BGREWRITEAOF')
                wait_for(lambda: marker.exists() and marker.read_text() == 'before-manifest\n',
                         'rewrite never reached its post-cut, pre-manifest window')
                h.emit('rewrite_armed', stage=marker.read_text())
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
        finally:
            marker.unlink(missing_ok=True)
        assert group.read() == b'OK'
        assert writer.read() == b'OK'
        if rewrite:
            h.emit('rewrite_finished', info=h.wait_rewrite(admin))
        live = admin.cmd('MGET', *keys)
        assert live == [b'1', b'1'], live
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = admin.cmd('MGET', *keys)
        h.emit('loadaof', live=live, reloaded=reloaded, equal=live == reloaded)
    with h.Server(options) as server:
        restarted = server.client().cmd('MGET', *keys)
        h.emit('restart', live=live, restarted=restarted, equal=live == restarted)
    assert reloaded == live and restarted == live, 'F3: AOF replay differs from live state'


def crossing():
    release = h.ARGS.artifacts / 'cross-release'
    os.environ['TOMO_AOFORDER_CROSS_RELEASE'] = str(release)
    options = h.aof(h.ARGS.policy) + ['--atomic', '1', '--databases', str(h.ARGS.databases)]
    with h.Server(options) as server:
        admin, first, second = (server.client(timeout=10) for _ in range(3))
        keys = keys_on_two_owners(admin)
        assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '1') == b'OK'
        try:
            first.send('MSET', keys[0], 'aoforder-group1', keys[1], 'aoforder-group1')
            wait_for(lambda: stats(admin)['atomic_pending_entries'] == 1,
                     'scheduler did not park group 1 before its second install')
            second.send('MSET', keys[0], 'aoforder-group2', keys[1], 'aoforder-group2')
            wait_for(lambda: stats(admin)['atomic_pending_entries'] == 2,
                     'scheduler did not park group 2 on the opposite owner')
            assert not select.select([first.s, second.s], [], [], 0)[0]
            h.emit('crossing_armed', pending=2, inflight=stats(admin)['atomic_inflight'])
            release.touch()
            wait_for(lambda: stats(admin)['atomic_pending_entries'] == 4,
                     'both delayed fragments did not install before ticket allocation')
        finally:
            release.touch()
            assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '0') == b'OK'
        assert first.read() == second.read() == b'OK'
        live = admin.cmd('MGET', *keys)
        assert live in ([b'aoforder-group1'] * 2, [b'aoforder-group2'] * 2), live
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = admin.cmd('MGET', *keys)
        h.emit('loadaof', live=live, reloaded=reloaded, equal=live == reloaded)
    with h.Server(options) as server:
        restarted = server.client().cmd('MGET', *keys)
        h.emit('restart', live=live, restarted=restarted, equal=live == restarted)
    assert reloaded == live and restarted == live, 'F3: crossing groups replay a torn pair'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--case', choices=('single', 'crossing', 'rewrite'), default='single')
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
    (crossing if args.case == 'crossing' else single)()


if __name__ == '__main__':
    main()
