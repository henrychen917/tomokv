#!/usr/bin/env python3
"""Function byte sizes and .text totals across binaries."""
import subprocess, sys, re, collections
def sizes(path):
    out = subprocess.run(['nm','-C','-S','--size-sort',path], capture_output=True, text=True).stdout
    d = collections.defaultdict(int)
    for l in out.split('\n'):
        m = re.match(r'^[0-9a-f]+ ([0-9a-f]+) [a-zA-Z] (.+)$', l)
        if m: d[m.group(2)] += int(m.group(1), 16)
    return d
def textsz(path):
    out = subprocess.run(['size','-A',path], capture_output=True, text=True).stdout
    for l in out.split('\n'):
        if l.startswith('.text'): return int(l.split()[1])
    return 0
paths = sys.argv[1:]
tags = [p.split('/')[-1] for p in paths]
D = [sizes(p) for p in paths]
groups = [
 ('fused parse  <*,32u,...>',   lambda k: 'parse_and_dispatch<' in k and ', 32u,' in k),
 ('2s parse     <*, 0u,...>',   lambda k: 'parse_and_dispatch<' in k and ', 0u,' in k),
 ('FlatStore::hash_key',        lambda k: k.startswith('tomo::FlatStore::hash_key')),
 ('Rob::mark_current_write',    lambda k: 'Rob<64u>::mark_current_write' in k),
 ('DemotionPlan::prepare',      lambda k: 'ReadLocalDemotionPlan::prepare' in k),
 ('ExLoop drain_local_reads',   lambda k: 'drain_local_reads_bounded_impl' in k),
 ('Rob<64u>:: (all members)',   lambda k: 'Rob<64u>::' in k),
 ('IoLoop::flush_ready<*>',     lambda k: 'IoLoop::flush_ready<' in k),
 ('IoLoop::genthread_*',        lambda k: 'IoLoop::genthread_' in k),
 ('IoLoop::on_cqe<*>',          lambda k: 'IoLoop::on_cqe<' in k),
]
print(f"{'group':<28}" + "".join(f"{t[:16]:>18}" for t in tags))
base = None
for name, pred in groups:
    vals = [sum(v for k, v in d.items() if pred(k)) for d in D]
    row = f"{name:<28}"
    for i, v in enumerate(vals):
        row += f"{v:>12}" + (f" {100*(v-vals[0])/vals[0]:+5.1f}%" if i and vals[0] else "      ")
    print(row)
tv = [textsz(p) for p in paths]
row = f"{'.text total':<28}"
for i, v in enumerate(tv):
    row += f"{v:>12}" + (f" {100*(v-tv[0])/tv[0]:+5.2f}%" if i and tv[0] else "      ")
print(row)
