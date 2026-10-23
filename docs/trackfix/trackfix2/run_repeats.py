"""Twenty fresh seed-19 correctness boots; no rate claims or performance tools."""
from concurrent.futures import ThreadPoolExecutor
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'docs/trackfix'))
from run_proof import environment, ORACLE
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT
arm=sys.argv[1]
DEST=ROOT/'docs/trackfix/trackfix2'/('repeats-'+arm)
DEST.mkdir(parents=True,exist_ok=False)
support.OUT=ROOT/'build/trackfix/trackfix2-repeats'/arm
binary=ROOT/('build/tomokv-PRE' if arm=='PRE' else 'build/tomokv')
digest=hashlib.sha256(binary.read_bytes()).hexdigest()
env=environment()
def worker(index):
    rows=[]
    port=22870+index*2
    for roll in range(index*5+1,index*5+6):
        label=f'{arm}-{roll}'
        shape=['--shards','16','--thread-mode','fused','--read-local','1',
               '--net-io','epoll','--databases','16','--atomic','0']
        with support.owned(label+'-oracle',ORACLE,'104',port+1,[]):
            with support.owned(label+'-target',binary,'96-103',port,shape):
                argv=['taskset','-c','105-111','python3','tests/differ.py',
                      '127.0.0.1',str(port),'127.0.0.1',str(port+1),'climon','19']
                log=DEST/(label+'.log')
                with log.open('w') as out:
                    rc=subprocess.run(argv,cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT).returncode
                duplicates=sum(line.startswith('    target:') and line.count('invalidate')>1
                               for line in log.read_text().splitlines())
                row=dict(arm=arm,roll=roll,argv=argv,returncode=rc,
                         duplicate_comparisons=duplicates,sha256=digest)
                (DEST/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
                rows.append(row);print(label,rc,duplicates,flush=True)
    return rows
with ThreadPoolExecutor(max_workers=4) as pool:
    rows=sum(pool.map(worker,range(4)),[])
(DEST/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
