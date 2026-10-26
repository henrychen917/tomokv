import json
import os
from pathlib import Path
import subprocess
import time

root=Path('/home/user/Projects/cx-iofix3')
os.chdir(root)
doc=root/'docs/iofix3'
while 'COMPLETE gate matrix' not in (doc/'matrix-sequence.log').read_text():
    time.sleep(2)
env=dict(os.environ,GATE_ONLY_JOBS='differ-split-1',GATE_NET_IO='epoll',
         GATE_DIFFER_NET_IO='epoll',GATE_TEST_PORT='48898')
argv=['python3','tools/iofix3_ports.py','--ports','48840-48842','--',
      'tests/gate.sh','full','--server-cores','64-71','--load-cores','72-79',
      '--load-smt','','--ports','48840-48842','--candidate-binary',
      str(root/'build/tomokv-iofix3-post2')]
row=dict(argv=argv,extra_env={k:v for k,v in env.items() if k.startswith('GATE_')},
         reason='Retain and recheck psfix atomic-1 seed 20 SAVE-after-idle failure; entire standard partition, no filters.',started=time.time())
with (doc/'post2-differ-epoll-split1-recheck.log').open('w') as log:
    result=subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT)
row.update(ended=time.time(),exit=result.returncode)
(doc/'differ-recheck-status.json').write_text(json.dumps(row,indent=2)+'\n')
print(json.dumps(row),flush=True)
