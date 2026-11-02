#!/usr/bin/env python3
"""Selected gate jobs on the assigned lane only. No iteration or rate tier."""
import argparse, json, os, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JOBS='''flip fliplisten flipctl flipfix5 flipfix6 lb-stationary-1s lb-stationary-2s moverfix
blockfix4 blockfix2 blockfix_structure blockfix_registry blockfix_mkstream
feature-split-0 feature-split-1 feature-armed-0 feature-armed-1
pubtrackfix notify notifycompat tracking_redirect trackorder notify_order notify_aof
trackfix_accounting trackfix_order tls netfix_tls
persistfix2_lastsave persistfix2_shutdown persistfix2_commands persistfix2_errors persistfix_units
snapshot-epoll snapshot-uring snapfix_shutdown snapfix_bgsave_script snapfix_bgsave_exec snapfix2_tables
aof-epoll aof-uring aof_frame aoforder persistfmt persistfmt_aof_error'''.split()
# Signal handling has its own ordinary boot job; keep it in each engine run.
JOBS += ['iofix-deferred', 'iofix-hz', 'iofix-sleep', 'iofix-signal',
         'rootcore-waitaof', 'serverfix_waitaof', 'climonfix', 'wait_units',
         'wb_rule_units', 'wbland_units', 'wb_policy', 'splitlocal_units',
         'reorder_sync', 'reorder_engagement', 'reorder_identity',
         'clientcompat-multi-tracking', 'clientcompat-enable-race']
JOBS += [f'climonfix4-{mode}-{engine}' for mode in ('1s', '2s') for engine in ('uring', 'epoll')]
NEW=['flipfix7_output','flipfix7_blocked','flipfix7_tls']
UNITS=['core_units','flipfix_units','flipfix5_units','flipfix6_units','flipfix7_units','lbplanner_units','persistfix_units','flip_unit']

def main():
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['new','regression','differ','units']);p.add_argument('--engine',choices=['uring','epoll'],default='uring');args=p.parse_args()
 jobs=NEW if args.phase=='new' else JOBS if args.phase=='regression' else ['differ-split','differ-armed'] if args.phase=='differ' else UNITS
 out=ROOT/'build/flipfix7';tag=f'gate-{args.phase}-{args.engine}'
 (out/(tag+'.exit.json')).unlink(missing_ok=True)
 env=dict(os.environ,LC_ALL='C',GATE_TEST_PORT='21097',GATE_ONLY_JOBS=' '.join(jobs),GATE_PROOF_NO_RATES='1',REDIS74_ROOT='/home/user/Projects/redis',PARBUILD_JOBS='13',GATE_NET_IO=args.engine,GATE_SHUTDOWN_NET_IO=args.engine,GATE_PROOF_NET_IO=args.engine,GATE_DIFFER_NET_IO=args.engine,GATE_DIFFER_ORACLE_CORES='56-57')
 cmd=['taskset','-c','48-60','tests/gate.sh','full' if args.phase=='differ' else 'quick','--server-cores','48-55','--load-cores','56-60','--ports','21000-21099','--candidate-binary',str(ROOT/'build/flipfix7/POST')]
 (out/(tag+'.argv.json')).write_text(json.dumps(dict(command=cmd,environment={k:v for k,v in env.items() if k.startswith('GATE_') or k in ('LC_ALL','REDIS74_ROOT','PARBUILD_JOBS')}),indent=2)+'\n')
 with (out/(tag+'.log')).open('w') as f:result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
 (out/(tag+'.exit.json')).write_text(json.dumps(dict(rc=result.returncode))+'\n')
 print(tag,result.returncode,flush=True)
 raise SystemExit(result.returncode)
if __name__=='__main__':main()
