"""Fresh-state, unchanged climon seed 19 controls; owned CPUs and ports only."""
import importlib.util, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT
support.OUT=ROOT/'build/bugs5/tracking-controls'
DOC=ROOT/'docs/bugs5/tracking-controls';DOC.mkdir(parents=True,exist_ok=True)
rows=[]
for arm in ('PRE','HEADLINE'):
    binary=ROOT/f'build/tomokv-{arm}'
    for roll in range(1,11):
        label=f'{arm}-{roll}'
        shape=['--shards','16','--thread-mode','fused','--read-local','1',
               '--net-io','epoll','--databases','16','--atomic','0']
        with support.owned(label+'-oracle',Path('/home/user/Projects/redis74/src/redis-server'),'104',24801,[]):
            with support.owned(label+'-target',binary,'96-103',24800,shape):
                argv=['taskset','-c','105-111','python3','tests/differ.py',
                      '127.0.0.1','24800','127.0.0.1','24801','climon','19']
                env=dict(os.environ,PYTHONPATH=str(DOC.parent/'fixture_site'),
                         BUGS5_FIXTURE_PORT_LOG=str(DOC/'fixture-ports.log'))
                with (DOC/f'{label}.log').open('w') as log:
                    result=subprocess.run(argv,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                rows.append(dict(arm=arm,roll=roll,argv=argv,returncode=result.returncode))
                (DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
                print(label,result.returncode,flush=True)
