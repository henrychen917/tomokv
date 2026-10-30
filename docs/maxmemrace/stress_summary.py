#!/usr/bin/env python3
"""Summarize tests/maxmemrace_run.py results into docs/maxmemrace/stress-summary.json.

Per leg: geometry, toggles completed, SETs checked after each edge and every
violation class. Binary and driver hashes identify the arms. No rates.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'build/maxmemrace/stress-results'
LABELS = ('pre', 'post', 'pre-fused-shard0', 'post-fused-shard0', 'oracle')
KEEP = ('cycles', 'lift_sets', 'lift_oom', 'lift_other', 'tight_sets', 'tight_strict_sets',
        'tight_strict_admitted', 'tight_ok', 'tight_oom', 'eviction_checks', 'evicted_after_lift',
        'bg_mode', 'bg_shard', 'bg_threads', 'bg_conns', 'bg_pipe', 'bg_keys', 'bg_groups',
        'geometry_shards', 'conns', 'per_conn', 'tight', 'near_value', 'violations', 'rc',
        'lift_examples', 'tight_examples', 'evict_examples', 'other_examples')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out = dict(binaries={k: dict(path=p, sha256=sha(ROOT / p)) for k, p in (
                   ('PRE', 'build/maxmemrace/pre/tomokv'), ('POST', 'build/maxmemrace/post/tomokv'),
                   ('Redis', '/home/user/Projects/redis/src/redis-server'))},
               drivers=dict(v1=sha(ROOT / 'build/maxmemrace/stress-v1'),
                            v2=sha(ROOT / 'build/maxmemrace/stress'),
                            note='v1 ran the PRE main matrix; v2 adds only --bg-shard (default -1 '
                                 'is v1 behaviour) and ran every other label'),
               runs={})
    for label in LABELS:
        path = RESULTS / f'{label}.json'
        if not path.exists():
            continue
        legs = []
        for record in json.loads(path.read_text()):
            r = record.get('result', {})
            legs.append(dict(leg=record['leg_id'], **record['leg'], complete=record['complete'],
                             driver_rc=record['driver_rc'], server_rc=record.get('server_rc'),
                             server_alive_after_driver=record.get('server_alive_after_driver'),
                             **{k: r.get(k) for k in KEEP}))
        totals = {k: sum(l[k] or 0 for l in legs) for k in
                  ('cycles', 'lift_sets', 'lift_oom', 'tight_strict_sets', 'tight_strict_admitted',
                   'evicted_after_lift', 'violations')}
        totals['legs'] = len(legs)
        totals['legs_complete'] = sum(1 for l in legs if l['complete'])
        totals['legs_with_violations'] = sum(1 for l in legs if l['violations'])
        totals['other_replies'] = sum((l.get('lift_other') or 0) for l in legs)
        out['runs'][label] = dict(totals=totals, legs=legs)
    (ROOT / 'docs/maxmemrace/stress-summary.json').write_text(json.dumps(out, indent=1) + '\n')
    for label, run in out['runs'].items():
        print(label, run['totals'])


if __name__ == '__main__':
    main()
