#!/usr/bin/env python3
"""Measure the directed XREAD sequence on an already-owned listener. No load generator.

Run separately on PRE/POST with the gate fold alone and with the gate's other
jobs active. The caller owns server startup, quiet preflight and gate receipts.
"""
import argparse
import json
from pathlib import Path
import time
from _lib import Conn
from _differ_aclkeys import wait_blocked


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--arm', required=True)
    p.add_argument('--condition', choices=('idle', 'gate-concurrent'), required=True)
    p.add_argument('--iterations', type=int, default=1000)
    args = p.parse_args()
    if args.iterations < 1:
        p.error('iterations must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    admin = Conn('127.0.0.1', args.port, timeout=2, buffering=0)
    rows = []
    try:
        for iteration in range(args.iterations):
            worker = Conn('127.0.0.1', args.port, timeout=2, buffering=0)
            row = dict(iteration=iteration, started_at=time.time())
            try:
                admin.cmd('DEL', 'block:aclkeys')
                ident = worker.cmd('CLIENT', 'ID')
                worker.send('XREAD', 'BLOCK', '0', 'STREAMS', 'block:aclkeys', '0')
                wait_blocked(admin, (worker.sock, worker.file), ident,
                             lambda conn, command: conn.cmd(*command), lambda value: value,
                             lambda _file: worker.read(), timeout=2.0)
                start = time.monotonic()
                assert admin.cmd('XADD', 'block:aclkeys', '1-0', 'field', 'value') == b'1-0'
                try:
                    reply = worker.read()
                except TimeoutError:
                    row['result'] = 'missed'
                else:
                    assert reply == [[b'block:aclkeys', [[b'1-0', [b'field', b'value']]]]], reply
                    row['result'] = 'woke'
                    assert worker.cmd('PING') == b'PONG'
                row['milliseconds'] = 1000 * (time.monotonic() - start)
            finally:
                worker.close()
            rows.append(row)
            with (args.output / 'iterations.jsonl').open('a') as log:
                log.write(json.dumps(row) + '\n')
    finally:
        admin.close()
    missed = sum(row['result'] == 'missed' for row in rows)
    result = dict(arm=args.arm, condition=args.condition, iterations=len(rows),
                  missed=missed, loss_rate=missed / len(rows), timeout_seconds=2,
                  endpoint=f'127.0.0.1:{args.port}',
                  limitation='Condition labels require the caller\'s gate overlap receipts.')
    (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return int(missed != 0)


if __name__ == '__main__':
    raise SystemExit(main())
