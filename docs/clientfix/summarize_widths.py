#!/usr/bin/env python3
"""Render the PFMESSAG.1 table from complete fixed-rate receipts; never run traffic."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from clientfix_widths import percentile


def busy_percent(row):
    before = row['load_before']['cpus']
    after = row['load_after']['cpus']
    delta = [sum(after[cpu][i] - before[cpu][i] for cpu in before) for i in range(8)]
    total = sum(delta)
    return 100 * (total - delta[3] - delta[4]) / total if total else 0


def render(rows):
    groups = defaultdict(list)
    hashes = defaultdict(set)
    for row in rows:
        assert row['samples'] >= 1000
        assert len(row['latency_us']) == row['samples']
        groups[row['arm'], row['mode'], row['width'], row['tracking']].append(row)
        hashes[row['arm']].add(row['sha256'])
    variants = ['pre'] + (['pad-a'] if 'pad-a' in hashes else []) + ['post']
    arms = [(arm, mode) for mode in ('1s', '2s') for arm in variants] + [('redis', 'oracle')]
    expected = {(arm, mode, width, tracking) for arm, mode in arms
                for width in (1, 32, 256, 1024) for tracking in ('off', 'bcast', 'default')}
    assert set(groups) == expected, f'incomplete shape matrix: {expected - set(groups)}'
    boots = {row['boot'] for row in rows}
    assert len(boots) >= 3
    assert len({row['samples'] for row in rows}) == 1, 'sample counts differ across arms'
    assert len({row['rate'] for row in rows}) == 1, 'offered rate differs across arms'
    assert all(len(values) == 1 for values in hashes.values()), 'binary changed between boots'
    stats = {}
    for key, group in groups.items():
        assert len(group) == len(boots) and {row['boot'] for row in group} == boots, key
        samples = [sample for row in group for sample in row['latency_us']]
        stats[key] = (percentile(samples, .5), percentile(samples, .99))

    out = ['## clientfix — PFMESSAG.1', '',
           f'{len(boots)} boots per arm, {rows[0]["rate"]:g} MSET/s. Percentiles pool equally sized',
           'boot samples; ratios divide pooled ON percentiles by the matching OFF percentile.',
           'Latency includes sender lag. Per-boot values and shared-CPU load appear below.', '']
    for arm, values in hashes.items():
        out.append(f'- {arm} SHA-256: `{next(iter(values))}`')
    if 'pad-a' in hashes:
        out += ['', 'PAD-A is a kind-A behavior twin: PRE behavior with POST sidecar layout and total',
                '.text size. It does not match every function address.']
    invalid = [row for row in rows if not row['below_offered_period']]
    if invalid:
        out += ['', f'**No under-capacity verdict: {len(invalid)} cells have p99 at or above the offered period.**']
    out += ['', '| Arm | Mode | Width | Tracking | p50 µs | p99 µs | ON/OFF p50 / p99 | Redis p50 / p99 µs | Redis ON/OFF p50 / p99 |',
            '|---|---|---:|---|---:|---:|---|---|---|']
    for arm, mode in arms[:-1]:
        for width in (1, 32, 256, 1024):
            for tracking in ('off', 'bcast', 'default'):
                p50, p99 = stats[arm, mode, width, tracking]
                off50, off99 = stats[arm, mode, width, 'off']
                redis50, redis99 = stats['redis', 'oracle', width, tracking]
                roff50, roff99 = stats['redis', 'oracle', width, 'off']
                out.append(f'| {arm} | {mode} | {width} | {tracking} | {p50:.3f} | {p99:.3f} | '
                           f'{p50/off50:.3f} / {p99/off99:.3f} | {redis50:.3f} / {redis99:.3f} | '
                           f'{redis50/roff50:.3f} / {redis99/roff99:.3f} |')
    out += ['', '| Boot | Arm | Mode | Width | Tracking | p50 / p99 µs | Lag p99 µs | CPUs 112–127 busy % | Loadavg before → after | Below period |',
            '|---:|---|---|---:|---|---|---:|---:|---|---|']
    for row in rows:
        load = ' → '.join(row[phase]['loadavg'].split()[0]
                          for phase in ('load_before', 'load_after'))
        out.append(f'| {row["boot"]} | {row["arm"]} | {row["mode"]} | {row["width"]} | '
                   f'{row["tracking"]} | {row["p50_us"]:.3f} / {row["p99_us"]:.3f} | '
                   f'{row["lag_p99_us"]:.3f} | {busy_percent(row):.1f} | {load} | '
                   f'{row["below_offered_period"]} |')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    print(render([json.loads(line) for line in args.receipt.read_text().splitlines()]), end='')
