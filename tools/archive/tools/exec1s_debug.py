#!/usr/bin/env python3
"""Build visit-counter instruments. These are not release rate arms."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    rows=[]
    for arm in ['X1','X2','POST']:
        source=ROOT if arm=='POST' else ROOT/'build/exec1s'/(arm.lower()+'-current-source')
        objects=ROOT/'build/exec1s'/(arm.lower()+'-visits-build')
        flags='-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_EXEC1S_DEBUG'
        cmd=['make','-C',str(source),'BUILD_ROOT='+str(objects),'-j16','all','CXXFLAGS='+flags]
        with (ROOT/'build/exec1s-evidence'/(arm+'-visits-build.log')).open('w') as log:
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        binary=ROOT/'build'/('exec1s-'+arm+'-visits')
        if binary.exists():
            with binary.open('rb') as f:old=hashlib.file_digest(f,'sha256').hexdigest()
            archived=ROOT/'build/exec1s'/(binary.name+'-'+old[:12])
            if not archived.exists():shutil.copy2(binary,archived)
        shutil.copy2(objects/'tomokv',binary)
        with binary.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        rows.append(dict(instrument=arm,command=cmd,binary=str(binary),sha256=digest,kind='DEBUG visit observation only; not a release rate or ordinary-command instruction arm'))
        (ROOT/'docs/exec1s/visit-instruments.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(arm,digest,flush=True)
if __name__=='__main__':main()
