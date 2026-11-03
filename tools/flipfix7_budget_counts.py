#!/usr/bin/env python3
"""Finite instruction scopes with the source-derived compiler budgets."""
import argparse,concurrent.futures,gzip,json,subprocess
from pathlib import Path
import flipfix7_counts as c
ROOT=c.ROOT
ap=argparse.ArgumentParser();ap.add_argument('--candidate-json');ap.add_argument('--tag',default='derived');ap.add_argument('--namespace',default='normal,db0');args=ap.parse_args()
namespaces=args.namespace.split(',')
with gzip.open(ROOT/'docs/flipfix7/counts-unadjusted.json.gz','rt') as f:previous=json.load(f)
c.BUILD=ROOT/'build/flipfix7/budget-counts'/args.tag;c.OUT=ROOT/'docs/flipfix7/budget-counts'/args.tag
c.BUILD.mkdir(parents=True,exist_ok=True);c.OUT.mkdir(parents=True,exist_ok=True)
rows=json.loads((ROOT/'docs/flipfix7/budgets/derive.json').read_text())
if args.candidate_json:
 candidate=json.loads(Path(args.candidate_json).read_text());rows=[r for r in rows if r['unit']!=candidate['unit']]+[candidate]
replace={str(ROOT/'build'/r['unit']):r['output'] for r in rows}
for ns in namespaces:
 out=c.BUILD/f'command-trial-{ns}';out.mkdir(exist_ok=True)
 receipt=json.loads(previous[f'command-post-{ns}-build.json']);cmd=[replace.get(s,s) for s in receipt['link']]
 renamed=out/'original-main.o'
 subprocess.run(['objcopy','--redefine-sym','main=execfair_original_main',replace[str(ROOT/'build/db0/src/main.o')],str(renamed)],check=True)
 cmd=[str(renamed) if x.endswith('/original-main.o') else x for x in cmd]
 cmd[cmd.index('-o')+1]=str(out/'probe');cmd+=['-Wl,--strip-debug']
 with (out/'link.log').open('w') as log:subprocess.run(['taskset','-c','48-60',*cmd],stdout=log,stderr=subprocess.STDOUT,check=True)
 (out/'receipt.json').write_text(json.dumps(dict(replacements=replace,link=cmd),indent=2)+'\n')
subprocess.run(['cp',str(ROOT/'build/flipfix7/counts/step'),str(c.BUILD/'step')],check=True)
prepared={('command','trial',ns):c.prepare('trial',ns,'command') for ns in namespaces}
cases=[('command','trial',ns,(cmd,'2s',batch,atomic,-1)) for ns in namespaces for cmd in ('GET','SET','INCR','MGET','MSET') for batch in (1,32) for atomic in (0,1)]
with concurrent.futures.ThreadPoolExecutor(8) as pool:result=list(pool.map(lambda cell:c.run(cell,prepared),cases))
pre=json.loads((ROOT/'docs/flipfix7/counts/results-pre-command.json').read_text());old={(r['namespace'],tuple(r['argv'])):r for r in pre}
for r in result:r['pre']=old[r['namespace'],tuple(r['argv'])]['total'];r['delta']=r['total']-r['pre']
c.save(c.OUT/'comparison.json',result)
print('POSITIVE',[(r['namespace'],r['argv'],r['delta']) for r in result if r['delta']>0],flush=True)
