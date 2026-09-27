#!/usr/bin/env python3
"""Strict OFFLINE window analyzer. Missing fields are errors; never drives a server."""
import argparse
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def info(text):
    result = {}
    for line in text.splitlines():
        if ':' in line and not line.startswith('#'):
            key, value = line.split(':', 1)
            if key.startswith('read_local_'):
                assert key not in result, f'duplicate INFO field: {key}'
                result[key] = int(value)
    return result


def analyze(before, after, metrics, mget=False):
    required = set(re.findall(r'"(read_local_[a-z_]+):', (ROOT / 'src/cmd/t_server.cc').read_text()))
    required = {k for k in required if mget or not k.startswith('read_local_mget_')}
    assert required and not required - before.keys() and not required - after.keys(), \
        f'missing INFO: before={sorted(required-before.keys())}, after={sorted(required-after.keys())}'
    deltas = {k: after[k] - before[k] for k in sorted(required)}
    assert all(v >= 0 for v in deltas.values()), 'counter reset/wrap during window'
    # Supplied by the reviewed driver/perf collector, not reconstructed from peak rates or INFO.
    for key in ('public_completed', 'get_completed', 'set_completed', 'seconds', 'offered_rate',
                'backlog_start', 'backlog_end', 'p50_us', 'p99_us', 'p999_us',
                'rss_before', 'rss_after', 'live_bytes_before', 'live_bytes_after'):
        assert key in metrics and math.isfinite(metrics[key]) and metrics[key] >= 0, f'missing/invalid {key}'
    for key in ('server_thread_ids', 'perf_threads', 'trace_sha256', 'command_run_lengths', 'null_bounds'):
        assert key in metrics, f'missing {key}'
    ids = metrics['server_thread_ids']
    assert len(set(ids)) == len(ids) and ids, 'invalid server thread inventory'
    rows = metrics['perf_threads']
    assert len(rows) == len(ids) and {r['tid'] for r in rows} == set(ids), 'perf must cover ALL server threads'
    for r in rows:
        assert r['cycles'] >= 0 and r['instructions'] >= 0 and r['running_fraction'] == 1, \
            'missing, unsupported or multiplexed PMU count'
    n = metrics['public_completed']; seconds = metrics['seconds']
    assert n > 0 and seconds > 0
    c = sum(r['cycles'] for r in rows); i = sum(r['instructions'] for r in rows)
    assert c > 0 and i > 0
    assert metrics['get_completed'] + metrics['set_completed'] <= n
    nulls = metrics['null_bounds']
    assert all(k in nulls and math.isfinite(nulls[k]) and nulls[k] >= 0
               for k in ('E_C', 'E_I', 'E_rate', 'E_tail')), 'missing frozen session nulls'
    assert metrics['backlog_end'] <= metrics['backlog_start'], 'growing backlog: reject matched-load window'
    return dict(C=c/n, I=i/n, IPC=i/c, rate=n/seconds,
                offered_rate=metrics['offered_rate'], completions_per_offered=n/seconds/metrics['offered_rate']
                if metrics['offered_rate'] else None,
                get_fraction=metrics['get_completed']/n, set_fraction=metrics['set_completed']/n,
                read_local_deltas=deltas, metrics=metrics,
                category_rule='Report aggregates and details separately; never sum overlapping fallback fields.',
                limitations=['Collector must prove public-command denominator and trace fidelity.',
                             'No PC/role attribution, cache hits, allocator rates or RSS attribution inferred from INFO.',
                             'Compare achieved rate against frozen E_rate; saturation uses a separate window.'])


def witness(text, before_ticket, after_ticket):
    rows = [json.loads(line.split('AT_RECYCLE ', 1)[1]) for line in text.splitlines()
            if line.startswith('AT_RECYCLE ')]
    def snapshot(ticket):
        result = {}
        for r in rows:
            if r['event'] != 'owner-boundary' or r['ticket'] != ticket:
                continue
            assert r['cache'] not in result, 'duplicate cache snapshot'
            result[r['cache']] = r
        return result
    a, b = snapshot(before_ticket), snapshot(after_ticket)
    assert a and a.keys() == b.keys(), 'missing owner snapshot; do not interpret it as zero'
    counters = 'takes hits misses outside_takes admitted collection encoding borrowed undersize outside_classes class_full empty bytes_full fresh fresh_failed thread_mallocx thread_sdallocx'.split()
    output = []
    for cache in a:
        x, y = a[cache], b[cache]
        assert x['tid'] == y['tid'], 'cache owner changed across window'
        d = {k: y[k] - x[k] for k in counters}
        assert all(v >= 0 for v in d.values()) and d['takes'] == d['hits'] + d['misses']
        d['eligible_takes'] = d['takes'] - d['outside_takes']
        d['hit_fraction'] = d['hits']/d['eligible_takes'] if d['eligible_takes'] else None
        d.update(cache=cache, tid=x['tid'], cache_bytes_before=x['cache_bytes'], cache_bytes_after=y['cache_bytes'],
                 classes_before=x['classes'], classes_after=y['classes'])
        output.append(d)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    run = sub.add_parser('window')
    run.add_argument('before'); run.add_argument('after'); run.add_argument('metrics'); run.add_argument('--mget', action='store_true')
    w = sub.add_parser('witness'); w.add_argument('log'); w.add_argument('before', type=int); w.add_argument('after', type=int)
    a = p.parse_args()
    try:
        if a.mode == 'window':
            result = analyze(info(Path(a.before).read_text()), info(Path(a.after).read_text()),
                             json.loads(Path(a.metrics).read_text()), a.mget)
        else:
            result = witness(Path(a.log).read_text(), a.before, a.after)
    except (AssertionError, KeyError, ValueError) as error:
        p.exit(2, f'ERROR: {error}\n')
    print(json.dumps(result, indent=2))
