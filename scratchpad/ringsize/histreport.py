#!/usr/bin/env python3
"""Turn an inflight.sh .hist file into the delta distribution over the measured window."""
import sys

def parse(path):
    d = {}
    for line in open(path):
        k, _, v = line.strip().partition('=')
        d[k] = v
    return d

def delta(before, after):
    b = [int(x) for x in before.split(',')] if before else []
    a = [int(x) for x in after.split(',')] if after else []
    if not a:
        return []
    if not b:
        b = [0] * len(a)
    return [x - y for x, y in zip(a, b)]

def show(name, h):
    tot = sum(h)
    if not tot:
        print(f"  {name}: no samples")
        return
    print(f"  {name}: n={tot}")
    run = 0
    pcts = {}
    for i, c in enumerate(h):
        run += c
        for p in (50, 90, 99, 99.9, 100):
            if p not in pcts and run >= tot * p / 100.0:
                pcts[p] = i
    mean = sum(i * c for i, c in enumerate(h)) / tot
    hi = max(i for i, c in enumerate(h) if c)
    print(f"    mean={mean:.2f} p50={pcts.get(50)} p90={pcts.get(90)} "
          f"p99={pcts.get(99)} p99.9={pcts.get(99.9)} max={hi}")
    row = [(i, c) for i, c in enumerate(h) if c]
    print("    " + " ".join(f"{i}:{100.0*c/tot:.1f}%" for i, c in row if 100.0*c/tot >= 0.5))

for path in sys.argv[1:]:
    d = parse(path)
    print(f"{d.get('label')} ratio={d.get('ratio')} pipeline={d.get('pipeline')} "
          f"rate={d.get('rate')} hits={d.get('read_local_hits')} "
          f"inflight_write_fallbacks={d.get('read_local_fallback_inflight_write')}")
    show("live writes at read probe ", delta(d.get('probe_before'), d.get('probe_after')))
    show("live writes at write commit", delta(d.get('commit_before'), d.get('commit_after')))
    print()
