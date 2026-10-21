from pathlib import Path
import argparse,sys,time,json,hashlib
sys.path.insert(0,str(Path.cwd()/'tests'))
import aoffix2 as h
import aoforder as order
p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--mode',choices=['1s','2s'],required=True);p.add_argument('--appendonly',default='yes')
a=p.parse_args();a.binary=a.binary.resolve();a.artifacts=a.artifacts.resolve();a.artifacts.mkdir(parents=True,exist_ok=False)
a.databases=16;a.engine='uring';a.cores='96-103';a.ratio='6:2';a.port=25740;a.policy='always';a.oracle=False;h.ARGS=a
h.emit('arm',binary=str(a.binary),sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),mode=a.mode)
options=h.aof('always')+['--atomic','1','--databases','16','--appendonly',a.appendonly]
with h.Server(options) as server:
    admin,group=server.client(timeout=10),server.client(timeout=10)
    keys=order.keys_on_two_owners(admin)
    sid=admin.cmd('DEBUG','SHARD',keys[0])
    sentinel=next(k for i in range(4096) if admin.cmd('DEBUG','SHARD',(k:=f'aoforder-hash-keep:{i}'))==sid)
    assert admin.cmd('DEBUG','SET-ACTIVE-EXPIRE','0')==b'OK'
    assert admin.cmd('HSET',keys[0],'f','old')==1
    assert admin.cmd('HSET',sentinel,'f','keep')==1
    assert admin.cmd('HPEXPIRE',sentinel,60000,'FIELDS',1,'f')==[1]
    deadline=int(time.time()*1000)+1000
    assert admin.cmd('HPEXPIREAT',keys[0],deadline,'FIELDS',1,'f')==[1]
    assert admin.cmd('DEBUG','ATOMIC-COMMIT-HOLD','1')==b'OK'
    try:
        group.send('MSET',keys[0],'1',keys[1],'1')
        order.wait_for(lambda:order.stats(admin)['atomic_pending_entries']>=2,'no installed group')
        assert admin.cmd('HGET',keys[0],'f')==b'old','TTL arm missed its live window'
        while time.time()*1000<=deadline+10:time.sleep(.005)
        h.emit('expired_read',value=admin.cmd('HGET',keys[0],'f'))
    finally:
        assert admin.cmd('DEBUG','ATOMIC-COMMIT-HOLD','0')==b'OK'
    h.emit('reply',value=group.read())
    live=admin.cmd('MGET',*keys);h.emit('live',value=live)
    if a.appendonly=='yes':
        assert admin.cmd('DEBUG','LOADAOF')==b'OK'
        replay=admin.cmd('MGET',*keys);h.emit('replay',value=replay,equal=live==replay)

if a.appendonly=='yes':
    with h.Server(options) as server:
        restarted=server.client().cmd('MGET',*keys)
        h.emit('restart',value=restarted,equal=live==restarted)
assert live==[b'1',b'1'], 'hash-field expiry tore an undecided MSET in the live keyspace'
if a.appendonly=='yes':
    assert replay==live and restarted==live, 'AOF replay differs from live after hash-field expiry'
