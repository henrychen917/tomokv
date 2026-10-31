#!/usr/bin/env python3
"""Save each independently measurable release and its exact source/object inputs."""
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(); p.add_argument('arm', choices=['B', 'C1', 'C2', 'FULL']); args=p.parse_args()
base=root/'build/execfifo'; dest=base/(args.arm+'-source')
assert not dest.exists(), f'refuse to overwrite frozen arm {dest}'
subprocess.run(['make', '-q', 'all'], cwd=root, check=True)
dest.mkdir(); (dest/'build').mkdir()
archive=subprocess.Popen(['git','archive','HEAD','Makefile','src','tests','tools','third_party'],cwd=root,stdout=subprocess.PIPE)
subprocess.run(['tar','-x','-C',str(dest)],stdin=archive.stdout,check=True)
assert archive.wait()==0
for name in ('src','db0'):
    subprocess.run(['cp','-a','--reflink=auto',str(root/'build'/name),str(dest/'build'/name)],check=True)
shutil.copy2(root/'build/tomokv',dest/'build/tomokv')
name={'B':'POST-B','C1':'POST-B+C1','C2':'POST-B+C1+C2','FULL':'POST-FULL'}[args.arm]
shutil.copy2(root/'build/tomokv',base/name)
record={'arm':name,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        'path':str(base/name),'sha256':hashlib.sha256((base/name).read_bytes()).hexdigest(),
        'source':str(dest)}
(root/'docs/execfifo'/('artifact-'+args.arm+'.json')).write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
