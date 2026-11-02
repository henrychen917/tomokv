#!/usr/bin/env python3
"""Retire only completed, production-bound transient probes; keep every receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
out = root/'docs/eoffix/retired-artifacts.json'
rows = json.loads(out.read_text()) if out.exists() else []
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--arm', choices=['pre', 'post', 'both'], default='both')
p.add_argument('--tag', default='')
a = p.parse_args()
for kind, tag in (('ordinary', ''), ('receive', ''), ('parser', 'final')):
    for arm in (('pre', 'post') if a.arm == 'both' else (a.arm,)):
        tag = a.tag if a.tag and arm == 'post' else tag
        for ns in ('normal', 'db0'):
            binding = root/'docs/eoffix'/('scope-binding'+('-'+tag if tag else ''))/f'{arm}-{kind}-{ns}.json'
            directory = root/'build/eoffix/counts/scopes'/(f'{arm}-{kind}'+('-'+tag if tag else '')+'-'+ns)
            if not binding.exists() or not directory.exists():
                continue
            data = json.loads(binding.read_text())
            assert data['matched'] == data['entered_groups']
            with (directory/'probe').open('rb') as f:
                assert hashlib.file_digest(f, 'sha256').hexdigest() == data['probe_sha256']
            rows.append(dict(path=str(directory.relative_to(root)), probe_sha256=data['probe_sha256'],
                reason='All entered bodies bound; retain counts, raw traces, build recipe and binding. Disk budget: transient probe and objects retired.'))
            shutil.rmtree(directory)
out.write_text(json.dumps(rows, indent=2)+'\n')
