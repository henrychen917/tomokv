#!/usr/bin/env python3
"""wave3: rank budget trials per object. Order: no unattributed or lane-differing hot body (hotCD),
then fewest unattributed (C) and lane-differing (D) bodies, fewest changed hot bodies (a hot body
equal to f821104a9 beats one equal only to a lane's own build), fewest changed bodies, and the value
nearest the headroom-preserving centre (f821104a9 budget + integrated IPA unit growth over
f821104a9). usage: rank.py <unit-sizes.jsonl> <trial files...>"""
import json, sys

# f821104a9 values. src/core/reorder.o has no override there: GCC 13's default unit limit is
# 1.4 x the running minimal unit size, whose final value is 105268 (-fdump-ipa-inline), i.e. an
# absolute limit of 147375.
PRE_BUDGET = {'src/cmd/t_server.o': 31379, 'db0/src/cmd/t_server.o': 31776, 'src/persist/aof.o': 34437,
              'db0/src/persist/aof.o': 34840, 'src/cmd/xshard.o': 127924, 'db0/src/cmd/xshard.o': 126566,
              'src/main.o': 147428, 'db0/src/main.o': 147449, 'src/core/genthread.o': 129447,
              'db0/src/core/genthread.o': 129704, 'src/core/rl2s.o': 162305, 'db0/src/core/rl2s.o': 162334,
              'db0/src/core/reorder.o': 148358, 'src/core/reorder.o': 147375}
units = {}
for line in open(sys.argv[1]):
    units.update(json.loads(line))
top = int(__import__('os').environ.get('TOP', '6'))
for f in sys.argv[2:]:
    rows = [json.loads(l) for l in open(f) if l.startswith('{')]
    if not rows:
        continue
    obj = rows[0]['object']
    centre = PRE_BUDGET[obj] + units[obj]['delta_vs_pre']
    def key(d):
        v = int(d['params'].split('large-unit-insns=')[1].split()[0])
        return (d['hotCD'], d['C'] + d['D'], d['hot_changed'], d['changed'], abs(v - centre)), v
    ranked = sorted(rows, key=lambda d: key(d)[0])
    extra = ' '.join(w for w in rows[0]['params'].split('--param') if 'large-unit' not in w and 'inline-unit-growth' not in w).strip()
    print(f'{obj} {extra}: centre {centre} (f821104a9 {PRE_BUDGET[obj]} + unit {units[obj]["delta_vs_pre"]:+d}), {len(rows)} trials')
    for d in ranked[:top]:
        k, v = key(d)
        print(f'   {v}: hotCD={d["hotCD"]} C={d["C"]} D={d["D"]} hot={d["hot_changed"]} (A{d["hotA"]} B{d["hotB"]}) '
              f'changed={d["changed"]} A={d["A"]} B={d["B"]} |v-centre|={k[4]}')
