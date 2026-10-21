#!/usr/bin/env python3
"""wave3: mkfix2 count receipts of the integrated binary (A+B, C reverted) next to the lane's own
PRE / A / AB / ABC finite-count rows (docs/mkfix2/counts.csv). Replies per send come from the
uninstrumented WB run; arena allocations per command (16 KiB posix_memalign requests) and all
allocation requests per command from the LD_PRELOAD run (docs/wave3/tools/mkcount.c). The lane's
mechanism counters (prepares, abandoned prepares, pool hits) came from instrumented builds that no
longer exist and are not reproduced. usage: mkfix_table.py <wb dir> <alloc dir> <out.json>"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(directory):
    rows = {}
    for line in (Path(directory) / 'rows.jsonl').read_text().splitlines():
        d = json.loads(line)
        rows[(d['mode'], d['command'], d['atomic'], d['pipeline'])] = d
    return rows


def main():
    wb, alloc = load(sys.argv[1]), load(sys.argv[2])
    lane = {}
    for r in csv.DictReader(open(ROOT / 'docs/mkfix2/counts.csv')):
        lane[(r['arm'], r['mode'], r['command'], int(r['atomic']), int(r['depth']))] = r
    table = []
    for key in sorted(wb):
        mode, command, atomic, depth = key
        a = alloc.get(key)
        arena = None
        if a and 'allocations' in a:
            arena = a['allocations']['posix_memalign']['n16384'] / a['measured_calls']
        row = dict(mode=mode, command=command, atomic=atomic, depth=depth,
                   replies_per_send=round(wb[key]['replies_per_send'], 3),
                   allocations_per_command=round(a['allocations_per_call'], 4) if a else None,
                   arena_allocations_per_command=round(arena, 5) if arena is not None else None,
                   measured_calls=wb[key]['measured_calls'])
        for arm in ('pre', 'a', 'ab', 'abc'):
            r = lane.get((arm, mode, command, atomic, depth))
            if r:
                row[f'lane_{arm}_replies_per_send'] = round(float(r['replies_per_send']), 3)
                row[f'lane_{arm}_arena_per_command'] = round(float(r['arena_allocations_per_command']), 5)
        table.append(row)
    Path(sys.argv[3]).write_text(json.dumps(table, indent=1) + '\n')
    print('mode cmd  at  p  | integrated rps  arena/cmd | lane PRE rps arena | A rps arena | AB rps arena')
    for r in table:
        print(f"{r['mode']} {r['command']:4} a{r['atomic']} p{r['depth']:<3} | {r['replies_per_send']:7.3f} {r['arena_allocations_per_command']!s:>9} | "
              f"{r.get('lane_pre_replies_per_send', '-')!s:>7} {r.get('lane_pre_arena_per_command', '-')!s:>8} | "
              f"{r.get('lane_a_replies_per_send', '-')!s:>7} {r.get('lane_a_arena_per_command', '-')!s:>8} | "
              f"{r.get('lane_ab_replies_per_send', '-')!s:>7} {r.get('lane_ab_arena_per_command', '-')!s:>8}")


if __name__ == '__main__':
    main()
