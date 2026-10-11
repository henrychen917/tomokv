#!/usr/bin/env python3
"""wave2: rank budget trials per object. Order: no non-intended hot change (bad_hot), intended
perfex hot bodies equal to perfex's own (intended_off), no unattributed/lane-differing hot body,
then fewest unattributed (C) and lane-differing (D) bodies, fewest changed bodies, and the value
nearest the headroom-preserving centre (991d48f65 budget + integrated IPA unit growth).
usage: rank.py <unit-sizes.jsonl> <trial files...>"""
import json, sys
from pathlib import Path

PRE_BUDGET = {'src/cmd/t_server.o': 31330, 'db0/src/cmd/t_server.o': 31725, 'src/persist/aof.o': 34400,
              'db0/src/persist/aof.o': 34800, 'src/cmd/xshard.o': 127880, 'db0/src/cmd/xshard.o': 126482,
              'src/main.o': 147428, 'db0/src/main.o': 147449, 'src/core/genthread.o': 129420,
              'db0/src/core/genthread.o': 129640, 'src/core/rl2s.o': 162300, 'db0/src/core/rl2s.o': 162334,
              'db0/src/core/reorder.o': 148258}
units = {}
for line in open(sys.argv[1]):
    units.update(json.loads(line))
for f in sys.argv[2:]:
    rows = [json.loads(l) for l in open(f) if l.startswith('{')]
    if not rows:
        continue
    obj = rows[0]['object']
    centre = PRE_BUDGET[obj] + units[obj]['delta']
    def key(d):
        v = int(d['params'].split('large-unit-insns=')[1].split()[0])
        return (d['bad_hot'], d['intended_off'], d['Chot'] + d['Dhot'], d['C'] + d['D'], d['changed'], abs(v - centre)), v
    ranked = sorted(rows, key=lambda d: key(d)[0])
    print(f'{obj}: centre {centre} (991d48f65 {PRE_BUDGET[obj]} + unit {units[obj]["delta"]:+d})')
    for d in ranked[:4]:
        k, v = key(d)
        print(f'   {v}: bad_hot={d["bad_hot"]} intended_off={d["intended_off"]} CDhot={k[2]} C={d["C"]} D={d["D"]} '
              f'changed={d["changed"]} A={d["A"]} B={d["B"]} |v-centre|={k[5]}')
