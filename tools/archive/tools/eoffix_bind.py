#!/usr/bin/env python3
"""Bind actual entered instruction addresses to each production arm."""
import argparse
import json
import os
from pathlib import Path
import wave14
import wave14_summary

ROOT = Path(__file__).resolve().parents[1]
wave14.BUILD = ROOT/'build/eoffix'
wave14.DOC = ROOT/'docs/eoffix'
wave14.PRE = wave14.BUILD/'pre-source'
assert os.sched_getaffinity(0) <= set(range(8))
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--arm', choices=['pre', 'post', 'both'], default='both')
p.add_argument('--tag', default='')
a = p.parse_args()
rows = []
for kind, tag in (('ordinary', ''), ('receive', ''), ('parser', 'final')):
    for arm in (('pre', 'post') if a.arm == 'both' else (a.arm,)):
        selected_tag = a.tag if a.tag and arm == 'post' else tag
        for ns in ('normal', 'db0'):
            row = wave14_summary.binding((arm, kind, ns, selected_tag))
            rows.append(row)
            print(arm, kind, ns, row['matched'], '/', row['entered_groups'], flush=True)
wave14.save(wave14.DOC/('scope-binding'+('-'+a.arm+'-'+a.tag if a.tag else '')+'.json'), rows)
assert all(r['matched'] == r['entered_groups'] for r in rows)
