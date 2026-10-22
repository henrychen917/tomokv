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
import aof_frames
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


def keys_on_two_owners(client, excluded=(), prefix='aoforder:'):
    owners = _lib.topology(client).shard_owner
    keys = {}
    for i in range(4096):
        key = f'{prefix}{i}'
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
        operation = h.ARGS.operation
        for key in keys:
            if operation != 'MSETNX':
                assert admin.cmd('SET', key, '0') == b'OK'
        commands = {
            'MSET': (['MSET', keys[0], '1', keys[1], '1'], [b'1', b'1'], 0, b'OK'),
            'MSETNX': (['MSETNX', keys[0], '1', keys[1], '1'], [b'1', b'1'], 0, 1),
            'DEL': (['DEL', *keys], [None, None], 0, 2),
            'UNLINK': (['UNLINK', *keys], [None, None], 0, 2),
            'RENAME': (['RENAME', *keys], [None, b'0'], 1, b'OK'),
        }
        command, expected, victim, group_reply = commands[operation]
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
                group.send(*command)
                armed = wait_for(lambda: (s if (s := stats(admin))['atomic_pending_entries'] >= 2
                                         else None), 'group did not install on both shards')
                assert not select.select([group.s], [], [], 0)[0], 'held group replied'
                writer.send('SET', keys[victim], '9')
                ordered = operation in ('MSETNX', 'RENAME') and 'atomic_txn_writer_waits' in before
                if ordered:
                    # D1/TO-B holds this writer until the admitted group decides.
                    # Keep the installed, undecided-group witness above; waiting
                    # for SET to run here would prevent the test releasing it.
                    wait_for(lambda: stats(admin)['atomic_txn_writer_waits'] >
                             before['atomic_txn_writer_waits'], 'writer never reached held unit')
                    assert not select.select([writer.s], [], [], 0)[0], 'writer bypassed held unit'
                    expected[victim] = b'9'
                    # Redis 7.4 exact group-then-SET replies are recorded in
                    # docs/txnorder2/oracle-sequencing/result.json.
                else:
                    wait_for(lambda: admin.cmd('GET', keys[victim]) == b'9',
                             'plain SET did not execute beneath the undecided group')
                h.emit('armed', before=before, after=armed, writer_ordered=ordered,
                       held_values=admin.cmd('MGET', *keys),
                       plain_reply_ready=bool(select.select([writer.s], [], [], 0)[0]))
            finally:
                # The before-manifest hook parks the writer thread itself. Release it
                # after witnessing both post-cut writes, before the commit-release
                # command can acquire an AOF reply fence that needs that writer.
                marker.unlink(missing_ok=True)
                assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '0') == b'OK'
        finally:
            marker.unlink(missing_ok=True)
        assert group.read() == group_reply
        assert writer.read() == b'OK'
        if rewrite:
            h.emit('rewrite_finished', info=h.wait_rewrite(admin))
        live = admin.cmd('MGET', *keys)
        assert live == expected, live
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
        commits_before = stats(admin)
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
        before = stats(admin)
        live = admin.cmd('MGET', *keys)
        after = stats(admin)
        assert live in ([b'aoforder-group1'] * 2, [b'aoforder-group2'] * 2), live
        kick = keys_on_two_owners(admin, prefix='aoforder-kick:')
        assert admin.cmd('MSET', kick[0], 'kick', kick[1], 'kick') == b'OK'
        live2 = admin.cmd('MGET', *keys)
        h.emit('visibility', live=live, live2=live2,
               commit_windows=before['atomic_commit_windows'] - commits_before['atomic_commit_windows'],
               **{name: after[name] - before[name]
                  for name in ('atomic_commit_windows', 'atomic_commit_holds')})
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = admin.cmd('MGET', *keys)
        h.emit('loadaof', live=live, reloaded=reloaded, equal=live == reloaded)
    # Decode only after the writer stopped. Preserve the native stream and its
    # ticket/payload order even when the visibility assertion below fails.
    for path in sorted(server.data.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            native = stream.read(8) == aof_frames.FILE_MAGIC
        if native:
            frames, size, truncated = aof_frames.read_frames(path)
            h.emit('aof_ticket_order', path=str(path), size=size, truncated=truncated,
                   frames=[dict(sid=f.sid, sequence=f.sequence,
                                records=[dict(kind=kind, key=key, ticket=ticket,
                                              payload=f.payload[pos + 40 + len(key):pos + 40 + len(key) + length])
                                         for kind, key, length, ticket, pos in f.records()])
                           for f in frames])
    with h.Server(options) as server:
        restarted = server.client().cmd('MGET', *keys)
        h.emit('restart', live=live, restarted=restarted, equal=live == restarted)
    assert live2 == live, ('live read lagged an acknowledged commit '
                          '(safe watermark; Server::atomic_commit_publish), not F3')
    assert reloaded == live and restarted == live, 'F3: crossing groups replay a torn pair'


def pop():
    """LMPOP's AOF group id is drawn after its already-visible single-key mutation."""
    options = h.aof(h.ARGS.policy) + ['--atomic', '1', '--databases', str(h.ARGS.databases)]
    with h.Server(options) as server:
        admin, group, writer = (server.client(timeout=10) for _ in range(3))
        keys = keys_on_two_owners(admin)
        assert admin.cmd('RPUSH', keys[0], 'x', 'y') == 2
        assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '1') == b'OK'
        try:
            group.send('LMPOP', 2, *keys, 'LEFT')
            wait_for(lambda: admin.cmd('LRANGE', keys[0], 0, -1) == [b'y'],
                     'LMPOP did not execute before its AOF decision')
            assert not select.select([group.s], [], [], 0)[0]
            writer.send('SET', keys[0], '9')
            wait_for(lambda: admin.cmd('TYPE', keys[0]) == b'string' and
                     admin.cmd('GET', keys[0]) == b'9', 'plain write did not execute')
            h.emit('pop_armed', remaining=['y'], plain='9')
        finally:
            assert admin.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', '0') == b'OK'
        assert group.read() == [keys[0].encode(), [b'x']]
        assert writer.read() == b'OK'
        live = [admin.cmd('TYPE', keys[0]), admin.cmd('DUMP', keys[0])]
        assert admin.cmd('DEBUG', 'LOADAOF') == b'OK'
        reloaded = [admin.cmd('TYPE', keys[0]), admin.cmd('DUMP', keys[0])]
        h.emit('loadaof', live=live, reloaded=reloaded, equal=live == reloaded)
    with h.Server(options) as server:
        client = server.client()
        restarted = [client.cmd('TYPE', keys[0]), client.cmd('DUMP', keys[0])]
        h.emit('restart', live=live, restarted=restarted, equal=live == restarted)
    assert reloaded == live and restarted == live, 'LMPOP group id is not its mutation ticket'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--case', choices=('single', 'crossing', 'rewrite'), default='single')
    parser.add_argument('--operation', choices=('MSET', 'MSETNX', 'DEL', 'UNLINK', 'RENAME', 'LMPOP'),
                        default='MSET')
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
    (crossing if args.case == 'crossing' else pop if args.operation == 'LMPOP' else single)()


if __name__ == '__main__':
    main()
