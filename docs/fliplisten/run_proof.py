"""Own gate job interface, fixed lane resources, correctness only."""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/fliplisten';DOC=ROOT/'docs/fliplisten';BIN=BASE/'bin';BIN.mkdir(exist_ok=True)
def executable(path,body):
 if path.exists() and path.read_text()==body:return
 with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as f:
  f.write(body);temporary=Path(f.name)
 temporary.chmod(0o755);temporary.replace(path)
executable(BIN/'make','''#!/usr/bin/python3
import os,sys
args=['-j16' if a.startswith('-j') and a[2:].isdigit() else a for a in sys.argv[1:]]
os.execv('/usr/bin/taskset',['taskset','-c','48-63','/usr/bin/make',*args])
''')
for p in BIN.iterdir():p.chmod(0o755)
ORACLE=BASE/'oracle/src';ORACLE.mkdir(parents=True,exist_ok=True)
for p in Path('/home/user/Projects/redis/src').iterdir():
    target=ORACLE/p.name
    if not target.exists():target.symlink_to(p)
for name in ('redis-server','redis-cli'):
    target=ORACLE/name
    expected=Path('/home/user/Projects/redis74/src')/name
    if target.is_symlink() and target.resolve()==expected.resolve():continue
    if target.is_symlink():target.unlink()
    target.symlink_to(expected)
def environment():
 return dict(os.environ,PATH=str(BIN)+':'+os.environ['PATH'],
     PYTHONPATH=str(DOC/'fixture_site'),FLIPLISTEN_FIXTURE_PORT_LOG=str(DOC/'fixture-ports.log'),
     REDIS74_ROOT=str(ORACLE.parent),GATE_TEST_PORT='21899',GATE_DIFFER_ORACLE_CORES='56',
     GATE_NOTIFY_ORACLE_CORES='56',GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
     GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli')
if __name__=='__main__':
 label,engine,*jobs=sys.argv[1:]
 requested_jobs=jobs.copy()
 overrides=DOC/'proof-plan-overrides.json'
 if overrides.exists():jobs=json.loads(overrides.read_text()).get(label,jobs)
 binary=Path(os.environ.get('FLIPLISTEN_PROOF_BINARY',str(ROOT/'build/tomokv'))).resolve()
 server_source=binary
 if engine=='epoll':
    binary=BASE/('tomokv-epoll-'+label)
    # A Redis-style configuration path must remain argv[1]. Insert the engine
    # after it, before explicit later flags so a declared uring leg still wins.
    binary.write_text('#!/usr/bin/python3\nimport os,sys\nargs=sys.argv[1:]\nfirst=[]\nif args and not args[0].startswith("-"):\n first=[args.pop(0)]\nserver='+repr(str(server_source))+'\nos.execv(server,[server,*first,"--net-io","epoll",*args])\n')
    binary.chmod(0o755)
 dest=DOC/'proof'/label;dest.mkdir(parents=True,exist_ok=True)
 env=environment();env.update(GATE_ONLY_JOBS=' '.join(jobs),GATE_LEDGER=str(dest/'ledger'))
 argv=['taskset','-c','48-63','bash','tests/gate.sh','full','--server-cores','48-55',
       '--load-cores','56-63','--server-smt','','--load-smt','','--ports',
       os.environ.get('FLIPLISTEN_PROOF_PORTS','21810-21839'),
       '--candidate-binary',str(binary)]
 (dest/'command.json').write_text(json.dumps(dict(argv=argv,jobs=jobs,requested_jobs=requested_jobs,
      binary=str(server_source),sha256=hashlib.sha256(server_source.read_bytes()).hexdigest(),
      test_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('tests/gate.sh','tests/flipfix.py','tests/fliplisten.py','tests/r7shadow_sync.py')}),indent=2)+'\n')
 with (dest/'gate.log').open('w') as f:
    rc=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
 (dest/'returncode').write_text(str(rc)+'\n');print(label,rc,flush=True)
 sys.exit(rc)
