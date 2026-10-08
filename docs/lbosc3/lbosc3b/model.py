#!/usr/bin/env python3
"""Offline stimulus calculation from the refused campaign; starts no processes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from lb_episodes import sampling_floor

CAMPAIGN = ROOT / 'build/lbosc3/episodes-mainline'
OUT = Path(__file__).resolve().parent
HOTMAX = (4, 8, 16, 32, 64, 128, 256)
MARGIN = 3


def model(seed, fraction, shard_sizes=None):
    owners = {int(s): int(o) for s, o in
              (v.split(':') for v in seed['identity']['shard_owners'].split(','))}
    ids = sorted(set(owners.values()))
    count = len(ids)
    shards = seed['shards']
    assert len(owners) == shards
    assert set(Counter(owners.values()).values()) == {shards // count}
    band = sampling_floor(count)
    rows = []
    for hotmax in HOTMAX:
        selected = seed['hot_keys'][:hotmax]
        assert [k for k, _ in selected] == [f'memtier-{i}' for i in range(1, hotmax + 1)]
        hot_shards = Counter(s for _, s in selected)
        hot_owners = Counter(owners[s] for _, s in selected)
        counts = [hot_owners[i] for i in ids]
        cold = {s: 1 / shards if shard_sizes is None else
                (shard_sizes[s] - hot_shards[s]) / (500000 - hotmax) for s in owners}
        load = {i: (1 - fraction) * sum(cold[s] for s in owners if owners[s] == i) +
                fraction * hot_owners[i] / hotmax for i in ids}
        span = max(load.values()) - min(load.values())
        ratio = 100 * count * span
        best = None
        for sid, source in owners.items():
            weight = (1 - fraction) * cold[sid] + fraction * hot_shards[sid] / hotmax
            for destination in ids:
                if destination == source:
                    continue
                after = dict(load)
                after[source] -= weight
                after[destination] += weight
                new_span = max(after.values()) - min(after.values())
                if new_span + 1e-9 < span and (best is None or new_span < best['span']):
                    best = dict(shard=sid, source=source, destination=destination,
                                span=new_span, after_ratio_pct=100 * count * new_span)
        rows.append(dict(hotmax=hotmax, owner_hot_counts=counts,
                         owner_load_pct=[100 * load[i] for i in ids],
                         hot_only_ratio_pct=100 * count * (max(counts) - min(counts)) / hotmax,
                         ratio_pct=ratio, band_pct=band, ratio_bands=ratio / band,
                         three_bands=ratio >= MARGIN * band, best_single_shard_move=best))
    eligible = [r['hotmax'] for r in rows if r['three_bands']]
    return dict(owners=ids, shards=shards, hot_fraction=fraction, band_pct=band,
                three_band_pct=MARGIN * band, largest_hotmax=max(eligible, default=None), rows=rows)


def main():
    result = dict(margin_bands=MARGIN,
                  assumptions='Uniform hot-key visits and uniform cold load per shard; equal-cost SETs; initial recorded ownership; no pinning; 1:1 cohort rates for declaration. Actual learned jitter can widen the floor.',
                  modes={}, sources={})
    for mode in ('1s', '2s'):
        seed_path = CAMPAIGN / f'seed-{mode}/manifest.json'
        seed = json.loads(seed_path.read_text())
        rates = {}
        for cohort in ('hot', 'cold'):
            path = CAMPAIGN / f'key-skew-{mode}-PRE-probe/{cohort}.json'
            rates[cohort] = json.loads(path.read_text())['ALL STATS']['Sets']['Ops/sec']
            result['sources'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        result['sources'][str(seed_path.relative_to(ROOT))] = hashlib.sha256(seed_path.read_bytes()).hexdigest()
        telemetry_path = CAMPAIGN / f'key-skew-{mode}-PRE-probe/telemetry.jsonl'
        with telemetry_path.open() as stream:
            first = json.loads(next(stream))
        shard_sizes = {int(s): v['size'] for s, v in first['signals']['shards'].items()}
        assert sum(shard_sizes.values()) == 500000
        result['sources'][str(telemetry_path.relative_to(ROOT))] = hashlib.sha256(telemetry_path.read_bytes()).hexdigest()
        fraction = rates['hot'] / sum(rates.values())
        result['modes'][mode] = dict(equal_rate=model(seed, .5),
                                    recorded_rate=model(seed, fraction), rates=rates,
                                    recorded_cold=model(seed, fraction, shard_sizes),
                                    seed_shard_sizes=shard_sizes,
                                    seed=seed)
    assert result['modes']['2s']['equal_rate']['largest_hotmax'] == 64
    assert result['modes']['2s']['recorded_rate']['largest_hotmax'] == 64
    assert result['modes']['1s']['equal_rate']['largest_hotmax'] == 128
    assert result['modes']['1s']['recorded_rate']['largest_hotmax'] == 128
    assert result['modes']['1s']['recorded_cold']['largest_hotmax'] == 128
    assert result['modes']['2s']['recorded_cold']['largest_hotmax'] == 64
    (OUT / 'hotmax-model.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['Model: equal-rate hot/cold SET cohorts; ratio = 100 * owners * (max(load)-min(load))/sum(load).',
             'Three-band margin applies to total demand. Hot-only ratios are shown to expose the cold-cohort dilution.', '']
    for mode, data in result['modes'].items():
        m = data['equal_rate']
        lines += [f"{mode}: owners {m['owners']}, {m['shards']} shards; band {m['band_pct']:.9f}%; 3 bands {m['three_band_pct']:.9f}%.", '',
                  '| HOTMAX | Hot keys per owner | Hot-only % | Total % | Total / band | Recorded-rate % | Recorded-rate + seed-cold % | Improves with one shard |',
                  '| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |']
        for r, observed, exact in zip(m['rows'], data['recorded_rate']['rows'], data['recorded_cold']['rows']):
            lines.append(f"| {r['hotmax']} | {','.join(map(str,r['owner_hot_counts']))} | {r['hot_only_ratio_pct']:.4f} | {r['ratio_pct']:.4f} | {r['ratio_bands']:.4f} | {observed['ratio_pct']:.4f} | {exact['ratio_pct']:.4f} | {'yes' if r['best_single_shard_move'] else 'no'} |")
        lines += ['', f"Largest HOTMAX with >=3 bands: {m['largest_hotmax']}; recorded hot fraction {data['recorded_rate']['hot_fraction']:.9f}.", '']
    lines += ['Predeclare 2s HOTMAX=64. 1s HOTMAX=256 arms but does NOT retain the declared three-band margin once cold traffic is counted; the largest model-compliant 1s value is 128. No favourable round selection or automatic stimulus change.', '']
    (OUT / 'hotmax-model.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
