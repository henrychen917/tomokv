#!/usr/bin/env python3
import json,subprocess,hashlib
from pathlib import Path
import budget
ROOT=budget.ROOT;OUT=budget.OUT
rows=[]
for r in json.loads((OUT/'selected.json').read_text()):
 obj=r['object'];expected=budget.Bodies(Path(r['selected_trial']['output']));actual=budget.Bodies(ROOT/'build'/obj)
 symbols=expected.funcs.keys()|actual.funcs.keys()
 changed=[s for s in symbols if expected.canon(s)!=actual.canon(s)]
 rows.append(dict(object=obj,changed=changed,functions=len(symbols)))
(OUT/'final-equals-selected.json').write_text(json.dumps(rows,indent=2)+'\n')
assert all(not r['changed'] for r in rows)
subprocess.run(['python3',str(OUT/'identity.py')],cwd=ROOT,check=True)
ref=ROOT/'build/compat2b/headline-src/build';post=ROOT/'build';out=OUT/'identity';results=[]
for name,argv in [('hot',['python3','tools/lbstall_artifacts.py','compare',str(ref),str(post),str(out/'hot.json')]),
 ('full',['python3','tools/ccfix_audit.py',str(ref),str(post),str(out/'full')]),
 ('linked',['python3','docs/deadswitch/linked_bytes.py',str(ref/'tomokv'),str(post/'tomokv'),str(out/'linked.json')])]:
 with (out/(name+'.log')).open('w') as log:rc=subprocess.run(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
 results.append(dict(name=name,argv=argv,returncode=rc))
(out/'tools.json').write_text(json.dumps(results,indent=2)+'\n')
(OUT/'post-sha256.txt').write_text(hashlib.sha256((post/'tomokv').read_bytes()).hexdigest()+'  build/tomokv\n')
print(results,flush=True)
