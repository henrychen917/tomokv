#!/usr/bin/env python3
"""Slope instructions/op per cell, and the A-vs-B table. Fields per row:
tag,rep,shape,keylen,pipeline,n1,n2, iu1,ia1,rate1, iu2,ia2,rate2"""
import sys, collections, statistics
rows = []
for line in open(sys.argv[1]):
    f = line.strip().replace(' ', ',').split(',')
    if len(f) != 13: continue
    tag, rep, shape, kl, pl, n1, n2, iu1, ia1, r1, iu2, ia2, r2 = f
    n1, n2 = int(n1), int(n2)
    d = n2 - n1
    rows.append(dict(tag=tag, shape=shape, kl=int(kl), pl=int(pl),
                     u=(int(iu2)-int(iu1))/d, a=(int(ia2)-int(ia1))/d,
                     rate=(float(r1)+float(r2))/2))
agg = collections.defaultdict(list)
for r in rows: agg[(r['shape'], r['kl'], r['pl'], r['tag'])].append(r)
tags = []
for r in rows:
    if r['tag'] not in tags: tags.append(r['tag'])
A, B = tags[0], tags[1] if len(tags) > 1 else tags[0]
def med(v, k): return statistics.median([x[k] for x in v]) if v else float('nan')
print(f"{'shape':<12}{'klen':>5}{'p':>4} | {A+' u/op':>12}{B+' u/op':>12}{'delta%':>9} | "
      f"{A+' all/op':>13}{B+' all/op':>13}{'delta%':>9} | {'rateA':>10}{'rateB':>10}")
cells = sorted({(r['shape'], r['kl'], r['pl']) for r in rows},
               key=lambda c: (c[0], c[1]))
worst = 0.0
for shape, kl, pl in cells:
    a = agg[(shape, kl, pl, A)]; b = agg[(shape, kl, pl, B)]
    au, bu, aa, ba = med(a,'u'), med(b,'u'), med(a,'a'), med(b,'a')
    du = 100*(bu-au)/au; da = 100*(ba-aa)/aa
    worst = max(worst, du)
    print(f"{shape:<12}{kl:>5}{pl:>4} | {au:>12.1f}{bu:>12.1f}{du:>+9.2f} | "
          f"{aa:>13.1f}{ba:>13.1f}{da:>+9.2f} | {med(a,'rate'):>10.0f}{med(b,'rate'):>10.0f}")
print(f"\nworst adverse user-instr cell: {worst:+.2f}%")
