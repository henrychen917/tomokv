"""Five isolated fresh batteries after the broad run's unproved redirect-flag miss."""
import hashlib, importlib.util, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/trackfix'))
from run_proof import environment
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
arm=sys.argv[1] if len(sys.argv)>1 else 'POST'
label='tracking-battery-recheck'+('-'+arm if arm!='POST' else '')
support.ROOT=ROOT;support.OUT=ROOT/'build/trackfix'/label
dest=ROOT/'docs/trackfix/trackfix2'/label;dest.mkdir(parents=True,exist_ok=False)
binary=ROOT/({'PRE':'build/tomokv-PRE','TRACE':'build/trackfix/redirect-trace/tomokv'}.get(arm,'build/tomokv'));shape=['--shards','16','--thread-mode','1s','--read-local','1','--net-io','epoll','--atomic','1','--enable-debug-command','yes']
rows=[]
for roll in range(1,6):
    argv=['taskset','-c','105-111','python3','tests/tracking.py','127.0.0.1','22800']
    with support.owned(str(roll),binary,'96-103',22800,shape):
        with (dest/(str(roll)+'.log')).open('w') as f:rc=subprocess.run(argv,cwd=ROOT,env=environment(),stdout=f,stderr=subprocess.STDOUT).returncode
    rows.append(dict(roll=roll,argv=argv,returncode=rc,sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
    (dest/'results.json').write_text(json.dumps(rows,indent=2)+'\n');print(roll,rc,flush=True)
