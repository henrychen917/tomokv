#!/usr/bin/env python3
"""Exact CLIENT TRACKING frames and CC4.4 accounting, compared with Redis 7.4."""
import argparse
import json
from pathlib import Path
import select
import time

from _lib import Conn, info, topology


def equal(actual, expected, label):
    assert actual == expected, f'{label}: got {actual!r}, expected {expected!r}'


def raw_frame(c):
    prefix = c.file.read(1)
    line = c.file.readline()
    assert prefix and line.endswith(b'\r\n'), (prefix, line)
    out = prefix + line
    if prefix == b'$' and int(line) >= 0:
        size = int(line) + 2
        data = c.file.read(size)
        assert len(data) == size and data.endswith(b'\r\n'), data
        out += data
    elif prefix in (b'*', b'>'):
        out += b''.join(raw_frame(c) for _ in range(max(0, int(line))))
    else:
        assert prefix in (b'+', b'-', b':', b'_', b'$'), prefix
    return out


def drain(c, wanted, label):
    frames = []
    for _ in range(wanted):
        assert select.select([c.sock], [], [], 5)[0], label + ': missing frame'
        frames.append(raw_frame(c))
    # Absence is an assertion, not a skipped arm. Positive cases already waited
    # for their final frame, and all sockets are unbuffered.
    while select.select([c.sock], [], [], .05)[0]:
        frames.append(raw_frame(c))
    return frames


def invalidation(key, protocol):
    tail = b'*1\r\n$%d\r\n%s\r\n' % (len(key), key)
    return ((b'>2\r\n$10\r\ninvalidate\r\n' if protocol == 3 else
             b'*3\r\n$7\r\nmessage\r\n$20\r\n__redis__:invalidate\r\n') + tail)


class Peer:
    def __init__(self, host, port, target, args):
        self.host, self.port, self.target = host, port, target
        self.admin = self.connect()
        self.writer = self.connect()
        self.args = args
        if target:
            observed = info(self.admin, 'server')
            wanted = dict(thread_mode=args.mode, net_io=args.engine,
                          atomic=str(args.atomic), read_local=str(args.read_local), shards='16')
            for key, value in wanted.items():
                equal(observed.get(key), value, 'geometry ' + key)
            topo = topology(self.admin)
            equal(len(topo.roles), 8, 'eight threads')
            equal(len(topo.shard_owner), 16, 'sixteen shards')
            roles = {role: list(topo.roles.values()).count(role) for role in ('io', 'ex', 'fused')}
            equal(roles, dict(io=6, ex=2, fused=0) if args.mode == '2s' else
                  dict(io=0, ex=0, fused=8), 'thread roles')
            print('GEOMETRY ' + json.dumps(wanted), flush=True)
        else:
            equal(info(self.admin, 'server')['redis_version'], '7.4.10', 'oracle version')
        equal(self.admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', ''), b'OK', 'notify off')

    def connect(self):
        return Conn(self.host, self.port, timeout=5, buffering=0)

    def counters(self):
        if not self.target:
            return {}
        data = info(self.admin, 'stats')
        return {k: int(data[k]) for k in ('notify_events_fired', 'notify_events_dropped',
                                        'tracking_invalidations')}

    def case(self, protocol, mode):
        key = f'trackfix:accounting:{protocol}:{mode}'.encode()
        reader = self.connect()
        listener = reader if protocol == 3 else self.connect()
        try:
            equal(self.writer.cmd('SET', key, 'before'), b'OK', 'prime before tracking')
            if protocol == 3:
                reader.cmd('HELLO', 3)
                redirect = []
            else:
                redirect = ['REDIRECT', listener.cmd('CLIENT', 'ID')]
                equal(listener.cmd('SUBSCRIBE', '__redis__:invalidate'),
                      [b'subscribe', b'__redis__:invalidate', 1], 'RESP2 redirect subscriber')
            flags = [] if mode == 'default' else [mode]
            equal(reader.cmd('CLIENT', 'TRACKING', 'ON', *redirect, *flags), b'OK', 'tracking on')
            if mode == 'OPTIN':
                equal(reader.cmd('CLIENT', 'CACHING', 'YES'), b'OK', 'opt in')
            equal(reader.cmd('GET', key), b'before', 'priming GET')
            equal(drain(listener, 0, 'priming'), [], 'no priming pushes')
            before = self.counters()
            equal(self.writer.cmd('SET', key, 'after'), b'OK', 'tracked mutation')
            frames = drain(listener, 1, 'tracked mutation')
            equal(frames, [invalidation(key, protocol)], 'one exact invalidation')
            after = self.counters()
            result = dict(protocol=protocol, mode=mode, frames=[f.hex() for f in frames],
                          counters_before=before, counters_after=after)
            # Print the successful delivery before asserting the broken PRE counter.
            print(('TARGET ' if self.target else 'ORACLE ') + json.dumps(result), flush=True)
            if self.target:
                equal(after['notify_events_fired'] - before['notify_events_fired'], 1,
                      'one recorded event')
                equal(after['tracking_invalidations'] - before['tracking_invalidations'], 1,
                      'one delivered event')
                equal(after['notify_events_dropped'] - before['notify_events_dropped'], 0,
                      'CC4.4 delivered tracking event is not dropped')
            return frames
        finally:
            # Turn tracking off even if an assertion fails, so all subsequent
            # protocol/option legs run independently and retain their receipts.
            reader.cmd('CLIENT', 'TRACKING', 'OFF')
            reader.close()
            if listener is not reader:
                listener.close()

    def ordered(self, protocol, mode):
        key = f'trackfix:ordered:{protocol}:{mode}'.encode()
        reader = self.connect()
        listener = reader if protocol == 3 else self.connect()
        priming = self.connect()
        try:
            # Arm the writer's own notification branch before the scheduled SET.
            # A cross-owner TRACKING acknowledgement alone does not establish
            # that the writer's cached configuration has refreshed. The unmatched
            # BCAST prefix supplies no extra frame and keeps collection armed
            # while the filter-priming subscription is removed below.
            equal(self.writer.cmd('CLIENT', 'TRACKING', 'ON', 'BCAST', 'PREFIX',
                                  'trackfix-never:'), b'OK', 'writer observation armed')
            equal(self.writer.cmd('SET', key, 'before'), b'OK', 'initial value')
            # Seed the existing monotonic membership filter, then remove its
            # subscription. The actual tracker has never read this key yet.
            priming.cmd('HELLO', 3)
            equal(priming.cmd('CLIENT', 'TRACKING', 'ON'), b'OK', 'filter tracker on')
            equal(priming.cmd('GET', key), b'before', 'filter primed')
            equal(priming.cmd('CLIENT', 'TRACKING', 'OFF'), b'OK', 'filter tracker off')
            if protocol == 3:
                reader.cmd('HELLO', 3)
                redirect = []
            else:
                redirect = ['REDIRECT', listener.cmd('CLIENT', 'ID')]
                equal(listener.cmd('SUBSCRIBE', '__redis__:invalidate'),
                      [b'subscribe', b'__redis__:invalidate', 1], 'RESP2 redirect subscriber')
            equal(reader.cmd('CLIENT', 'TRACKING', 'ON', *redirect,
                             *([] if mode == 'default' else [mode])), b'OK', 'tracking on')
            equal(self.writer.cmd('SET', key, 'observed'), b'OK', 'older committed write')
            if self.target and mode != 'BCAST':
                receipt = Path(self.args.schedule_dir) / (key.decode() + '.held')
                end = time.monotonic() + 5
                while not receipt.exists():
                    assert time.monotonic() < end, 'real older notification was never held'
                    time.sleep(.002)
            before_read = drain(listener, 1 if mode == 'BCAST' else 0, 'older SET')
            if mode == 'OPTIN':
                equal(reader.cmd('CLIENT', 'CACHING', 'YES'), b'OK', 'opt in')
            equal(reader.cmd('GET', key), b'observed', 'read observed the older write')
            after_read = drain(listener, 0, 'read retirement')
            if self.target and mode != 'BCAST':
                receipt = Path(self.args.schedule_dir) / (key.decode() + '.replayed')
                assert receipt.exists(), 'held notification was not delivered before read retirement'
                equal(receipt.read_text(), '2\n', 'read was Done when older notification delivered')
            equal(self.writer.cmd('DEL', key), 1, 'later write')
            after_delete = drain(listener, 1, 'later write')
            transcript = [before_read, after_read, after_delete]
            print(('TARGET ' if self.target else 'ORACLE ') + json.dumps(dict(
                protocol=protocol, mode=mode, ordered_frames=[[f.hex() for f in stage]
                                                           for stage in transcript])), flush=True)
            expected = [[invalidation(key, protocol)] if mode == 'BCAST' else [],
                        [], [invalidation(key, protocol)]]
            equal(transcript, expected, 'DIFF-TRK-1 exact chronological frames')
            return transcript
        finally:
            reader.cmd('CLIENT', 'TRACKING', 'OFF')
            self.writer.cmd('CLIENT', 'TRACKING', 'OFF')
            priming.close()
            reader.close()
            if listener is not reader:
                listener.close()

    def overlap(self, protocol, mode, twins=False):
        key = f'trackfix:overlap:{protocol}:{mode}:{int(twins)}'.encode()
        reader = self.connect()
        listener = reader if protocol == 3 else self.connect()
        try:
            equal(self.writer.cmd('CLIENT', 'TRACKING', 'ON', 'BCAST', 'PREFIX',
                                  'trackfix-never:'), b'OK', 'writer observation armed')
            if protocol == 3:
                reader.cmd('HELLO', 3)
                redirect = []
            else:
                redirect = ['REDIRECT', listener.cmd('CLIENT', 'ID')]
                equal(listener.cmd('SUBSCRIBE', '__redis__:invalidate'),
                      [b'subscribe', b'__redis__:invalidate', 1], 'RESP2 redirect subscriber')
            equal(reader.cmd('CLIENT', 'TRACKING', 'ON', *redirect,
                             *([] if mode == 'default' else [mode])), b'OK', 'tracking on')
            equal(self.writer.cmd('SET', key, 'before'), b'OK', 'initial value')
            if self.target and mode != 'BCAST':
                receipt = Path(self.args.schedule_dir) / (key.decode() + '.primed')
                end = time.monotonic() + 5
                while not receipt.exists():
                    assert time.monotonic() < end, 'initial notification never reached the reader owner'
                    time.sleep(.002)
            equal(drain(listener, 1 if mode == 'BCAST' else 0, 'initial write'),
                  [invalidation(key, protocol)] if mode == 'BCAST' else [], 'initial frame')
            # OPTIN needs a CACHING command before each read; queue the pair in
            # one packet so no extra reader command reuses a held ROB slot.
            commands = []
            for _ in range(2 if twins else 1):
                if mode == 'OPTIN': commands.append(('CLIENT', 'CACHING', 'YES'))
                commands.append(('GET', key))
            reader.send(*commands[0]) if len(commands) == 1 else None
            if len(commands) > 1:
                from _lib import encode
                reader.sock.sendall(b''.join(encode(*command) for command in commands))
            if self.target and mode != 'BCAST':
                receipt = Path(self.args.schedule_dir) / (key.decode() + '.pending')
                end = time.monotonic() + 5
                wanted = str(2 if twins else 1) + '\n'
                while not receipt.exists() or receipt.read_text() != wanted:
                    assert time.monotonic() < end, 'all pending windows must open'
                    time.sleep(.002)
                equal(receipt.read_text(), wanted, 'all pending windows opened')
                assert not receipt.with_suffix('.overlapped').exists(), 'read released before the newer write'
            else:
                for command in commands:
                    equal(reader.read(), b'OK' if command[0] == 'CLIENT' else b'before',
                          'oracle/BCAST read before mutation')
            equal(self.writer.cmd('SET', key, 'changed'), b'OK', 'write overlaps tracking retirement')
            if self.target and mode != 'BCAST':
                for command in commands:
                    equal(reader.read(), b'OK' if command[0] == 'CLIENT' else b'before',
                          'real held read reply')
            first = drain(listener, 1, 'required overlapping invalidation')
            if self.target and mode != 'BCAST':
                receipt = Path(self.args.schedule_dir) / (key.decode() + '.overlapped')
                end = time.monotonic() + 5
                while not receipt.exists():
                    assert time.monotonic() < end, 'overlap event never resumed retirement'
                    time.sleep(.002)
                equal(receipt.read_text(), str(2 if twins else 1) + '\n', 'all held reads retired')
            equal(self.writer.cmd('SET', key, 'newer'), b'OK', 'second write without another read')
            second = drain(listener, 1 if mode == 'BCAST' else 0, 'no stale reenrollment')
            if mode == 'OPTIN':
                equal(reader.cmd('CLIENT', 'CACHING', 'YES'), b'OK', 'fresh opt in')
            equal(reader.cmd('GET', key), b'newer', 'fresh read reenrolls')
            equal(self.writer.cmd('DEL', key), 1, 'fresh later write')
            third = drain(listener, 1, 'fresh enrollment invalidates')
            actual = [first, second, third]
            expected = [[invalidation(key, protocol)],
                        [invalidation(key, protocol)] if mode == 'BCAST' else [],
                        [invalidation(key, protocol)]]
            print(('TARGET ' if self.target else 'ORACLE ') + json.dumps(dict(
                protocol=protocol, mode=mode, twins=twins,
                overlap_frames=[[f.hex() for f in stage] for stage in actual])), flush=True)
            equal(actual, expected, 'non-loss and retirement exact frames')
            return actual
        finally:
            reader.cmd('CLIENT', 'TRACKING', 'OFF')
            self.writer.cmd('CLIENT', 'TRACKING', 'OFF')
            reader.close()
            if listener is not reader: listener.close()

    def close(self):
        self.writer.close()
        self.admin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    parser.add_argument('--oracle', nargs=2, required=True)
    parser.add_argument('--mode', choices=['1s', '2s'], required=True)
    parser.add_argument('--engine', choices=['epoll', 'uring'], required=True)
    parser.add_argument('--atomic', type=int, required=True)
    parser.add_argument('--read-local', type=int, required=True)
    parser.add_argument('--case', choices=['accounting', 'ordered'], default='accounting')
    parser.add_argument('--schedule-dir')
    args = parser.parse_args()
    oracle = Peer(args.oracle[0], int(args.oracle[1]), False, args)
    target = Peer(args.host, args.port, True, args)
    failures = []
    checks = [('case', ())] if args.case == 'accounting' else [
        ('ordered', ()), ('overlap', (False,)), ('overlap', (True,))]
    try:
        for method, extra in checks:
            for protocol in (2, 3):
                for mode in ('default', 'BCAST', 'OPTIN', 'OPTOUT', 'NOLOOP'):
                    try:
                        expected = getattr(oracle, method)(protocol, mode, *extra)
                        equal(getattr(target, method)(protocol, mode, *extra), expected, 'Redis oracle exact frames')
                    except Exception as error:
                        failures.append(f'{method}{extra} RESP{protocol} {mode}: {error}')
                        print('FAIL ' + failures[-1], flush=True)
    finally:
        target.close()
        oracle.close()
    print(f'trackfix {args.case}: {10*len(checks)-len(failures)} passed, {len(failures)} failed')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
