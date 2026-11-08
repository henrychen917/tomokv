#!/usr/bin/env python3
"""Focused diagnosis on a listener owned by ccfix5_probe.sh, not a gate receipt."""
import argparse
import json
from pathlib import Path
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import _lib


def counters(conn):
    return {key: value for key, value in _lib.info(conn, 'all').items()
            if key.startswith(('read_local_', 'atomic_', 'keylb_', 'thread_mode', 'flip_'))}


def dump(conn, label, **fields):
    print(json.dumps(dict(label=label, counters=counters(conn), **fields)), flush=True)


def reads(conn, n=1024):
    for _ in range(n):
        assert conn.must('GET', 'ccfix5:clean') == b'value'


def probe(host, port, attempts, readers=False, swap=False, close_peers=False):
    admin = _lib.Conn(host, port, timeout=10)
    retained = []
    try:
        print(json.dumps({'server': _lib.info(admin, 'server'),
                          'lbsignals': _lib.lbsignals(admin).raw}), flush=True)
        atomic = int(_lib.info(admin, 'server')['atomic'])
        if swap:
            assert admin.must('SWAPDB', '0', '1') == b'OK'
        admin.must('SET', 'ccfix5:clean', 'value')
        reads(admin)
        dump(admin, 'before-reset')
        assert int(_lib.info(admin, 'stats')['read_local_hits']) > 0
        admin.must('CONFIG', 'RESETSTAT')
        dump(admin, 'after-reset')
        assert int(_lib.info(admin, 'stats')['read_local_hits']) == 0
        reads(admin)
        dump(admin, 'reads-after-reset')
        assert int(_lib.info(admin, 'stats')['read_local_hits']) > 0
        if not atomic:
            return
        if readers:
            admin.must('CONFIG', 'SET', 'atomic', '0')
            admin.must('CONFIG', 'SET', 'notify-keyspace-events', 'Em')
            subscriber = _lib.Conn(host, port, timeout=10)
            retained.append(subscriber)
            assert subscriber.cmd('SUBSCRIBE', '__keyevent@0__:keymiss')[0] == b'subscribe'
            admin.must('CONFIG', 'SET', 'atomic', '1')
        for attempt in range(attempts):
            admin.must('FLUSHALL')
            deadline = time.monotonic() + 5
            while int(_lib.info(admin, 'stats')['atomic_pending_entries']):
                assert time.monotonic() < deadline, 'old pending records did not drain'
                time.sleep(.005)
            buckets = _lib.owner_buckets(admin, 'ccfix5:%d:%d' % (attempt, time.time_ns()),
                                        per_owner=2)
            owners = [keys for keys in buckets.values() if len(keys) >= 2][:2]
            keys = [owners[0][0], owners[1][0]]
            dest = owners[1][1]
            verb = ('COPY', 'SINTERSTORE', 'BITOP')[attempt % 3]
            command = ([verb, keys[0], dest] if verb == 'COPY' else
                       [verb, 'OR', dest, *keys] if verb == 'BITOP' else
                       [verb, dest, *keys])
            writer = _lib.Conn(host, port, timeout=10)
            reader = _lib.Conn(host, port, timeout=10) if readers else None
            try:
                before = _lib.info(admin, 'stats')
                with _lib.armed(admin, 'ATOMIC-COMMIT-HOLD', 1):
                    writer.send('MSET', keys[0], 'private', keys[1], 'private')
                    deadline = time.monotonic() + 5
                    opened = False
                    while time.monotonic() < deadline:
                        current = _lib.info(admin, 'stats')
                        if int(current['atomic_pending_entries']) >= 2:
                            opened = True
                            break
                        time.sleep(.005)
                    ready = bool(select.select([writer.sock], [], [], 0)[0])
                    print(json.dumps(dict(label='pending-window', attempt=attempt,
                                          verb=verb if readers else None,
                                          opened=opened, writer_ready=ready, keys=keys,
                                          placement=[owner for owner, bucket in buckets.items()
                                                     if len(bucket) >= 2][:2],
                                          placement_after=_lib.shards_of(admin, keys),
                                          before=before, held=current,
                                          state=_lib.info(admin, 'server', 'lb'),
                                          lbsignals=_lib.lbsignals(admin).raw)), flush=True)
                    if opened and readers:
                        predecessor = int(current['atomic_predecessor_reads'])
                        reader.send(*command)
                        wanted = 1 if verb == 'COPY' else 2
                        deadline = time.monotonic() + 5
                        while int(_lib.info(admin, 'stats')['atomic_predecessor_reads']) - predecessor < wanted:
                            assert time.monotonic() < deadline, 'reader missed pending sources'
                            time.sleep(.005)
                assert writer.read() == b'OK'
                if opened and readers:
                    assert reader.read() == 0
            finally:
                if readers and not close_peers:
                    retained.extend((writer, reader))
                else:
                    writer.close()
                    if reader:
                        reader.close()
    finally:
        for conn in retained:
            conn.close()
        admin.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', type=int)
    parser.add_argument('--attempts', type=int, default=12)
    parser.add_argument('--readers', action='store_true')
    parser.add_argument('--swap', action='store_true')
    parser.add_argument('--close-peers', action='store_true')
    args = parser.parse_args()
    probe('127.0.0.1', args.port, args.attempts, args.readers, args.swap, args.close_peers)
