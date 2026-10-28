#!/usr/bin/env python3
"""Build cumulative, source-identified exec1s arms; no server or measurement."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/exec1s'
EVIDENCE=ROOT/'build/exec1s-evidence'
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    commits={}
    for row in subprocess.check_output(['git','log','--format=%H %s','83e0b809d..HEAD'],cwd=ROOT,text=True).splitlines():
        digest,title=row.split(' ',1)
        if title.startswith('exec1s X'):commits[title.split(':',1)[0].split()[-1]]=digest
    receipts=[]
    for arm in ('X0','X1','X2','X3','X4'):
        source=OUT/(arm.lower()+'-current-source'); stamp=source/'exec1s-source-sha'
        if source.exists():
            assert stamp.exists(), 'source snapshot must identify its commit'
            previous_commit=stamp.read_text().strip()
            if previous_commit!=commits[arm]:
                source.rename(OUT/(arm.lower()+'-source-'+previous_commit[:12]))
        if not source.exists():
            source.mkdir()
            archive=source/'source.tar'
            with archive.open('wb') as stream:subprocess.run(['git','archive',commits[arm]],cwd=ROOT,stdout=stream,check=True)
            subprocess.run(['tar','-xf',str(archive),'-C',str(source)],check=True);archive.unlink()
            stamp.write_text(commits[arm]+'\n')
        cmd=['make','-C',str(source),'-j16','all']
        if arm=='X4':cmd+=['CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_EXEC1S_WB']
        with (EVIDENCE/(arm+'-isolated-build.log')).open('w') as stream:
            subprocess.run(['python3','tests/r7shadow_sync.py'],cwd=source,
                           stdout=stream,stderr=subprocess.STDOUT,check=True)
            subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,check=True)
        binary=ROOT/'build'/('exec1s-'+arm)
        if binary.exists() and sha(binary)!=sha(source/'build/tomokv'):
            previous=OUT/(arm+'-'+sha(binary)[:12])
            if not previous.exists():shutil.copy2(binary,previous)
        shutil.copy2(source/'build/tomokv',binary)
        row=dict(arm=arm,source_commit=commits[arm],source=str(source),binary=str(binary),sha256=sha(binary),command=cmd)
        receipts.append(row)
        (EVIDENCE/'isolated-arms.json').write_text(json.dumps(receipts,indent=2)+'\n')
        print(arm,row['sha256'],flush=True)
if __name__=='__main__':main()
