"""Check PAD(A)'s linked function identities against the frozen merged PRE."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'docs/wave4'))
import identity
pre=identity.inventory(ROOT/'build/wave4c/tomokv-pre')
result={}
for label,path in [('rebuilt-pre',ROOT/'build/wave4d/pad/objects/tomokv'),('pad-a',ROOT/'build/wave4d/tomokv-pad-a')]:
 inv=identity.inventory(path)
 names=set(pre['groups'])|set(inv['groups'])
 changed=[name for name in sorted(names) if identity.signature(pre['groups'].get(name,[]))!=identity.signature(inv['groups'].get(name,[]))]
 result[label]=dict(path=str(path),sha256=inv['sha256'],groups=len(names),changed=changed)
 print(label,len(names),'changed',len(changed),flush=True)
(ROOT/'docs/wave4d/pad-identity.json').write_text(json.dumps(result,indent=2)+'\n')
assert all(not r['changed'] for r in result.values()),result
