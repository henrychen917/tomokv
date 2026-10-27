#!/usr/bin/env python3
"""Command-scope controls for xshard compile trials; no rates or servers."""
import concurrent.futures, hashlib, json, subprocess
import instructions as count

rows=json.loads((count.ROOT/'docs/wave8b/budgets-helpers/scan.json').read_text())
cases=[]
for row in rows:
    if not row['object'].endswith('cmd/xshard.o'): continue
    ns='db0' if row['object'].startswith('db0/') else 'normal'
    arm='budget'+str(row['budget'])
    dest=count.BUILD/(arm+'-'+ns); dest.mkdir(exist_ok=True)
    recipe=json.loads((count.OUT/('post-'+ns+'-build.json')).read_text())
    link=[row['output'] if s==str(count.ROOT/'build'/row['object']) else s for s in recipe['link']]
    link[link.index('-o')+1]=str(dest/'probe')
    subprocess.run(link,check=True,stdout=subprocess.DEVNULL)
    recipe.update(link=link,sha256=hashlib.sha256((dest/'probe').read_bytes()).hexdigest())
    count.save(count.OUT/(arm+'-'+ns+'-build.json'),recipe)
    cases += [(arm,ns,shape,'2s',n,1,-1) for shape,n in [('EXEC-single',1),('EXEC-cross',4)]]
with concurrent.futures.ThreadPoolExecutor(16) as pool: results=list(pool.map(count.trace,cases))
count.save(count.ROOT/'docs/wave8b/budgets-helpers/counts.json',results)
