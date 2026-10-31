import json, os, re, subprocess, sys, time
from pathlib import Path
root=Path.cwd()
sys.path.insert(0,str(root/'tests'))
import differ_fanout
out=root/'build/flipfix6'
receipt=root/'docs/flipfix6/remaining-proof.json'
(out/'tmp').mkdir(exist_ok=True)
base={**os.environ,'LC_ALL':'C','GATE_PROOF_NO_RATES':'1','TMPDIR':str(out/'tmp')}
gate=['taskset','-c','32-47','tests/gate.sh']
geometry=['--server-cores','32-39','--load-cores','40-47','--load-smt','','--ports','20300-20399']
phases=[]
def gate_phase(name,jobs,engine='uring',fused='0',tier='quick'):
    phases.append((name,gate+[tier]+geometry,{'GATE_ONLY_JOBS':jobs,'GATE_NET_IO':engine,'GATE_DIFFER_NET_IO':engine,'GATE_TXN_FUSED':fused,'GATE_DIFFER_ORACLE_CORES':'40-47'},0))
gate_phase('gate-regression-epoll','flip flipctl lb-stationary-1s lb-stationary-2s debug-0 debug-1 txn_group_fused txn_group_split txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 atomic_batteries multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1 multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1 tls feature-split-0 feature-split-1 feature-armed-0 feature-armed-1','epoll')
for engine in ('uring','epoll'):
    gate_phase('gate-fused-'+engine,'debug-0 debug-1 atomic_batteries fused-0 fused-1',engine,'1')
for engine in ('uring','epoll'):
    gate_phase('gate-differ-'+engine,'differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence',engine,tier='full')
for arm,expected,engines,atomics,databases,rc in [('PAD-A','pre',['uring','epoll'],['0','1'],['1','16'],0),('PRE','post',['uring'],['0'],['1'],1)]:
    name='negative-'+arm
    cmd=['taskset','-c','40-47','python3','tests/flipfix6.py','--binary',str(out/arm),'--cores','32-39','--port','20300','--output',str(out/name),'--expect',expected,'--cases','exec','--engines',*engines,'--atomics',*atomics,'--databases',*databases]
    phases.append((name,cmd,{},rc))
phases.append(('gates-selftest',['taskset','-c','32-47','python3','tests/gates_test.py'],{'GATE_TEST_PORT':'20390'},0))
results=[]
for name,cmd,env,expected in phases:
    print('START',name,flush=True)
    record={'name':name,'argv':cmd,'environment':{'LC_ALL':'C','GATE_PROOF_NO_RATES':'1',**env},'start':time.time(),'expected_exit':expected}
    results.append(record);receipt.write_text(json.dumps(results,indent=2)+'\n')
    with (out/(name+'.log')).open('w') as log:
        proc=subprocess.run(cmd,env={**base,**env},stdout=log,stderr=subprocess.STDOUT)
    record.update(exit=proc.returncode,seconds=time.time()-record['start'],passed=proc.returncode==expected)
    if name.startswith('gate-differ-') and record['passed']:
        directory=Path(re.search(r'artifacts: (.+)',(out/(name+'.log')).read_text()).group(1))
        try:
            plan=differ_fanout.load_plan(directory/'differ-plan.json')
            record['folds']=[differ_fanout.fold(plan,group,directory) for group in ('split','armed')]
        except Exception as error:
            record['fold_error']=str(error);record['passed']=False
    if name=='negative-PRE':
        paths=list((out/name).glob('*/witness.json'))
        if len(paths)==1:
            witness=json.loads(paths[0].read_text())
            record['deadline_witness']=any(row['reply'].startswith('ERR FLIP') and row['seconds']>=4.5 for row in witness['flips']) and witness['ping_max']>=4
        else: record['deadline_witness']=False
        record['passed'] &= record['deadline_witness']
    receipt.write_text(json.dumps(results,indent=2)+'\n')
    print('END',name,record['exit'],round(record['seconds'],3),'pass='+str(record['passed']),flush=True)
raise SystemExit(0 if all(row['passed'] for row in results) else 1)
