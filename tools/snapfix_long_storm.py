#!/usr/bin/env python3
"""Timeline of one tests/snapfix.py storm leg (no rates claimed): INFO sampled every --every s.

Runs the unchanged bgsave-exec (or bgsave-script) case for ONE leg with a longer --seconds and a
generous --stall, while a sampler on the same port records the snapshot, MVCC and transaction
counters below. It answers whether capture-time waits grow with storm length and why; it is a
diagnostic, never a gate row.
"""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import snapfix as s  # noqa: E402
from _lib import Conn  # noqa: E402

FIELDS = ('rdb_bgsave_in_progress', 'snapshot_cuts_armed', 'snapshot_groups_drained',
          'snapshot_preimages', 'atomic_pending_entries', 'atomic_entries', 'atomic_chain_max',
          'atomic_promotions', 'atomic_cleanup_fast', 'atomic_records_freed', 'atomic_groups',
          'atomic_txn_executed', 'atomic_txn_writer_waits', 'atomic_txn_place_waits',
          'atomic_txn_fast_polls', 'total_commands_processed', 'used_memory', 'used_memory_rss')


def sampler(port, every, stop, rows):
    conn = None
    while not stop.is_set():
        try:
            if conn is None:
                conn = Conn('127.0.0.1', port, timeout=2)
            text = conn.must('INFO', 'everything').decode(errors='replace')
            values = {}
            for line in text.splitlines():
                key, _, value = line.partition(':')
                if key in FIELDS:
                    values[key] = int(value) if value.lstrip('-').isdigit() else value
            rows.append(dict(t=round(time.monotonic(), 3), **values))
        except Exception:
            with contextlib.suppress(Exception):
                conn.close()
            conn = None
        stop.wait(every)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case', choices=['bgsave-exec', 'bgsave-script'], default='bgsave-exec')
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default='/home/user/Projects/redis74/src/redis-server')
    p.add_argument('--cores', default='16-23')
    p.add_argument('--port', type=int, default=20280)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', default='2s')
    p.add_argument('--engine', default='epoll')
    p.add_argument('--atomic', type=int, default=1)
    p.add_argument('--seconds', type=float, default=60)
    p.add_argument('--stall', type=float, default=60)
    p.add_argument('--every', type=float, default=1.0)
    p.add_argument('--dataset', type=int, default=30000)
    p.add_argument('--writers', type=int, default=4)
    p.add_argument('--burst', type=int, default=64)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stop, rows = threading.Event(), []
    thread = threading.Thread(target=sampler, args=(args.port, args.every, stop, rows), daemon=True)
    thread.start()
    began = time.monotonic()
    row = dict(case=args.case, leg=f'{args.mode}-{args.engine}-{args.atomic}', seconds=args.seconds)
    try:
        row['value'] = s.CASES[args.case](args, args.output / row['leg'], args.mode, args.engine,
                                          args.atomic, False)
        row['pass'] = True
    except Exception as error:
        row.update(pass_=False, error=repr(error))
    stop.set()
    thread.join(timeout=5)
    for sample in rows:
        sample['t'] = round(sample['t'] - began, 3)
    row['timeline'] = rows
    (args.output / 'timeline.json').write_text(json.dumps(row, indent=1) + '\n')
    print(json.dumps({k: v for k, v in row.items() if k != 'timeline'}))
    return 0 if row.get('pass') else 1


if __name__ == '__main__':
    raise SystemExit(main())
