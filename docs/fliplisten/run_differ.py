"""Standard seed corpus, unchanged suites, both engines and both geometries."""
from concurrent.futures import ThreadPoolExecutor
import json,subprocess
from pathlib import Path
from run_proof import ROOT,BASE,DOC,environment
OUT=BASE/'differ';OUT.mkdir(exist_ok=True)
def run(item):
 index,engine,geometry=item;name=engine+'-'+geometry
 dest=DOC/'differ'/name;dest.mkdir(parents=True,exist_ok=True)
 wrapper=OUT/name;wrapper.write_text('#!/bin/bash\nexec '+str(ROOT/'build/tomokv')+' --net-io '+engine+' "$@"\n');wrapper.chmod(0o755)
 env=environment();env.update(GATE_DIFFER_OUT=str(OUT/(name+'-results')),GATE_DIFFER_GEOMETRY=geometry,
                             GATE_LOAD_CORES='56-63',GATE_RUN_ID='fliplisten-standard')
 argv=['taskset','-c','56-63','bash','tests/differ_gate.sh',str(wrapper),str(21850+index*2),str(21851+index*2),'48-55','6:2']
 (dest/'command.json').write_text(json.dumps(dict(argv=argv,geometry=geometry,engine=engine),indent=2)+'\n')
 with (dest/'output.log').open('w') as f:rc=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
 result=dict(engine=engine,geometry=geometry,returncode=rc);(dest/'result.json').write_text(json.dumps(result)+'\n');print(result,flush=True)
 return result
if __name__=='__main__':
 specs=[(i,e,g) for i,(e,g) in enumerate((('uring','split'),('epoll','split'),('uring','armed-fused'),('epoll','armed-fused')))]
 with ThreadPoolExecutor(max_workers=1) as pool:results=list(pool.map(run,specs))
 (DOC/'differ/results.json').write_text(json.dumps(results,indent=2)+'\n')
