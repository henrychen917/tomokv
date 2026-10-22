"""Oracle and FLIP reproductions; no performance load or private gate substitute."""
import hashlib,importlib.util,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,info,RespError
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT; arm=sys.argv[1] if len(sys.argv)>1 else 'PRE'
support.OUT=ROOT/('build/fliplisten/'+arm.lower()+'-controls')
DOC=ROOT/('docs/fliplisten/'+arm.lower()+'-controls');DOC.mkdir(parents=True,exist_ok=True)
binary=ROOT/('build/tomokv-PRE' if arm=='PRE' else 'build/tomokv')
(DOC/'binary.json').write_text(json.dumps(dict(path=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest()),indent=2)+'\n')
rows=[]
def report(c):
    r=c.must('FLIP');return dict(zip(r[::2],r[1::2]))
for mode in ('1s','2s'):
  for engine in ('uring','epoll'):
    for atomic in (0,1):
      label=f'flip-{mode}-{engine}-{atomic}'
      shape=['--thread-mode',mode,'--shards','16','--net-io',engine,
             '--atomic',str(atomic),'--key-lb','0','--client-lb','0','--flip-auto','0']
      if mode=='2s':shape+=['--ratio','6:2']
      deadline=time.monotonic()+10
      while subprocess.check_output(['ss','-ltnH','sport = :21800']).strip():
        assert time.monotonic()<deadline;time.sleep(.05)
      with support.owned(label,ROOT/('build/tomokv-PRE' if arm=='PRE' else 'build/tomokv'),'48-55',21800,shape):
        admin=Conn('127.0.0.1',21800)
        if mode=='1s':
          reply=admin.cmd('FLIP',4,4)
          rows.append(dict(label=label,reply=repr(reply)));admin.close();continue
        for direction,outcome in ((d,o) for d in ('io-ex','ex-io') for o in ('complete','rollback')):
          wanted=6 if direction=='io-ex' else 4
          current=report(admin)[b'live_io']
          if current!=wanted: admin.must('FLIP',wanted,8-wanted)
          blocker=Conn('127.0.0.1',21800);issuer=Conn('127.0.0.1',21800)
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
            c=Conn('127.0.0.1',21800,timeout=8)
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
          row=dict(label=label,direction=direction,case=outcome,flip_reply=repr(reply),
                   remaining_quiesce_s=ended-started,post_flip_drain_s=time.monotonic()-ended,
                   established=repr(probe),new_connections=results)
          rows.append(row);print(json.dumps(row),flush=True)
          if arm=='POST':
            assert probe==b'PONG' and results==["b'PONG'"]*24,row
            assert reply==b'OK' if outcome=='complete' else isinstance(reply,RespError) and b'timed out' in reply.message,row
          blocker.close();issuer.close()
        admin.close()
      (DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
(DOC/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
