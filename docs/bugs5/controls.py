"""Oracle and FLIP reproductions; no performance load or private gate substitute."""
import importlib.util,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,info,RespError
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT; support.OUT=ROOT/'build/bugs5/controls-2'
DOC=ROOT/'docs/bugs5/controls';DOC.mkdir(parents=True,exist_ok=True)
rows=[]
def report(c):
    r=c.must('FLIP');return dict(zip(r[::2],r[1::2]))
with support.owned('oracle',Path('/home/user/Projects/redis74/src/redis-server'),'104',24841,[]):
    for test in ('scancompact','slowlog_identity','read_local_lfu'):
        argv=['taskset','-c','105-111','python3',f'tests/{test}.py','127.0.0.1','24841']
        if test=='read_local_lfu':argv+=['--oracle']
        with (DOC/f'oracle-{test}.log').open('w') as log:
            rc=subprocess.run(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
        rows.append(dict(test=test,oracle_rc=rc));print(rows[-1],flush=True)
for mode in ('1s','2s'):
  for engine in ('uring','epoll'):
    for atomic in (0,1):
      label=f'flip-{mode}-{engine}-{atomic}'
      shape=['--thread-mode',mode,'--shards','16','--net-io',engine,
             '--atomic',str(atomic),'--key-lb','0','--client-lb','0','--flip-auto','0']
      if mode=='2s':shape+=['--ratio','6:2']
      with support.owned(label,ROOT/'build/tomokv-PRE','96-103',24840,shape):
        admin=Conn('127.0.0.1',24840)
        if mode=='1s':
          reply=admin.cmd('FLIP',4,4)
          rows.append(dict(label=label,reply=repr(reply)));admin.close();continue
        for outcome in ('complete','rollback'):
          blocker=Conn('127.0.0.1',24840);issuer=Conn('127.0.0.1',24840)
          blocker.send('BLPOP','bugs5:flip:blocker',0)
          deadline=time.monotonic()+3
          while int(info(admin,'clients')['blocked_clients'])!=1:
            assert time.monotonic()<deadline;time.sleep(.01)
          old=report(admin);target=4 if old[b'live_io']!=4 else 6
          issuer.send('FLIP',target,8-target)
          deadline=time.monotonic()+3
          while not report(admin)[b'moving']:
            assert time.monotonic()<deadline;time.sleep(.001)
          peers=[]
          for _ in range(24):
            c=Conn('127.0.0.1',24840,timeout=8)
            c.send('PING');peers.append(c)
          # Established-client command must complete when FLIP retires too.
          established=admin
          established.send('PING')
          if outcome=='complete':blocker.close()
          started=time.monotonic();reply=issuer.read();ended=time.monotonic()
          probe=established.read()
          results=[]
          for c in peers:
            try:results.append(repr(c.read()))
            except Exception as e:results.append(type(e).__name__)
            finally:c.close()
          row=dict(label=label,case=outcome,flip_reply=repr(reply),
                   remaining_quiesce_s=ended-started,post_flip_drain_s=time.monotonic()-ended,
                   established=repr(probe),new_connections=results)
          rows.append(row);print(json.dumps(row),flush=True)
          blocker.close();issuer.close()
        admin.close()
      (DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
(DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
