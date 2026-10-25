#!/usr/bin/env python3
"""Sequential correctness jobs, all through the gate's own selector."""
import argparse,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/datafix2';BUILD=ROOT/'build/datafix2'
jobs=json.loads((DOC/'required-jobs.json').read_text())
p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');args=p.parse_args()
# A previous gate owns this lane's slot; never overlap gate lifetimes.
while not (DOC/'pre-final-v2-gate-results.json').exists():time.sleep(1)
steps=[
 ('post-final-v2-directed-', 'gate', ROOT/'build/tomokv', jobs['directed'],None),
 ('post-related-', 'gate', ROOT/'build/tomokv', jobs['related'],None),
 ('post-eviction-', 'gate', ROOT/'build/tomokv', jobs['eviction'],None),
 ('pre-related-', 'gate', ROOT/'build/pre-objects/build/tomokv',jobs['related'],ROOT/'build/pre-objects'),
 ('pre-eviction-', 'gate',ROOT/'build/tomokv-pre',jobs['eviction'],None),
 ('post-', 'differ', ROOT/'build/tomokv','',None),
 ('pre-', 'differ', ROOT/'build/tomokv-pre','',None),
]
results=json.loads((DOC/'campaign-results.json').read_text()) if args.resume else []
completed={entry['prefix'] for entry in results}
for prefix,phase,binary,selected,source in steps:
    if prefix in completed:continue
    if (BUILD/'stop-after-current').exists():break
    argv=['taskset','-c','96-111','python3',str(DOC/'verify.py'),phase,'--prefix',prefix,'--binary',str(binary)]
    if selected:argv+=['--jobs',selected]
    if source:argv+=['--source-root',str(source)]
    (DOC/'campaign-state.json').write_text(json.dumps(dict(active=prefix,argv=argv),indent=2)+'\n')
    rc=subprocess.run(argv,cwd=ROOT).returncode
    results.append(dict(prefix=prefix,phase=phase,driver_returncode=rc))
    (DOC/'campaign-results.json').write_text(json.dumps(results,indent=2)+'\n')
(DOC/'campaign-state.json').write_text(json.dumps(dict(active=None,completed=len(results),planned=len(steps)))+'\n')
