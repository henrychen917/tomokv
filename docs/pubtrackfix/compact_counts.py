#!/usr/bin/env python3
"""Keep arm hashes and function counts; discard recorded per-PC step traces."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'docs/pubtrackfix/instructions-pc'
removed=[]
for f in sorted(p.iterdir()):
    if f.name.startswith(('pre-','post-')):
        removed.append({'path':str(f.relative_to(ROOT)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size})
        f.unlink()
    elif f.suffix=='.json':
        d=json.loads(f.read_text())
        if isinstance(d,list):
            for r in d:
                r.pop('pc_counts',None)
                if 'probe_sha256' in r:r['fixture_passed']=True
            f.write_text(json.dumps(d,indent=2)+'\n')
(ROOT/'docs/pubtrackfix/retired-step-traces.json').write_text(json.dumps(removed,indent=2)+'\n')
# Raw instruction plans/results are reproducible from retained fixtures and counter.
for f in (ROOT/'build/pubtrackfix/counts').glob('*-step.json'): f.unlink()
for f in (ROOT/'build/pubtrackfix/counts').glob('*/step-plan'): f.unlink()
