#!/usr/bin/env python3
"""Maintainer-only 1 Hz bare-INFO poller for an already-running measurement arm.

Never starts a server or a load generator. Start it at the instrument's measured
window; use identical duration/pins on PRE, POST and PAD. A missed whole period
is an invalid 1 Hz cell, recorded with the completed responses rather than hidden.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from _lib import Conn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error('--seconds must be positive')
    report = dict(command='INFO', period_seconds=1, requested_polls=args.seconds,
                  completed_polls=0, polls=[], error=None)
    client = None
    try:
        client = Conn(args.host, args.port, timeout=30)
        start = time.monotonic()
        for index in range(args.seconds):
            target = start + index
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            sent = time.monotonic()
            if sent - target >= 1:
                raise RuntimeError('missed an entire 1 Hz period; reject this cadence')
            body = client.must('INFO')
            finished = time.monotonic()
            if not isinstance(body, bytes) or b'# Keyspace\r\n' not in body:
                raise RuntimeError('bare INFO did not return its keyspace section')
            report['polls'].append(dict(index=index, send_offset_s=sent-start,
                                        schedule_lag_ms=1000*(sent-target),
                                        latency_ms=1000*(finished-sent), reply_bytes=len(body)))
            report['completed_polls'] += 1
    except Exception as error:
        report['error'] = str(error)
    finally:
        if client:
            client.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    return int(report['error'] is not None or report['completed_polls'] != args.seconds)


if __name__ == '__main__':
    sys.exit(main())
