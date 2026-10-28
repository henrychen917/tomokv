#!/usr/bin/env python3
"""Throwaway km-to-mile regression in merged objects; production source stays intact."""
from pathlib import Path
import hashlib, json, shlex, subprocess
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/wave9/planted';OUT.mkdir(parents=True,exist_ok=True)
source=ROOT/'src/cmd/geo.cc';s=source.read_text()
old='else if (input.eq_icase("km")) meters = 1000.0;'
new='else if (input.eq_icase("km")) meters = 1609.34;'
assert s.count(old)==1
copy=OUT/'geo.cc';copy.write_text(s.replace(old,new))
recipes=subprocess.check_output(['make','-Bn','all'],cwd=ROOT,text=True).replace('\\\n',' ')
commands=[]; replacements={}
for prefix in ('src','db0/src'):
    target='build/'+prefix+'/cmd/geo.o'
    command=shlex.split(next(l for l in recipes.splitlines() if l.startswith('g++ ') and l.endswith(' -o '+target)))
    obj=OUT/(prefix.replace('/','_')+'-geo.o')
    command[command.index('src/cmd/geo.cc')]=str(copy)
    command[command.index('-o')+1]=str(obj)
    command+=['-I'+str(ROOT/'src/cmd')]
    subprocess.run(command,cwd=ROOT,check=True)
    commands.append(command);replacements[target]=str(obj)
link=shlex.split(next(l for l in recipes.splitlines() if ' -Wl,--wrap=main ' in l))
link=[replacements.get(x,x) for x in link]
binary=OUT/'tomokv';link[link.index('-o')+1]=str(binary)
subprocess.run(link,cwd=ROOT,check=True);commands.append(link)
receipt=dict(change=dict(file=str(source.relative_to(ROOT)),before=old,after=new),commands=commands,
    merged_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),
    planted_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
(ROOT/'docs/wave9/geo-regression.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
