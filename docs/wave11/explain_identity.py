#!/usr/bin/env python3
"""Annotate every strict body difference; TLS explanations never erase a failure."""
import concurrent.futures, difflib, gzip, hashlib, json, os, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'docs/wave11')]
import wave11
from wave11_normalize import install
from tls_layout import read as tls_read
identity=wave11.references();install(identity.audit)
# All accepted jump tables start with LEA. Avoid constructing an entire large
# body for every non-LEA instruction; the accepted normalization is unchanged.
slow=identity.audit.LiteralPools.jump_label
def jump(self,index,body,instructions,addr,size):
    if not instructions[body[index]][1].startswith('lea '):return None
    return slow(self,index,body,instructions,addr,size)
identity.audit.LiteralPools.jump_label=jump
DOC=ROOT/'docs/wave11';OUT=ROOT/'build/wave11/body-explain'
rows=json.loads((DOC/'identity/changed-bodies.json').read_text())
names={r['name'] for r in rows}
os.sched_setaffinity(0,set(range(64,96)))

def load(item):
    label,path=item;path=Path(path);folder=OUT/label;folder.mkdir(parents=True,exist_ok=True)
    cache=folder/'selected.json.gz'
    if cache.exists():
        with gzip.open(cache,'rt') as f:return label,json.load(f)
    binary=identity.audit.Binary(path,folder,literal_pools=True)
    result=dict(sha256=binary.sha256,tls=tls_read(path),groups={n:b for n,b in binary.groups.items() if n in names})
    with gzip.open(cache,'wt') as f:json.dump(result,f)
    for p in folder.glob('*.objdump'):p.unlink()
    print('parsed',label,flush=True)
    return label,result

def tls_line(line,arm):
    # Only direct FS-relative operands whose full address lies in a named TLS
    # object are explained. Stack/member offsets and other immediates remain.
    def replace(m):
        value=int(m[1],16)
        if value>=1<<63:value-=1<<64
        hits=[(name,value-s['tp_offset']) for name,s in arm['tls']['symbols'].items()
              if s['tp_offset']<=value<s['tp_offset']+max(1,s['size'])]
        return '%fs:<'+repr(sorted(hits))+'>' if hits else m[0]
    return re.sub(r'%fs:0x([a-f0-9]+)',replace,line)

def body_tls_equal(a,b,aa,bb):
    if a['size']!=b['size'] or len(a['ins'])!=len(b['ins']):return False
    for x,y,xe,ye in zip(a['ins'],b['ins'],a['encodings'],b['encodings']):
        if x==y and xe==ye:continue
        if x==y or tls_line(x,aa)!=tls_line(y,bb):return False
        mx=re.search(r'%fs:0x([a-f0-9]+)',x);my=re.search(r'%fs:0x([a-f0-9]+)',y)
        if not mx or not my:return False
        old=(int(mx[1],16)&0xffffffff).to_bytes(4,'little').hex(' ')
        new=(int(my[1],16)&0xffffffff).to_bytes(4,'little').hex(' ')
        if xe.count(old)!=1 or ye.count(new)!=1 or xe.replace(old,'TLS')!=ye.replace(new,'TLS'):return False
    return True

if __name__=='__main__':
    paths={k:v for k,v in identity.REFS.items() if not k.startswith('baseline_')}
    paths['post']=ROOT/'build/wave11/tomokv-POST'
    with concurrent.futures.ProcessPoolExecutor(3) as pool:arms=dict(pool.map(load,paths.items()))
    details=[]
    for row in rows:
        name=row['name'];after=arms['post']['groups'].get(name,[])
        if row['matches']:
            row['explanation_kind']='lane-identical';continue
        matches=[]
        for label,arm in arms.items():
            if label=='post':continue
            before=arm['groups'].get(name,[])
            if len(before)==len(after) and before and all(body_tls_equal(a,b,arm,arms['post']) for a,b in zip(before,after)):
                matches.append(label)
        if matches:
            row['explanation_kind']='TLS-offsets-only';row['tls_equivalent_to']=matches
            row['reason']='Only verified direct FS-relative TLS addresses differ from '+', '.join(matches)+'. All opcodes, widths, other operands and local branches match; strict identity remains different.'
        else:
            row['explanation_kind']='composition-or-codegen'
        candidates=[]
        for label,arm in arms.items():
            if label=='post':continue
            before=arm['groups'].get(name,[])
            if len(before)==len(after)==1:
                a,b=before[0]['ins'],after[0]['ins'];delta=list(difflib.unified_diff(a,b,n=1))
                candidates.append((len(delta),label,delta))
        if candidates:
            _,label,delta=min(candidates)
            details.append(dict(name=name,reference=label,diff=delta))
    (DOC/'identity/changed-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
    (DOC/'identity/changed-bodies.md').write_text('\n'.join(['# Linked body differences','','Strict identity is retained. TLS equivalence is a separate, verified operand explanation.','','| Function | Headline sizes | POST sizes | Reason |','|---|---|---|---|',*[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows]])+'\n')
    with gzip.open(DOC/'identity/residual-diffs.json.gz','wt') as f:json.dump(details,f)
    counts={k:sum(r['explanation_kind']==k for r in rows) for k in sorted({r['explanation_kind'] for r in rows})}
    (DOC/'identity/explanations.json').write_text(json.dumps(dict(counts=counts,arms={k:v['sha256'] for k,v in arms.items()}),indent=2)+'\n')
    print(counts,flush=True)
