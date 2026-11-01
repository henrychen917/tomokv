#!/usr/bin/env python3
"""One observer orders keyevents and EXEC-enrolled invalidations around a wake."""
import argparse
import contextlib
import copy
import json
import os
from pathlib import Path
import select
import time
from _lib import info
from clientcompat import Peer, clean
from persistfix2 import boot, emit, wait

SCRIPT = "redis.call('LPUSH',KEYS[1],'item');redis.call('SET',KEYS[2],'v');return redis.call('LLEN',KEYS[1])"

def probe(a, c, shape, kind):
    with contextlib.ExitStack() as stack:
        def peer():
            p=Peer(a.port); stack.callback(p.close); return p
        if a.oracle:
            names=[f'order:{shape}:list'.encode(), f'order:{shape}:key'.encode()]
        else:
            pool=[f'order:{shape}:{i}'.encode() for i in range(512)]
            geo=c.must('DEBUG','SHARDS',*pool)
            test={'shard':lambda g:g[0]==geo[0][0],
                  'owner':lambda g:g[0]!=geo[0][0] and g[1]==geo[0][1],
                  'cross':lambda g:g[1]!=geo[0][1]}[shape]
            names=[pool[0],next(k for k,g in zip(pool[1:],geo[1:]) if test(g))]
            emit('geometry',shape=shape,keys=names,placement=c.must('DEBUG','SHARDS',*names))
        key, second=names
        c.must('DEL',*names)
        observer, blocked=peer(),peer()
        assert isinstance(observer.cmd('HELLO',3),list)
        assert observer.cmd('CLIENT','TRACKING','ON') == b'OK'
        channels=[b'__keyevent@0__:'+event for event in (b'lpush',b'lpop',b'del',b'set')]
        for channel in channels:
            assert observer.cmd('SUBSCRIBE',channel)[0] == b'subscribe'
        if os.getenv('WAVE14_ORDER_ENROL_PLAIN') == '1':
            assert observer.cmd('LLEN',key) == 0
            assert observer.cmd('GET',second) is None
        else:
            assert observer.cmd('MULTI') == b'OK'
            assert observer.cmd('LLEN',key) == b'QUEUED'
            assert observer.cmd('GET',second) == b'QUEUED'
            assert observer.cmd('EXEC') == [0,None]
        assert observer.drain() == [], 'enrolment itself published a push'
        blocked.send('BLPOP',key,0)
        wait(lambda:int(info(c,'clients')['blocked_clients'])==1,'BLPOP registered')
        emit('risky moment',case='EXEC-enrolled observer and registered waiter',hits=1,shape=shape,kind=kind)
        c.must('SLOWLOG','RESET')
        if kind=='EXEC':
            assert c.must('MULTI') == b'OK'
            for command in [('LPUSH',key,'item'),('SET',second,'v'),('LLEN',key)]:
                assert c.must(*command) == b'QUEUED'
            reply=c.must('EXEC')
        else:
            body=SCRIPT if kind=='EVAL' else c.must('SCRIPT','LOAD',SCRIPT)
            reply=c.must(kind,body,2,*names)
        assert blocked.response()==[key,b'item']
        frames=observer.drain(.5)
        # Notifications and invalidations share ONE observer, so their wire
        # order is meaningful. Cross-client reply arrival is not compared.
        sequence=[]
        for frame in frames:
            if frame[0]==b'invalidate':
                assert frame[1] is not None,frame
                for k in frame[1]:sequence.append(['invalidate',names.index(k)])
            else:
                assert frame[0]==b'message',frame
                sequence.append([frame[1].split(b':')[-1].decode(),names.index(frame[2])])
        rows=c.must('SLOWLOG','GET',-1)
        wanted={b'BLPOP',b'EVAL',b'EVALSHA'} if kind!='EXEC' else {b'BLPOP',b'LPUSH',b'SET',b'LLEN'}
        slow=[row[3][0].upper().decode() for row in reversed(rows) if row[3][0].upper() in wanted]
        return dict(shape=shape,kind=kind,sequence=sequence,slowlog=slow,reply=clean(reply))

def main():
    p=argparse.ArgumentParser()
    for name in ('binary','oracle','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--port',type=int,required=True);p.add_argument('--cores',required=True)
    p.add_argument('--ratio',default='6:2');p.add_argument('--single',action='store_true')
    a=p.parse_args();os.environ['LC_ALL']='C';a.output.mkdir(parents=True,exist_ok=True)
    legs=[(True,'oracle','normal',16,1)]+[(False,m,e,d,t) for m in ('1s','2s') for e in ('uring','epoll') for d in (1,16) for t in (0,1)]
    if a.single: legs=[legs[0],(False,'2s','epoll',16,1)]
    refs={};results=[];failures=[]
    for oracle,mode,engine,db,atomic in legs:
        leg=copy.copy(a);leg.oracle=oracle;leg.mode=mode;leg.engine=engine
        leg.output=a.output/f'{mode}-{engine}-db{db}-a{atomic}'
        leg.output.mkdir()
        if oracle:leg.binary=a.oracle
        options=['--databases',str(db),'--notify-keyspace-events','Elg$','--slowlog-log-slower-than','0','--slowlog-max-len','1024']
        if not oracle:options+=['--atomic',str(atomic)]
        try:
            with boot(leg,'server',options) as (_,c,_):
                for shape in ('shard','owner','cross'):
                    for kind in ('EVAL','EVALSHA','EXEC'):
                        row=probe(leg,c,shape,kind);row['leg']=leg.output.name
                        if oracle:refs[shape,kind]=row
                        expected=refs[shape,kind]
                        row['matches']={k:row[k]==expected[k] for k in ('sequence','slowlog','reply')}
                        results.append(row);emit('order',**row)
                        if not all(row['matches'].values()):failures.append(row)
        except Exception as error:
            failures.append(dict(leg=leg.output.name,error=repr(error)));emit('FAIL',leg=leg.output.name,error=repr(error))
        (a.output/'results.json').write_text(json.dumps(dict(results=results,failures=failures),indent=2)+'\n')
    assert not failures,failures

if __name__=='__main__':main()
