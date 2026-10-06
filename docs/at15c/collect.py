#!/usr/bin/env python3
"""Preserve complete small receipts and compressed per-reply traces in git."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil

roots = ['trace-post', 'trace-pre', 'bisect-pre', 'bisect-post',
         'profile-post-mono', 'directed-split', 'absolute-control-post', 'absolute-control-pre',
         'profile-post-warm', 'profile-post-warm-2', 'trace-pre-warm',
         'profile-observed-mask-post', 'trace-observed-mask-pre',
         'profile-compiler-post', 'trace-compiler-pre']
manifest = []
for name in roots:
    root = Path('build/at15c') / name
    if not root.exists():
        continue
    target = Path('docs/at15c/receipts') / name
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(root.iterdir()):
        if source.name == 'perf.data':
            manifest.append(dict(path=str(source), bytes=source.stat().st_size,
                                 sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                 storage='worktree build artifact; not committed'))
        elif source.is_file() and source.suffix in ('.log', '.json'):
            dest = target / source.name
            data = source.read_bytes()
            if source.name.startswith('edgetime-') and source.suffix == '.json':
                dest = dest.with_suffix('.json.gz')
                dest.write_bytes(gzip.compress(data, mtime=0))
            else:
                shutil.copy2(source, dest)
            manifest.append(dict(path=str(dest), bytes=dest.stat().st_size,
                                 sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                                 original=str(source)))
for root in sorted(Path('build/at15c').glob('replay-*')):
    journal = root / 'legs.tsv'
    if not journal.exists():
        continue
    target = Path('docs/at15c/receipts') / root.name
    target.mkdir(parents=True, exist_ok=True)
    failures = [root / fields[5] for line in journal.read_text().splitlines()
                if (fields := line.split('\t'))[4] != '0']
    for source in [journal, *failures]:
        dest = target / source.name
        shutil.copy2(source, dest)
        manifest.append(dict(path=str(dest), bytes=dest.stat().st_size,
                             sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                             original=str(source)))
Path('docs/at15c/artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('preserved', len(manifest), 'artifacts')
