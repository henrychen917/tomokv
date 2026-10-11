import json,pathlib,subprocess,hashlib,sys
sys.path.insert(0,'tools')
from ccfix_audit import audit
root=pathlib.Path('docs/txnfix/txnfix3')
rows=json.loads((root/'scatter-all-final4/inventory.json').read_text())['functions']
details=[]
for obj in ('src/cmd/xshard.o','db0/src/cmd/xshard.o'):
 a=audit.Elf(pathlib.Path('build/txnfix2/pre')/obj);b=audit.Elf(pathlib.Path('build')/obj)
 aa=a.functions();bb=b.functions()
 for r in rows:
  if r['object']!=obj or r['equal']:continue
  old=a.canonical(aa[r['symbol']]) if r['symbol'] in aa else None
  new=b.canonical(bb[r['symbol']]) if r['symbol'] in bb else None
  row=dict(r,canonical_instruction_bytes_equal=bool(old and new and old[0]==new[0]))
  if row['canonical_instruction_bytes_equal']:
   row['pre_targets']=old[1];row['post_targets']=new[1]
  details.append(row)
(root/'scatter-all-final4/changed-details.json').write_text(json.dumps(details,indent=2)+'\n')
tls={}
for arm,path in [('pre',pathlib.Path('build/txnfix2/pre/tomokv')),('post',pathlib.Path('build/tomokv'))]:
 cmd=['readelf','-sW',str(path)];symbols={}
 for line in subprocess.check_output(cmd,text=True).splitlines():
  f=line.split()
  if len(f)>=8 and f[3]=='TLS' and f[6]!='UND':symbols[f[7]]=[int(f[1],16),int(f[2])]
 tls[arm]=dict(symbols=symbols,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),command=cmd)
tls['changed_existing']={k:[v,tls['post']['symbols'].get(k)] for k,v in tls['pre']['symbols'].items() if tls['post']['symbols'].get(k)!=v}
tls['added']={k:v for k,v in tls['post']['symbols'].items() if k not in tls['pre']['symbols']}
assert not tls['changed_existing']
(root/'tls-final4.json').write_text(json.dumps(tls,indent=2)+'\n')
hot=json.loads((root/'identity-final4/hot.json').read_text())
assert all(r['relocation_equal'] for r in hot)
summary={ns:sum(r['object'].startswith('db0/')==(ns=='db0') for r in hot) for ns in ('normal','db0')}
(root/'identity-final4/hot-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('TLS existing',len(tls['pre']['symbols']),'unchanged; lbstall',summary,'scatter changed',len(details))
