#!/usr/bin/env python3
"""Fold lottery runner results into the per-row calibration table.

Inputs are runner result files (results.json from `--all`, or a row's
result.json); a later file replaces an earlier result for the same row. The
table reports the per-attempt hit rate, the attempts and wall time a K-hit
campaign would need at that rate, and the rows that cannot reach K within the
budget, each with the witness primitive (a pause point) that would serve it.
"""
import argparse
import json
import math
from pathlib import Path
import sys

from lottery_runner import DEFAULT_HITS, registry, write_json

# Pause-point primitives from docs/flakeaudit2/remaining-v2.md, by family.
PAUSE_POINT = {
    'spinprobe': 'W10 parser-park publication + hold',
    'atomic_torn': 'W2 held read cut / lead fragment',
    'atomic_hazards': 'W2 held pinned cut / reader stage',
    's6': 'W3 controlled sampler traversal',
    'multi_exec': 'W16 EXEC installed/predecision latch',
    'blocking': 'W1 per-owner config query + W5 timeout stage',
    'limits': 'W5 cron/timeout stage with release',
    'servertail': 'W1 per-owner applied-config query',
    'expwide': 'W4 held command expiry cut',
    'slowlog': 'W1 per-owner applied-config query',
    'execatomic': 'W2 held first fragment',
    'execiso': 'W2 held first fragment',
    'xmove': 'W6 LMOVE phase-one hold',
    'debug': 'W7 DEBUG SLEEP entered/release latch',
    'snapshot capture/reload': 'W8 capture-cut hold',
    'snapshot groups': 'W9 APPLY-fragment hold',
    'flip saturated': 'W11 held admitted backlog',
    'TLS partial handshake/teardown': 'W12 per-connection TLS stage hold',
    'differential matrix': 'W3/W13/W14/W15 (per missing leg)',
}


def zero_hit_rate_bound(attempts, confidence=.95):
    """One-sided upper bound on the per-attempt hit rate after 0 hits."""
    return -math.expm1(math.log1p(-confidence) / attempts) if attempts else None


def calibrate(results, goal, budget):
    rows = []
    for row in registry():
        result = results.get(row['id'])
        entry = dict(id=row['id'], name=row['name'], family=row['family'],
                     job=row['job'], requires=row['requires'],
                     observable=row['observable'], measured=result is not None)
        if result is None:
            rows.append(entry)
            continue
        attempts, hits = result['attempts'], result['hits']
        seconds = result['seconds']
        per_attempt = seconds / attempts if attempts else None
        rate = hits / attempts if attempts else None
        need = math.ceil(goal / rate) if rate else None
        estimate = need * per_attempt if need and per_attempt else None
        entry.update(verdict=result['verdict'], attempts=attempts, hits=hits,
                     failures=result['failures'], errors=result['errors'],
                     incomplete=result['incomplete'], seconds=seconds,
                     seconds_per_attempt=per_attempt, hit_rate=rate,
                     hit_rate_upper95=(zero_hit_rate_bound(attempts) if attempts and not hits
                                       else None),
                     attempts_for_k=need, seconds_for_k=estimate,
                     witness_attempts=result.get('witness_attempts', {}),
                     reaches_k_in_budget=(estimate is not None and estimate <= budget))
        if not entry['reaches_k_in_budget']:
            entry['pause_point'] = PAUSE_POINT[row['family']]
        rows.append(entry)
    return rows


def fmt(value, spec):
    return '-' if value is None else format(value, spec)


def markdown(rows, goal, budget):
    lines = [f'| Row | Name | Witness | Verdict | Attempts | Hits | Hit rate | s/attempt '
             f'| Attempts for K={goal} | Minutes for K={goal} | Within {budget / 60:g} min? |',
             '|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        if not r['measured']:
            lines.append(f"| {r['id']} | {r['name']} | {', '.join(r['requires'])} | not run "
                         '| - | - | - | - | - | - | - |')
            continue
        rate = (fmt(r['hit_rate'], '.0%') if r['hits'] else
                f"0 (<{r['hit_rate_upper95']:.0%})" if r['attempts'] else '-')
        within = ('yes' if r['reaches_k_in_budget'] else f"NO - {r['pause_point']}")
        lines.append(
            f"| {r['id']} | {r['name']} | {', '.join(r['requires'])} | {r['verdict']} "
            f"| {r['attempts']} | {r['hits']} | {rate} | {fmt(r['seconds_per_attempt'], '.1f')} "
            f"| {fmt(r['attempts_for_k'], 'd')} "
            f"| {fmt(r['seconds_for_k'] and r['seconds_for_k'] / 60, '.1f')} | {within} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', nargs='+', type=Path)
    parser.add_argument('--hits', type=int, default=DEFAULT_HITS)
    parser.add_argument('--budget', type=float, default=600, help='seconds allowed for K hits')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    results = {}
    for path in args.results:
        value = json.loads(path.read_text())
        for result in value if isinstance(value, list) else [value]:
            results[result['row']['id']] = result
    rows = calibrate(results, args.hits, args.budget)
    table = markdown(rows, args.hits, args.budget)
    if args.json:
        write_json(args.json, dict(goal=args.hits, budget_seconds=args.budget, rows=rows))
    if args.markdown:
        args.markdown.write_text(table)
    sys.stdout.write(table)
    return 0


if __name__ == '__main__':
    sys.exit(main())
