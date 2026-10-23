"""Expose every strict PAD residual; do not mask it out of the identity audit."""
import difflib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'));from reorder_noop import Binary
out=ROOT/'build/bugs5/pad-details';out.mkdir(exist_ok=True)
a=Binary(ROOT/'build/tomokv-PRE',out,True);b=Binary(ROOT/'build/tomokv-PAD-A',out,True)
rows=[]
for r in json.loads((ROOT/'docs/bugs5/pad-identity.json').read_text())['pad_a']['changed']:
 name=r['name'];aa=a.groups[name];bb=b.groups[name]
 rows.append(dict(name=name,pre=aa,post=bb))
 for i,(left,right) in enumerate(zip(aa,bb)):
  print(name,i)
  print('\n'.join(difflib.unified_diff([str(x) for x in left['ins']],[str(x) for x in right['ins']],n=1)))
(ROOT/'docs/bugs5/pad-differences.json').write_text(json.dumps(rows,indent=2)+'\n')
