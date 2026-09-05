#!/usr/bin/env python3
"""Mean +/- stderr of the paired cycles/instructions deltas, with IPC."""
import statistics as st, collections, sys
rows = [l.split(',') for l in open(sys.argv[1]).read().strip().split('\n') if ',' in l]
rows = [r for r in rows if r[0] in ('1s', '2s') and len(r) >= 10 and r[8]]
d = collections.defaultdict(list)
for r in rows:
    d[(r[0], r[1])].append(tuple(float(x) for x in (r[4], r[5], r[6], r[7])))
print("%-4s %-9s %10s %10s %10s %10s %9s %9s" %
      ("mode", "cell", "A instr", "B instr", "A cyc", "B cyc", "d_cyc", "IPC A->B"))
for (m, c), v in sorted(d.items()):
    ai = st.mean(x[0] for x in v); ac = st.mean(x[1] for x in v)
    bi = st.mean(x[2] for x in v); bc = st.mean(x[3] for x in v)
    dc = [x[3] - x[1] for x in v]; di = [x[2] - x[0] for x in v]
    sec = st.stdev(dc) / len(dc) ** 0.5 if len(dc) > 1 else 0.0
    sei = st.stdev(di) / len(di) ** 0.5 if len(di) > 1 else 0.0
    print("%-4s %-9s %10.0f %10.0f %10.0f %10.0f %+6.0f+-%-4.0f %.3f->%.3f" %
          (m, c, ai, bi, ac, bc, st.mean(dc), sec, ai / ac if ac else 0, bi / bc if bc else 0))
    print("%-4s %-9s %10s %10s %10s %10s %9s" %
          ("", "", "", "d_instr %+.0f+-%.0f" % (st.mean(di), sei), "", "", ""))
