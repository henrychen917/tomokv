#!/usr/bin/env python3
"""Bind actual entered instruction addresses to each production arm."""
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
rows = []
for kind, tag in (('ordinary', ''), ('receive', ''), ('parser', 'final')):
    for arm in ('pre', 'post'):
        for ns in ('normal', 'db0'):
            row = wave14_summary.binding((arm, kind, ns, tag))
            rows.append(row)
            print(arm, kind, ns, row['matched'], '/', row['entered_groups'], flush=True)
wave14.save(wave14.DOC/'scope-binding.json', rows)
assert all(r['matched'] == r['entered_groups'] for r in rows)
