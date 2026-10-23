"""Strict IO-body diffs; no source-line or operand masking beyond gate tools."""
import difflib,gzip,importlib.util,json,re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('wave_identity',ROOT/'docs/wave4/identity.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
OUT=ROOT/'build/fliplisten/io-identity';OUT.mkdir(exist_ok=True)
DOC=ROOT/'docs/fliplisten/identity/io';DOC.mkdir(exist_ok=True)
def binary(name):
 b=a.audit.Binary(ROOT/'build'/name,OUT,literal_pools=True)
 return {n:v for n,v in b.groups.items() if re.search(r'::(?:r7_)?(?:arm_accept|admit_fd|on_accept|on_cqe|epoll_pass|run_loop)',n)}
if __name__=='__main__':
 with ProcessPoolExecutor(max_workers=2) as p:pre,post=list(p.map(binary,['tomokv-PRE','tomokv']))
 rows=[]
 for n,old in sorted(pre.items()):
  new=post.get(n,[])
  for i,x in enumerate(sorted(old,key=lambda b:b['addr'])):
   y=sorted(new,key=lambda b:b['addr'])[i] if i<len(new) else None
   same=y and x['ins']==y['ins'] and x['encodings']==y['encodings']
   row=dict(name=n,instance=i,equal=bool(same),pre_size=x['size'],post_size=y['size'] if y else None,
            pre_instructions=len(x['ins']),post_instructions=len(y['ins']) if y else None)
   rows.append(row)
   if not same:
    stem=f'{len(rows):03}'
    row['artifact']=stem
    (DOC/(stem+'.pre')).write_text(n+'\n'+'\n'.join(x['ins'])+'\n')
    if y:
     (DOC/(stem+'.post')).write_text(n+'\n'+'\n'.join(y['ins'])+'\n')
     (DOC/(stem+'.diff')).write_text(n+'\n'+'\n'.join(difflib.unified_diff(x['ins'],y['ins'],fromfile='PRE',tofile='POST'))+'\n')
 (DOC/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
 for f in OUT.glob('*.objdump'):f.unlink()
 a.OUT=ROOT/'build/fliplisten/identity-cache'
 before=a.inventory(ROOT/'build/tomokv-PRE');pad=a.inventory(ROOT/'build/tomokv-PAD-A')
 result=a.compare(pad,{'headline':before})
 changed=[r for r in result if not r['equal']]
 (DOC.parent/'pad-identity.json').write_text(json.dumps(dict(pre=before['sha256'],pad=pad['sha256'],
     bodies=len(result),changed=changed),indent=2)+'\n')
 print('IO bodies',len(rows),'strict identical',sum(r['equal'] for r in rows),'PAD changed',len(changed))
