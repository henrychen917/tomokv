#!/usr/bin/env python3
"""Isolate the four scriptfix2 production commits on the landed PRE geometry.

Only scripting/functions objects change; link order and all other PRE objects
are fixed. Reverse patches preserve unrelated fixes already on the headline.
"""
import json, os, shutil, subprocess
from pathlib import Path
from scriptfix3_counts import ROOT,BUILD,DOC,sha,save
COMMITS=['370210cfc','18191bcc1','6bc147d2c','cdd2c4673']
FILES=['src/cmd/scripting.cc','src/cmd/scripting.h','src/cmd/functions.cc']
def main():
 assert os.sched_getaffinity(0)<=set(range(32,48));os.environ['LC_ALL']='C'
 for stage in range(4):
  label='scriptfix2-stage'+str(stage);source=BUILD/(label+'-source');objects=source/'build'
  if not source.exists():
   shutil.copytree(BUILD/'pre-source',source)
   for commit in reversed(COMMITS[stage:]):
    patch=subprocess.check_output(['git','diff',commit+'^',commit,'--',*FILES],cwd=ROOT)
    result=subprocess.run(['patch','-p1','-R','--batch'],cwd=source,input=patch)
    if result.returncode:
     reject=source/'src/cmd/functions.cc.rej'
     assert commit=='370210cfc' and reject.exists()
     text=reject.read_text()
     assert sum(line.startswith('@@ ') for line in text.splitlines())==2 and 'function_list' in text and 'cmd_function' in text
     # Later autharity edits overlap two cold LIST/LOAD diagnostic hunks.
     # Keep those post-integration cold guards identical in all control arms.
     save(DOC/label/'retained-cold-conflicts.json',dict(commit=commit,reject=text,reason='Later autharity LIST/LOAD diagnostics, outside all warm scopes'))
     reject.unlink()
  for before in (BUILD/'pre').rglob('*.o'):
   rel=before.relative_to(BUILD/'pre');target=objects/rel;target.parent.mkdir(parents=True,exist_ok=True)
   if not target.exists() and rel.as_posix() not in ('src/cmd/scripting.o','src/cmd/functions.o','db0/src/cmd/scripting.o','db0/src/cmd/functions.o'):target.symlink_to(before)
  targets=[str(objects/path) for path in ('src/cmd/scripting.o','src/cmd/functions.o','db0/src/cmd/scripting.o','db0/src/cmd/functions.o')]
  with (BUILD/(label+'-build.log')).open('w') as log:
   subprocess.run(['make','BUILD_ROOT='+str(objects),'-j16',*targets],cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
   # Use the PRE production link receipt. Only the four isolated objects differ.
   receipt=json.loads((DOC/'pre/normal-build.json').read_text());link=receipt['link']
   link=[str(objects/Path(a).relative_to(BUILD/'pre')) if a.startswith(str(BUILD/'pre')+'/') else a for a in link]
   link=[a for a in link if not a.endswith('/probe.o')]
   link=[str(objects/'db0/src/main.o') if a.endswith('/original-main.o') else a for a in link]
   link[link.index('-o')+1]=str(objects/'tomokv')
   subprocess.run(link,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
  save(DOC/label/'control.json',dict(included_commits=COMMITS[:stage],removed_commits=COMMITS[stage:],source_sha256={f:sha(source/f) for f in FILES},binary_sha256=sha(objects/'tomokv'),other_objects='symlinks to unchanged e2b237926 PRE objects',link=link))
  with (BUILD/(label+'-counts.log')).open('w') as log:
   subprocess.run(['python3','tools/scriptfix3_counts.py',label,'--source',str(source),'--objects',str(objects),'--only','EVAL-single,EVAL-cross,EVALSHA-single,EVALSHA-cross,FCALL-single,FCALL-cross'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
if __name__=='__main__':main()
