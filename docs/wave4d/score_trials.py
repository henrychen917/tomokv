from concurrent.futures import ProcessPoolExecutor
import difflib,gzip,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'docs/wave4'))
import identity
from target_bodies import bodies
DOC=ROOT/'docs/wave4d';OUT=ROOT/'build/wave4d/trials'
with gzip.open(DOC/'call-sites.json.gz','rt') as f:refs=json.load(f)
names=set(refs['headline']['groups'])
# Include all group-read lambda and completion instantiations, even where not residual.
with gzip.open(ROOT/'docs/wave4/identity/all-bodies.json.gz','rt') as f:
 names|={r['name'] for r in json.load(f) if 'xshard_execute(' in r['name'] or 'xshard_complete' in r['name']}

def score(label):
    records=[r for r in json.load(open(DOC/'source-trials.json')) if r['label']==label]
    command=shlex.split(next(s for s in reversed((ROOT/'build/wave4/build-rebuilt.log').read_text().splitlines()) if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    for r in records:command[command.index('build/'+r['object'])]=r['output']
    binary=OUT/label/'tomokv';command[command.index('-o')+1]=str(binary)
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    data=bodies(binary,names)
    with gzip.open(OUT/label/'bodies.json.gz','wt') as f:json.dump(data,f)
    diffs=[]
    for name,bs in data.items():
        if name not in refs['moverfix']['groups']:continue
        for arm in ('headline','moverfix','merged'):
            old=refs[arm]['groups'][name]
            lines=lambda v:[a+' | '+b for body in v for a,b in zip(body['ins'],body['encodings'])]
            equal=lines(old)==lines(bs)
            diffs.append(dict(name=name,reference=arm,equal=equal,
                              sizes=[[b['size'] for b in old],[b['size'] for b in bs]],
                              diff='' if equal else '\n'.join(difflib.unified_diff(lines(old),lines(bs)))))
    with gzip.open(DOC/(label+'-diffs.json.gz'),'wt') as f:json.dump(diffs,f,indent=2)
    print(label,[(r['name'].split('(')[0],r['sizes'],r['equal']) for r in diffs if r['reference']=='moverfix'],flush=True)
    return dict(label=label,command=command,sha256=identity.audit.digest(binary),comparisons=[{k:v for k,v in r.items() if k!='diff'} for r in diffs])
if __name__=='__main__':
    labels=sys.argv[1:] or list(dict.fromkeys(r['label'] for r in json.load(open(DOC/'source-trials.json'))))
    with ProcessPoolExecutor(max_workers=4) as pool:rows=list(pool.map(score,labels))
    destination=DOC/'source-trial-scores.json'
    old=json.loads(destination.read_text()) if destination.exists() else []
    rows=[r for r in old if r['label'] not in labels]+rows
    destination.write_text(json.dumps(rows,indent=2)+'\n')
