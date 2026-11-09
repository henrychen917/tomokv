#!/usr/bin/env python3
"""Connection-hold cleanup liveness under a sliding reader, parked WAIT, and FLIP.

The companion directed unit proves a nonempty ROB throughout two-bucket rotation.
This live probe keeps 4096 commands outstanding at the client (at least 48),
checks every read, and requires cleanup progress in each observation interval.
It never infers a continuously nonempty server ROB from a TCP backlog alone.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from tornread import Conn, Tracker, choose_geometry, enc, info_fields


if os.environ.get('TORNHOLD_PTRACE_BINARY') and '--shards' in sys.argv:
    # Only the gate-owned FLIP witness child opts into sibling inspection.
    assert ctypes.CDLL(None).prctl(0x59616d61, ctypes.c_ulong(-1).value, 0, 0, 0) == 0
    binary = os.environ.pop('TORNHOLD_PTRACE_BINARY')
    os.execv(binary, [binary, *sys.argv[1:]])


def live_hold_snapshot(pid, identity, output):
    script = Path(__file__).resolve().parents[1] / 'tools/tornhold_snapshot.py'
    command = ['gdb', '-q', '-batch', '-p', str(pid),
               '-ex', 'python identity = ' + str(identity),
               '-ex', 'source ' + str(script), '-ex', 'detach']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    Path(output).write_text(completed.stdout + completed.stderr)
    rows = [line.removeprefix('TORNHOLD_SNAPSHOT ') for line in completed.stdout.splitlines()
            if line.startswith('TORNHOLD_SNAPSHOT ')]
    assert completed.returncode == 0 and len(rows) == 1, completed.stdout + completed.stderr
    return json.loads(rows[0])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--case', choices=('progress', 'wait', 'flip'), required=True)
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--json', required=True)
    args = p.parse_args()
    admin = Conn('127.0.0.1', args.port, timeout=15)
    mode = admin.call('CONFIG', 'GET', 'thread-mode')[1].decode()
    assert args.case != 'flip' or mode == '2s', mode
    groups, _, geometry = choose_geometry(admin, SimpleNamespace(
        groups=64, geometry='debug', read_mode='pipe'), 'hold:' + str(time.time_ns()))
    for group in groups:
        assert admin.call('MSET', *[item for key in group for item in (key, b'init:0')]) == b'OK'
    stop = threading.Event()
    errors = []
    counts = dict(writes=0, reads=0, changes=0, minimum_client_outstanding=4096)
    reader = None
    writer = None
    parked = None
    moving = None
    samples = []
    observer = Tracker()
    result = dict(case=args.case, mode=mode, geometry=geometry, samples=samples, counts=counts)

    def write():
        conn = Conn('127.0.0.1', args.port, timeout=15)
        try:
            seq = 0
            while not stop.is_set():
                a, b = groups[seq % len(groups)]
                seq += 1
                value = b'w0:%d' % seq
                conn.send(enc('MULTI') + enc('SET', a, value) + enc('SET', b, value) + enc('EXEC'))
                assert [conn.reply() for _ in range(4)] == [b'OK', b'QUEUED', b'QUEUED', [b'OK', b'OK']]
                counts['writes'] += 1
        except Exception as exc:
            errors.append(('writer', repr(exc))); stop.set()
        finally:
            conn.close()

    def read(conn):
        tracker = Tracker()
        pair = enc('GET', groups[0][0]) + enc('GET', groups[0][1])
        outstanding = 4096
        try:
            conn.send(pair * (outstanding // 2))
            while not stop.is_set():
                for _ in range(8):
                    value = conn.reply()
                    assert tracker.observe(value) is None, ('session order', value, tracker.snapshot())
                    outstanding -= 1
                    counts['reads'] += 1
                    counts['changes'] = tracker.changes
                counts['minimum_client_outstanding'] = min(counts['minimum_client_outstanding'], outstanding)
                assert outstanding >= 48
                conn.send(pair * 4); outstanding += 8
            # Preserve the connection for the post-FLIP ownership observation.
            for _ in range(outstanding):
                value = conn.reply()
                assert tracker.observe(value) is None, ('final session order', value)
                counts['reads'] += 1
                counts['changes'] = tracker.changes
        except Exception as exc:
            errors.append(('reader', repr(exc))); stop.set()

    try:
        writer = threading.Thread(target=write); writer.start()
        deadline = time.monotonic() + 10
        while counts['writes'] < 128 and not errors:
            assert time.monotonic() < deadline, ('writer did not arm', counts)
            time.sleep(.01)
        assert not errors, errors
        if args.case == 'wait':
            parked = Conn('127.0.0.1', args.port, timeout=15)
            identity = parked.call('CLIENT', 'ID')
            parked.send(enc('GET', groups[0][0]) + enc('GET', groups[0][1]) + enc('WAIT', 1, 0))
            tracker = Tracker()
            assert tracker.observe(parked.reply()) is None
            assert tracker.observe(parked.reply()) is None
            fields = dict(item.split(b'=', 1) for item in admin.call('CLIENT', 'LIST', 'ID', identity).split())
            assert fields[b'cmd'] == b'wait' and b'b' in fields[b'flags'], fields
            assert not parked.buf[parked.pos:] and not select.select([parked.sock], [], [], .05)[0]
            result['parked_wait_client'] = identity
        else:
            if args.case == 'flip':
                # Select a different IO from the coordinator, and require a move below.
                coordinator = admin.call('DEBUG', 'IO-THREAD')
                target = max(set(range(8)) - set(geometry['owners_seen']) - {coordinator})
                for _ in range(128):
                    conn = Conn('127.0.0.1', args.port, timeout=15)
                    if conn.call('DEBUG', 'IO-THREAD') == target:
                        moving = conn; break
                    conn.close()
                assert moving is not None, ('could not place migrating reader', target)
            else:
                moving = Conn('127.0.0.1', args.port, timeout=15)
            result['reader_io_before'] = moving.call('DEBUG', 'IO-THREAD')
            result['reader_id'] = moving.call('CLIENT', 'ID')
            assert admin.call('DEBUG', 'ATOMIC-READ-DELAY', 100) == b'OK'
            reader = threading.Thread(target=read, args=(moving,)); reader.start()
        # Rotating write keys let old records become empty even while newer writes run.
        # Ignore initialization, then demand advancement in every two-second interval.
        time.sleep(2)
        previous = int(info_fields(admin)['atomic_records_freed'])
        started = time.monotonic()
        flipped = False
        while time.monotonic() - started < args.seconds:
            time.sleep(2)
            assert not errors, errors
            if args.case == 'flip' and not flipped:
                assert counts['reads'] > 0 and counts['changes'] > 0, ('reader did not arm', counts)
                pid = int(info_fields(admin)['process_id'])
                result['hold_snapshots'] = []
                for attempt in range(8):
                    # Each retry observes freshly issued reads in the sliding window.
                    witness = live_hold_snapshot(pid, result['reader_id'],
                                                args.json + '.gdb-' + str(attempt))
                    result['hold_snapshots'].append(witness)
                    if witness['a_slot'] != 65535 and witness['dispatch'] != witness['flush']:
                        break
                    time.sleep(.02)
                else:
                    raise AssertionError('live hold on migrating reader never armed')
                assert admin.call('FLIP', 1, 7) == b'OK'
                report = admin.call('FLIP')
                result['flip_report'] = {key.decode(): value for key, value in
                                         zip(report[::2], report[1::2])}
                assert result['flip_report']['live_io'] == 1, result['flip_report']
                flipped = True
            info = info_fields(admin)
            freed = int(info['atomic_records_freed'])
            entries = int(info['atomic_pending_entries'])
            samples.append(dict(seconds=round(time.monotonic() - started, 3), freed=freed,
                                live_entries=entries, **counts))
            assert freed > previous, ('cleanup did not advance', samples)
            # 128 written keys times one ROB window is a deliberately finite bound;
            # the per-interval freed assertion independently falsifies a pinned hold.
            assert entries < len(groups) * 2 * 64, ('unbounded retained entries', samples)
            previous = freed
            assert observer.observe(admin.call('GET', groups[0][0])) is None
            result['observer_value_changes'] = observer.changes
            if parked:
                assert not parked.buf[parked.pos:] and not select.select([parked.sock], [], [], 0)[0], 'WAIT unexpectedly completed'
        stop.set()
        assert admin.call('DEBUG', 'ATOMIC-READ-DELAY', 0) == b'OK'
        if reader:
            reader.join(15); assert not reader.is_alive(), 'reader did not drain'
        writer.join(15); assert not writer.is_alive(), 'writer did not finish'
        assert not errors and counts['writes'] > 128, errors
        assert observer.changes > 0, ('no observed value changes', result)
        if moving:
            assert counts['reads'] and counts['changes'], ('vacuous reader', counts)
            result['reader_io_after'] = moving.call('DEBUG', 'IO-THREAD')
            if args.case == 'flip':
                assert flipped and result['reader_io_before'] != result['reader_io_after'], result
        result['ok'] = True
    finally:
        stop.set()
        try:
            admin.call('DEBUG', 'ATOMIC-READ-DELAY', 0)
        except Exception:
            pass
        for thread in (reader, writer):
            if thread: thread.join(20)
        for conn in (parked, moving, admin):
            if conn: conn.close()
        result['errors'] = errors
        with open(args.json, 'w') as output:
            json.dump(result, output, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
