#!/usr/bin/env python3
"""Build instrumented PRE/POST registry-visit servers; never execute workloads."""
import concurrent.futures,hashlib,json,shlex,subprocess
from pathlib import Path
from execindex_pad import recipe
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/execindex'
PRE_SOURCE=OUT/'pre-debug-source';PRE_SOURCE.mkdir(exist_ok=True)
archive=subprocess.check_output(['git','archive','3a4a32ed2','src','Makefile'],cwd=ROOT)
subprocess.run(['tar','-x','-C',str(PRE_SOURCE)],input=archive,check=True)
receipts=[]
for arm,source,objects in [('PRE-visits',PRE_SOURCE,OUT/'pre-source/build'),('POST-visits',ROOT,ROOT/'build')]:
    dest=OUT/(arm+'-objects');dest.mkdir(exist_ok=True)
    recipes=subprocess.check_output(['make','-n','-W','Makefile','all'],cwd=source,text=True).replace('\\\n',' ')
    commands={}
    for line in recipes.splitlines():
        if line.startswith('g++ '):
            cmd=shlex.split(line)
            if '-c' in cmd:commands[cmd[cmd.index('-o')+1].removeprefix('build/')]=cmd
    units=[prefix+'cmd/'+name+'.o' for prefix in ['src/','db0/src/'] for name in ['xshard','t_server']]
    def compile_one(unit):
        cmd=commands[unit].copy();out=dest/unit;out.parent.mkdir(exist_ok=True,parents=True)
        cmd[cmd.index('-o')+1]=str(out);cmd+=['-DTOMO_TXNORDER_DEBUG']
        with (dest/(unit.replace('/','_')+'.log')).open('w') as log:subprocess.run(cmd,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
        return dict(unit=unit,command=cmd,sha256=hashlib.sha256(out.read_bytes()).hexdigest())
    with concurrent.futures.ThreadPoolExecutor(4) as pool:compiled=list(pool.map(compile_one,units))
    base=recipe(OUT/'pre-source' if arm=='PRE-visits' else ROOT,objects)
    base=[str(dest/x.relative_to(objects)) if isinstance(x,Path) and x.relative_to(objects).as_posix() in units else str(x) for x in [Path(v) if v.startswith(str(objects)+'/') and v.endswith('.o') else v for v in base]]
    binary=OUT/arm;base[base.index('-o')+1]=str(binary)
    with (dest/'link.log').open('w') as log:subprocess.run(base,stdout=log,stderr=subprocess.STDOUT,check=True)
    receipts.append(dict(arm=arm,source=str(source),source_commit='3a4a32ed2' if arm=='PRE-visits' else subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),objects=compiled,link=base,path=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
(ROOT/'docs/execindex/debug-artifacts.json').write_text(json.dumps(receipts,indent=2)+'\n')
