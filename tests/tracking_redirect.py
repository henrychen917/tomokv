#!/usr/bin/env python3
"""Exact REDIRECT-close frames, with a witnessed in-flight target-close schedule."""
import argparse
import json
from pathlib import Path
import select
import time

from _lib import Conn, encode, info
from notifycompat import Capture, equal


def read(conn):
    conn.file.wire.clear()
    value = conn.read()
    return value, bytes(conn.file.wire)


def command(conn, *args):
    conn.send(*args)
    pushes, wires = [], []
    while True:
        value, wire = read(conn)
        if isinstance(value, list) and value and value[0] == b'tracking-redir-broken':
            pushes.append(value)
            wires.append(wire)
        else:
            return value, pushes, b''.join(wires)


def scenario(host, port, resp, schedule=None, reset=False):
    admin = Conn(host, port, buffering=0, timeout=5)
    owned = [admin]
    equal(admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', ''), b'OK', 'notifications off')
    try:
        for attempt in range(64 if schedule else 1):
            key = f'nc:redirect:r{resp}:reset{int(reset)}:{attempt}'
            admin.cmd('DEL', key)
            source = Conn(host, port, buffering=0, timeout=5)
            source.file = Capture(source.file)
            target = Conn(host, port, buffering=0, timeout=5)
            owned += [source, target]
            target.cmd('HELLO', 3)
            target_id = target.cmd('CLIENT', 'ID')
            if resp == 3:
                equal(command(source, 'HELLO', 3)[1], [], 'HELLO has no push')
            equal(command(source, 'CLIENT', 'TRACKING', 'ON', 'REDIRECT', target_id)[0], b'OK', 'tracking on')
            equal(command(source, 'GET', key)[0], None, 'register absent key')
            held = schedule / (key + '.held') if schedule else None
            if schedule:
                equal(admin.cmd('SET', key, 'changed'), b'OK', 'invalidation producer')
                deadline = time.monotonic() + 2
                while not held.exists() and time.monotonic() < deadline:
                    if select.select([target.sock], [], [], .01)[0]:
                        equal(target.read(), [b'invalidate', [key.encode()]], 'same-owner control frame')
                        break
                if not held.exists():
                    source.close()
                    target.close()
                    # Re-arm on new connections and a fresh key. Failure to reach
                    # the cross-owner window in the bounded search is a failure.
                    continue
                witness = json.loads(held.read_text())
                assert witness['origin'] != witness['target'], 'no cross-IO hop'
                print('HELD ' + json.dumps(witness), flush=True)
            if reset:
                equal(command(source, 'CLIENT', 'TRACKING', 'OFF')[0], b'OK', 'reset old generation')
                equal(command(source, 'CLIENT', 'TRACKING', 'ON', 'REDIRECT', target_id)[0], b'OK', 'new generation')
            equal(admin.cmd('CLIENT', 'KILL', 'ID', target_id), 1, 'close redirect target')
            target.close()
            assert all(f'id={target_id} '.encode() not in line for line in admin.cmd('CLIENT', 'LIST').splitlines())
            if schedule:
                (schedule / (key + '.release')).write_text('release\n')
                deadline = time.monotonic() + 5
                while not (schedule / (key + '.replayed')).exists():
                    assert time.monotonic() < deadline, 'held delivery never replayed'
                    admin.cmd('CLIENT', 'LIST')  # real IO control work on every owner
                    time.sleep(.002)
                admin.cmd('CLIENT', 'LIST')
                while int(info(admin)['pubsub_inflight']):
                    assert time.monotonic() < deadline, 'replayed transport never quiesced'
                    time.sleep(.002)
            elif not reset:
                equal(admin.cmd('SET', key, 'changed'), b'OK', 'oracle invalidation after close')
            pushes, wire = [], b''
            deadline = time.monotonic() + 2
            while True:
                value, frames, raw = command(source, 'CLIENT', 'TRACKINGINFO')
                pushes += frames
                wire += raw
                flags = dict(zip(value[::2], value[1::2]))[b'flags']
                if reset or b'broken_redirect' in flags or time.monotonic() >= deadline:
                    break
                time.sleep(.002)
            # One more in-order barrier detects duplicate pushes.
            pong, frames, raw = command(source, 'PING')
            equal(pong, b'PONG', 'source barrier')
            pushes += frames
            wire += raw
            expected = [] if reset or resp == 2 else [[b'tracking-redir-broken', target_id]]
            expected_wire = (b'>2\r\n$21\r\ntracking-redir-broken\r\n:' + str(target_id).encode() + b'\r\n') \
                if expected else b''
            print(json.dumps(dict(target=bool(schedule), resp=resp, reset=reset,
                                  attempt=attempt, target_id=target_id, flags=repr(flags),
                                  frames=repr(pushes), wire_hex=wire.hex())), flush=True)
            equal(flags, [b'on'] if reset else [b'on', b'broken_redirect'], 'broken redirect flag')
            equal(pushes, expected, 'exact broken redirect pushes')
            equal(wire, expected_wire, 'exact broken redirect wire')
            source.close()
            return
        raise AssertionError('cross-IO in-flight window never opened in 64 fresh attempts')
    finally:
        for conn in owned:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    parser.add_argument('--oracle', nargs=2)
    parser.add_argument('--schedule', type=Path)
    parser.add_argument('--case', default='redirect')
    parser.add_argument('--mode')
    parser.add_argument('--engine')
    parser.add_argument('--atomic', type=int)
    parser.add_argument('--read-local', type=int)
    args = parser.parse_args()
    peers = [(args.oracle[0], int(args.oracle[1]), None)] if args.oracle else []
    peers.append((args.host, args.port, args.schedule))
    failures = []
    for host, port, schedule in peers:
        if schedule:
            conn = Conn(host, port)
            observed = info(conn, 'server')
            for field, value in dict(thread_mode=args.mode, net_io=args.engine,
                                     atomic=str(args.atomic), read_local=str(args.read_local), shards='16').items():
                equal(observed[field], value, 'tracking geometry ' + field)
            conn.close()
        if not schedule:
            conn = Conn(host, port)
            equal(info(conn, 'server')['redis_version'], '7.4.10', 'oracle version')
            conn.close()
        for resp in (2, 3):
            for reset in (False, True):
                try:
                    scenario(host, port, resp, schedule, reset)
                except AssertionError as error:
                    failures.append(f'resp={resp} reset={reset} target={bool(schedule)}: {error}')
    assert not failures, '\n'.join(failures)
    print('PASS redirect', flush=True)


if __name__ == '__main__':
    main()
