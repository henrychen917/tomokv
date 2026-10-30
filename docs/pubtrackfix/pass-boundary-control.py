#!/usr/bin/env python3
"""Serverless negative control for the final BCAST drain ordering."""
import hashlib,json,os,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'build/pubtrackfix/pass-boundary-control'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assert os.sched_getaffinity(0)<=set(range(32,48))
 overlay=OUT/'overlay';(overlay/'src').mkdir(parents=True,exist_ok=True)
 for source in (ROOT/'src').rglob('*'):
  dest=overlay/source.relative_to(ROOT)
  if source.is_dir():dest.mkdir(exist_ok=True)
  elif not dest.exists():dest.symlink_to(source)
 old=overlay/'src/core/pubsub.inc';old.unlink()
 old.write_bytes(subprocess.check_output(['git','show','fbb510875:src/core/pubsub.inc'],cwd=ROOT))
 obj=OUT/'netcmd_unit.o';binary=OUT/'netcmd-unit-broken'
 compile=['g++','-std=c++20','-O2','-g','-Wall','-Wextra','-march=native','-pthread','-DTOMO_JEMALLOC',
  '-Wno-mismatched-new-delete','-I'+str(overlay),'-I.','-c','tests/netcmd_unit.cc','-o',str(obj)]
 recipe=subprocess.check_output(['make','-n','-W','build/tests/netcmd_unit.o','build/netcmd-unit'],cwd=ROOT,text=True)
 link=shlex.split(next(s for s in recipe.splitlines() if ' -o build/netcmd-unit ' in s))
 link[link.index('build/tests/netcmd_unit.o')]=str(obj);link[link.index('-o')+1]=str(binary)
 with (OUT/'build.log').open('w') as f:
  subprocess.run(compile,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
  subprocess.run(link,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
 rows=[]
 for label,b in [('POST',ROOT/'build/netcmd-unit'),('EARLY-FLUSH',binary)]:
  r=subprocess.run([str(b),'pubsub'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  rows.append(dict(arm=label,sha256=sha(b),returncode=r.returncode,output=r.stdout))
 assert rows[0]['returncode']==0 and rows[1]['returncode']!=0
 assert 'pass drained every newly enrolled BCAST key' in rows[1]['output'],rows
 (ROOT/'docs/pubtrackfix/pass-boundary-control.json').write_text(json.dumps(dict(compile=compile,link=link,
  changed_header_sha256=sha(old),rows=rows),indent=2)+'\n')
 print(json.dumps(rows,indent=2),flush=True)
if __name__=='__main__':main()
