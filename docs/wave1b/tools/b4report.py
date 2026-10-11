#!/usr/bin/env python3
"""wave1b: attribute every hot body that differs between the bisection build b4 (b959fc844 with the
lanes' own budgets) and the final default build. Inputs: lbstall compare JSON (b4 -> final) and the
final attribution JSON (final vs origin/cpp). usage: b4report.py b4-hot.json attribution.json out.tsv"""
import json, re, sys
from collections import Counter
hot = json.load(open(sys.argv[1]))
attr = {(o['object'], x['symbol']): x for o in json.load(open(sys.argv[2])) for x in o['rows']}
B959 = {'src/main.o': 146891, 'db0/src/main.o': 146928, 'src/core/genthread.o': 129025,
        'db0/src/core/genthread.o': 129370, 'src/core/rl2s.o': 162035, 'db0/src/core/rl2s.o': 162000,
        'db0/src/core/reorder.o': 147752, 'src/cmd/xshard.o': 127844, 'db0/src/cmd/xshard.o': 126421,
        'src/cmd/acl.o': 35377, 'db0/src/cmd/acl.o': 35324, 'src/cmd/climon.o': 25743,
        'db0/src/cmd/climon.o': 25670, 'src/cmd/t_server.o': 31297, 'db0/src/cmd/t_server.o': 31629,
        'src/snapshot/snapshot.o': 14584, 'db0/src/snapshot/snapshot.o': 14457}
FINAL = {'src/main.o': 147428, 'db0/src/main.o': 147449, 'src/core/genthread.o': 129420,
         'db0/src/core/genthread.o': 129640, 'src/core/rl2s.o': 162300, 'db0/src/core/rl2s.o': 162334,
         'db0/src/core/reorder.o': 148258, 'src/cmd/xshard.o': 127880, 'db0/src/cmd/xshard.o': 126482,
         'src/cmd/acl.o': 35369, 'db0/src/cmd/acl.o': 35324, 'src/cmd/climon.o': 26145,
         'db0/src/cmd/climon.o': 26220, 'src/cmd/t_server.o': 31330, 'db0/src/cmd/t_server.o': 31725,
         'src/snapshot/snapshot.o': 14718, 'db0/src/snapshot/snapshot.o': 14562}
CF = re.compile(r'serve_suppressing|prepare_suppressing|climon_serve_suppressed|climon_prepare_suppressed')
rows = []
for r in hot:
    if r['relocation_equal']:
        continue
    obj, name = r['object'], r['name']
    a = attr.get((obj, r['symbol']))
    if CF.search(name):
        cause = 'climon fix ec0317384 (old clientfix signature; the renamed body replaces it)'
    elif obj.endswith('core/reorder.o') and ('r7_' in name or obj == 'src/core/reorder.o'):
        cause = 'R7 envelope regeneration d32c20a20 (savefix admission mirrored; src reorder.o has no budget)'
    elif B959.get(obj) != FINAL.get(obj):
        cause = f'budget {B959.get(obj)} -> {FINAL.get(obj)}'
    else:
        cause = 'UNEXPLAINED'
    if a is None:
        vs_origin = 'final == origin/cpp (b4 drift removed)'
    else:
        lc, eq = a['lanes_changed'], a['merged_equals_lane']
        if a.get('climonfix'): vs_origin = 'climon fix'
        elif a.get('r7_mirror_of'): vs_origin = 'R7 mirror of ' + '+'.join(a['r7_mirror_of'])
        elif eq and set(eq) & set(lc): vs_origin = 'lane-identical ' + '+'.join(sorted(set(eq) & set(lc)))
        elif len(lc) > 1: vs_origin = 'composite ' + '+'.join(lc)
        elif lc: vs_origin = 'single lane, differs from lane body: ' + lc[0]
        else: vs_origin = 'UNATTRIBUTED'
    rows.append((obj, cause, vs_origin, r['pre_size'], r['post_size'], name))
with open(sys.argv[3], 'w') as f:
    f.write('object\tcause_vs_b4\tfinal_vs_origin\tb4_size\tfinal_size\tbody\n')
    for row in rows:
        f.write('\t'.join(map(str, row)) + '\n')
print(len(rows), 'hot bodies differ from b4')
print(Counter(r[1].split(' (')[0] if not r[1].startswith('budget') else 'budget re-derivation' for r in rows))
print(Counter((r[1].split(' ')[0], r[2].split(' ')[0]) for r in rows))
