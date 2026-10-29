#!/usr/bin/env python3
"""Map counted historical instruction sites to DWARF frames and source commits.

Blame is source provenance, not proof of the compiler's inlining decision. The
separate compile-boundary records establish integration/code-generation causes.
"""
import concurrent.futures, functools, gzip, hashlib, json, os, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOC=ROOT/'docs/rlfix4';INS=DOC/'instructions'
REVS={'anchor':'991d48f65','wave6':'05a5e01a9','wave7':'3700b51d7','pre':'a214652ec','preparse':'a214652ec'}
@functools.lru_cache(None)
def blame(rev,path):
 r=subprocess.run(['git','blame','--line-porcelain',rev,'--',path],cwd=ROOT,text=True,capture_output=True)
 if r.returncode:return {}
 result={};commit=None;line=None
 for s in r.stdout.splitlines():
  m=re.fullmatch(r'([0-9a-f]{40}) \d+ (\d+)(?: \d+)?',s)
  if m:commit,line=m[1],int(m[2])
  if s.startswith('\t') and line is not None:result[line]=commit
 return result
def one(case):
 arm,ns=case;binary=ROOT/f'build/rlfix4/commands/{arm}-{ns}/probe';sha=hashlib.sha256(binary.read_bytes()).hexdigest();cases={};sites=set()
 for f in INS.glob(f'{arm}-{ns}-GET-1s-*.json'):
  r=json.loads(f.read_text())
  if r.get('binary_sha256')!=sha or not any(f.name.endswith('-'+x+'.json') for x in ('local','mix','parse','parsemix','r7parse','r7mix')):continue
  with gzip.open(str(f)+'.sites.gz','rt') as g:counts=json.load(g)['sites']
  cases[f.name]=counts;sites.update(int(x,16) for x in counts)
 assert sites,(arm,ns)
 output=subprocess.check_output(['addr2line','-a','-f','-i','-e',str(binary)],input=''.join(hex(x)+'\n' for x in sorted(sites)),text=True)
 origins={};pc=None;name=None
 for s in output.splitlines():
  if re.fullmatch(r'0x[0-9a-f]+',s):pc=hex(int(s,16));origins[pc]=[];name=None;continue
  if name is None:name=s;continue
  m=re.match(r'(.+):(\d+|\?)(?: \(discriminator \d+\))?$',s);path=m[1] if m else s;line=int(m[2]) if m and m[2].isdigit() else 0
  for prefix in ('src/','third_party/','tests/'):
   needle='/'+prefix
   if needle in path:path=prefix+path.rsplit(needle,1)[1];break
  commit=blame(REVS[arm],path).get(line) if path.startswith(('src/','third_party/')) else None
  origins[pc].append(dict(function=name,path=path,line=line,source_commit=commit));name=None
 result=dict(arm=arm,namespace=ns,revision=REVS[arm],binary_sha256=sha,
             note='DWARF/source provenance; integration causes are recorded separately',cases=cases,origins=origins)
 folder=DOC/'source-sites';folder.mkdir(exist_ok=True)
 with gzip.GzipFile(filename=str(folder/f'{arm}-{ns}.json.gz'),mode='wb',mtime=0) as f:f.write(json.dumps(result).encode())
 print(arm,ns,len(sites),'instruction sites',flush=True)
if __name__=='__main__':
 os.sched_setaffinity(0,set(range(32,48)))
 with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(one,[(a,n) for a in REVS for n in ('normal','db0')]))
