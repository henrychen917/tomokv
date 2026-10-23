"""Bounded trace replay; the statistical controls use the unmodified differ."""
import importlib.util,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT;support.OUT=ROOT/'build/bugs5/trace/runs'
DOC=ROOT/'docs/bugs5/trace';DOC.mkdir(exist_ok=True)
p=ROOT/'build/bugs5/trace/differ.py'
s=(ROOT/'tests/differ.py').read_text().replace('        mode = rng.randrange(5)\n','        mode = rng.randrange(5)\n        print("TRACE round", round_, "key", k, "mode", mode, flush=True)\n')
p.write_text(s)
rows=[]
for roll in range(1,11):
 label=f'trace-{roll}'
 with support.owned(label+'-oracle',Path('/home/user/Projects/redis74/src/redis-server'),'104',24843,[]):
  with support.owned(label+'-target',ROOT/'build/bugs5/trace/tomokv','96-103',24842,
       ['--shards','16','--thread-mode','fused','--read-local','1','--net-io','epoll','--atomic','0','--databases','16']):
   env=dict(os.environ,PYTHONPATH=str(ROOT/'tests')+':'+str(DOC.parent/'fixture_site'),BUGS5_FIXTURE_PORT_LOG=str(DOC/'fixture-ports.log'))
   with (DOC/f'{label}.log').open('w') as log:
    rc=subprocess.run(['taskset','-c','105-111','python3',str(p),'127.0.0.1','24842','127.0.0.1','24843','climon','19'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
   rows.append(dict(roll=roll,returncode=rc));print(rows[-1],flush=True)
 (DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
 if 'DIFF invalidation round 21 mode 1' in (DOC/f'{label}.log').read_text():break
