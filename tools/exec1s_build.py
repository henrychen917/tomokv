#!/usr/bin/env python3
"""Rebuild frozen arms serially; keep binaries/probes, remove source/object trees.

POST must be built first. PRE additionally constructs the exact common-image
PAD-A pair while its objects exist. No server or performance workload is run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import exec1s_scope as scope

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/exec1s'
EVIDENCE=ROOT/'build/exec1s-evidence'
DOCS=ROOT/'docs/exec1s'
COMMITS=dict(PRE='83e0b809d',X1='f893d7432',X2='96624237a',X3='2022b5374',
             X4='a8829929a',X5='6e1a805ed',POST='bd90f09de')

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def record(arm,binary,**extra):
    manifest=EVIDENCE/'rebuilt-arms.json'
    rows=json.loads(manifest.read_text()) if manifest.exists() else []
    rows=[r for r in rows if r['arm']!=arm]
    row=dict(arm=arm,binary=str(binary),sha256=sha(binary),bytes=binary.stat().st_size,**extra)
    rows.append(row)
    scope.save(manifest,rows);scope.save(DOCS/'arms.json',rows)
    (DOCS/'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {Path(r['binary']).relative_to(ROOT)}\n" for r in rows))
    print('BUILT',arm,row['sha256'],flush=True)

def probes(arm,source):
    selected=[]
    if arm in ('PRE','POST'):selected.append((arm,'txnorder_command_scope.cc'))
    if arm in ('PRE','POST','X3','X4','X5'):selected.append(('IO-'+arm,'exec1s_io_scope.cc'))
    if arm in ('PRE','POST','X1','X2'):selected.append(('OWNER-'+arm,'exec1s_owner_scope.cc'))
    if arm in ('PRE','X1','X2','X3'):selected.append(('IDLE-'+arm,'exec1s_idle_scope.cc'))
    for label,fixture in selected:
        scope.ARMS[label]=(source,source/'build');scope.FIXTURE=ROOT/'tests'/fixture
        for ns in ('normal','db0'):
            scope.build(label,ns)
            if not label.startswith('IDLE-'):
                cmd=['GET','1s','1','1','-1'] if label==arm else ['EXEC','1s','1','1','-1']
                subprocess.run([str(scope.BUILD/(label+'-'+ns)/'probe'),*cmd],check=True,
                               stdout=subprocess.DEVNULL)
    scope.FIXTURE=ROOT/'tests/txnorder_command_scope.cc'

def main():
    assert os.sched_getaffinity(0)<=set(range(48,64)), 'taskset -c 48-63 required'
    p=argparse.ArgumentParser();p.add_argument('--arms',default='POST,PRE,X1,X2,X3,X4,X5')
    p.add_argument('--keep-source',action='store_true');p.add_argument('--skip-probes',action='store_true')
    a=p.parse_args();OUT.mkdir(parents=True,exist_ok=True);EVIDENCE.mkdir(parents=True,exist_ok=True)
    for arm in a.arms.split(','):
        commit=git('rev-parse',COMMITS[arm])
        source=ROOT if arm=='POST' else OUT/('pre-source' if arm=='PRE' else arm.lower()+'-current-source')
        if source!=ROOT:
            stamp=source/'exec1s-source-sha'
            if source.exists():assert stamp.read_text().strip()==commit
            else:
                source.mkdir()
                with subprocess.Popen(['git','archive',commit],cwd=ROOT,stdout=subprocess.PIPE) as proc:
                    with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:archive.extractall(source,filter='data')
                    assert proc.wait()==0
                stamp.write_text(commit+'\n')
        cmd=['make','-C',str(source),'-j16','all']
        if arm=='X4':cmd+=['CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_EXEC1S_WB']
        with (EVIDENCE/(arm+'-isolated-build.log')).open('w') as log:
            subprocess.run(['python3','tests/r7shadow_sync.py'],cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        binary=ROOT/'build'/('exec1s-'+arm)
        shutil.copy2(source/'build/tomokv',binary)
        record(arm,binary,source_commit=commit,production_source_tree=git('rev-parse',commit+':src'),
               makefile_blob=git('rev-parse',commit+':Makefile'),command=cmd,
               build_macro='TOMO_EXEC1S_WB' if arm=='X4' else '',source_snapshot=str(source))
        if arm=='POST':shutil.copy2(binary,ROOT/'build/exec1s-POST-release')
        if not a.skip_probes:probes(arm,source)
        if arm=='PRE' and not a.skip_probes:
            subprocess.run(['python3','tools/exec1s_aux.py','--allocations'],cwd=ROOT,check=True)
            subprocess.run(['python3','tools/exec1s_pad.py'],cwd=ROOT,check=True)
            subprocess.run(['python3','tools/exec1s_pad_scope.py'],cwd=ROOT,check=True)
            for twin in ('POST-layout','PAD-A'):
                dest=ROOT/'build'/('exec1s-'+twin);shutil.move(OUT/twin,dest)
                record(twin,dest,control='A: PRE behaviour / POST behaviour in the same common image; larger than release',
                       source_commit=commit if twin=='PAD-A' else git('rev-parse',COMMITS['POST']))
            control=json.loads((DOCS/'pad-a.json').read_text())
            control['post_layout']=str(ROOT/'build/exec1s-POST-layout')
            control['pad_a']=str(ROOT/'build/exec1s-PAD-A')
            scope.save(DOCS/'pad-a.json',control)
            for allocation in OUT.glob('*-allocation-*'):
                if allocation.is_file():allocation.unlink()
            shutil.rmtree(OUT/'pad-objects')
            for ns in ('normal','db0'):
                shutil.rmtree(scope.BUILD/('POST-layout-'+ns))
                (scope.BUILD/('PAD-A-'+ns)/'post-layout-probe').unlink()
        if source!=ROOT and not a.keep_source:shutil.rmtree(source)

if __name__=='__main__':main()
