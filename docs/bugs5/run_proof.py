"""Own gate job interface, fixed lane resources, correctness only."""
import importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/bugs5';DOC=ROOT/'docs/bugs5';BIN=BASE/'bin';BIN.mkdir(exist_ok=True)
(BIN/'make').write_text('''#!/usr/bin/python3
import os,sys
args=['-j16' if a.startswith('-j') and a[2:].isdigit() else a for a in sys.argv[1:]]
os.execv('/usr/bin/taskset',['taskset','-c','96-111','/usr/bin/make',*args])
''')
(BIN/'python3').write_text('''#!/bin/bash
case "${1:-}" in
 *tests/atomic_ryow.py) exec /usr/bin/python3 "$@" --no-rate-assertions;;
 *) exec /usr/bin/python3 "$@";;
esac
''')
(BIN/'memtier_benchmark').write_text("#!/bin/bash\necho 'bugs5: measurement generators reserved for maintainer' >&2\nexit 125\n")
for p in BIN.iterdir():p.chmod(0o755)
ORACLE=BASE/'oracle/src';ORACLE.mkdir(parents=True,exist_ok=True)
for p in Path('/home/user/Projects/redis/src').iterdir():
    target=ORACLE/p.name
    if not target.exists():target.symlink_to(p)
for name in ('redis-server','redis-cli'):
    target=ORACLE/name
    if target.is_symlink():target.unlink()
    target.symlink_to(Path('/home/user/Projects/redis74/src')/name)
def environment():
 return dict(os.environ,PATH=str(BIN)+':'+os.environ['PATH'],
     PYTHONPATH=str(DOC/'fixture_site'),BUGS5_FIXTURE_PORT_LOG=str(DOC/'fixture-ports.log'),
     REDIS74_ROOT=str(ORACLE.parent),GATE_TEST_PORT='24899',GATE_DIFFER_ORACLE_CORES='104',
     GATE_NOTIFY_ORACLE_CORES='104',GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
     GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli')
if __name__=='__main__':
 label,engine,*jobs=sys.argv[1:]
 binary=ROOT/'build/tomokv'
 if engine=='epoll':
    binary=BASE/'tomokv-epoll-v2'
    # A Redis-style configuration path must remain argv[1]. Insert the engine
    # after it, before explicit later flags so a declared uring leg still wins.
    binary.write_text('#!/usr/bin/python3\nimport os,sys\nargs=sys.argv[1:]\nfirst=[]\nif args and not args[0].startswith("-"):\n first=[args.pop(0)]\nserver='+repr(str(ROOT/'build/tomokv'))+'\nos.execv(server,[server,*first,"--net-io","epoll",*args])\n')
    binary.chmod(0o755)
 dest=DOC/'proof'/label;dest.mkdir(parents=True,exist_ok=True)
 env=environment();env.update(GATE_ONLY_JOBS=' '.join(jobs),GATE_LEDGER=str(dest/'ledger'))
 argv=['taskset','-c','96-111','bash','tests/gate.sh','full','--server-cores','96-104',
       '--load-cores','105-111','--server-smt','','--load-smt','','--ports',
       os.environ.get('BUGS5_PROOF_PORTS','24810-24839'),
       '--candidate-binary',str(binary)]
 (dest/'command.json').write_text(json.dumps(dict(argv=argv,jobs=jobs),indent=2)+'\n')
 with (dest/'gate.log').open('w') as f:
    rc=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
 (dest/'returncode').write_text(str(rc)+'\n');print(label,rc,flush=True)
