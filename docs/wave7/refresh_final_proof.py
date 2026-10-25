#!/usr/bin/env python3
"""Rebind final offline proof after the cold prebuilt-specification correction."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import identity

ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0,os.sched_getaffinity(0)&set(range(64,96)))
env=dict(os.environ, WAVE7_COUNTED_HOT='1',
         WAVE7_CALLS_DOC='docs/wave7/callsites-expanded',
         WAVE7_IDENTITY_SUMMARY='docs/wave7/identity-expanded/summary.json')
commands=[
 ['python3','docs/wave7/identity.py','build/tomokv','docs/wave7/identity-expanded'],
 ['python3','docs/wave7/callsites.py'],
 ['python3','docs/wave7/review_identity.py'],
 ['python3','docs/wave7/provenance_diff.py'],
 ['python3','docs/wave7/command_provenance.py'],
 ['python3','docs/wave7/constant_proof.py'],
 ['python3','docs/wave7/r7_inventory.py'],
 ['python3','docs/wave7/pad_a.py'],
 ['python3','docs/wave7/identity.py','build/tomokv-wave7-PAD-A','docs/wave7/pad-identity-final'],
]
for command in commands:
 print('RUN',command,flush=True)
 subprocess.run(command,env=env,check=True)
old=identity.inventory(ROOT/'build/tomokv-wave7-before-prebuiltfix')
new=identity.inventory(ROOT/'build/tomokv')
names=set(old['groups'])|set(new['groups'])
changed=[dict(name=name,before=old['groups'].get(name,[]),after=new['groups'].get(name,[]))
         for name in sorted(names) if identity.signature(old['groups'].get(name,[])) != identity.signature(new['groups'].get(name,[]))]
assert changed and all('::l4prebuild_prepare_set(' in row['name'] or '::l4prebuild_notify_spec(' in row['name'] for row in changed), [row['name'] for row in changed]
summary=json.loads((ROOT/'docs/wave7/identity-expanded/summary.json').read_text())
pad=json.loads((ROOT/'docs/wave7/pad-identity-final/summary.json').read_text())
assert pad['hot_groups'] == pad['hot_headline']
receipt=dict(before_sha256=old['sha256'],after_sha256=new['sha256'],changed=changed,
             proof='Every other strict linked group is unchanged. The 80 retained command traces are rebound to final POST by command_provenance.py, including exact constant bytes and switch destinations. No counted body changed.',
             hot_groups=summary['hot_groups'],pad_hot_groups=pad['hot_groups'],
             trace_post_sha256={name:hashlib.sha256((ROOT/'docs/wave7/instructions'/name).read_bytes()).hexdigest()
                                for name in ('results-post.json','results-pre.json')})
(ROOT/'docs/wave7/prebuilt-fix-identity.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('PASS final binding; changed specification bodies',len(changed),'all other groups identical',flush=True)
