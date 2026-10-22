"""One bounded MGET batch for the debugger diagnostic; verifies every reply."""
import json,os,signal,socket,sys,time
from pathlib import Path
out=Path(sys.argv[1]);cfg=json.loads((out/'config.json').read_text())
os.sched_setaffinity(0,{72})
def wire(*args):
    args=[str(x).encode() if not isinstance(x,bytes) else x for x in args]
    return b'*%d\r\n'%len(args)+b''.join(b'$%d\r\n'%len(x)+x+b'\r\n' for x in args)
end=time.monotonic()+90
while True:
    try:s=socket.create_connection(('127.0.0.1',cfg['port']),timeout=2);break
    except OSError:
        if time.monotonic()>end:raise
        time.sleep(.05)
s.settimeout(120);f=s.makefile('rb')
def read():
    line=f.readline();assert line.endswith(b'\r\n'),line
    kind,val=line[:1],line[1:-2]
    if kind==b'+':return val
    if kind==b':':return int(val)
    if kind==b'$':
        n=int(val)
        if n==-1:return None
        v=f.read(n);assert f.read(2)==b'\r\n';return v
    if kind==b'*':return [read() for _ in range(int(val))]
    raise AssertionError(line)
def cmd(*args):s.sendall(wire(*args));return read()
keys={}
for i in range(512):
    k='wave4d:'+str(i);shard=cmd('DEBUG','SHARD',k)
    if shard<8:keys.setdefault(shard,k)
    if len(keys)==8:break
assert set(keys)==set(range(8)),keys
ordered=[keys[i] for i in range(8)];value=b'x'*64
for k in ordered:assert cmd('SET',k,value)==b'OK'
expected=[value]*8
assert cmd('MGET',*ordered)==expected
(out/'armed.json').write_text(json.dumps(dict(keys=ordered,shards=list(range(8)),value_bytes=64,warmup_commands=1)))
os.kill(int((out/'pid').read_text()),signal.SIGUSR1)
end=time.monotonic()+90
while not (out/'go').exists():
    assert time.monotonic()<end,'debugger did not arm'
    time.sleep(.02)
s.sendall(wire('MGET',*ordered)*cfg['depth'])
for _ in range(cfg['depth']):assert read()==expected
(out/'client.json').write_text(json.dumps(dict(replies=cfg['depth'])))
os.kill(int((out/'pid').read_text()),signal.SIGUSR1)
f.close();s.close()
