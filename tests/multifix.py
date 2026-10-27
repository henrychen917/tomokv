#!/usr/bin/env python3
"""Directed transaction roots; one root per invocation and exact wire replies."""
import argparse
import json
import time
from _lib import Conn, RespError, info, shard_of

OK = b'OK'
QUEUED = b'QUEUED'

def expect(actual, expected):
    assert actual == expected, (actual, expected)

def reset(a, b, oracle):
    expect(a.cmd('WATCH','multifix:reset'), OK)
    expect(a.cmd('MULTI'), OK)
    expect(a.cmd('SET','multifix:reset','discarded'), QUEUED)
    expect(a.cmd('RESET'), b'RESET')
    expect(a.cmd('EXEC'), RespError('ERR EXEC without MULTI'))
    expect(a.cmd('EXISTS','multifix:reset'), 0)
    expect(b.cmd('SET','multifix:reset','next'), OK)
    expect(a.cmd('MULTI'), OK)
    expect(a.cmd('PING'), QUEUED)
    expect(a.cmd('EXEC'), [b'PONG'])

def watch(a, b, oracle):
    # Fresh state on each topology. Never rely on the process hash seed to
    # happen to put the upstream names on the same shard.
    pairs=[]
    if oracle:
        pairs=[('srcset{t}','dstset{t}')]
    else:
        by_shard={}
        for n in range(4096):
            key='multifix:watch:'+str(n)
            sid=shard_of(a,key)
            by_shard.setdefault(sid,[]).append(key)
            if len(by_shard)>=2 and any(len(v)>=2 for v in by_shard.values()): break
        first=next(s for s,v in by_shard.items() if len(v)>=2)
        other=next(s for s in by_shard if s!=first)
        pairs=[tuple(by_shard[first][:2]),(by_shard[first][0],by_shard[other][0])]
        assert shard_of(a,pairs[0][0])==shard_of(a,pairs[0][1])
        assert shard_of(a,pairs[1][0])!=shard_of(a,pairs[1][1])
    for source,dest in pairs:
        for added in (False,True):
            a.cmd('DEL',source,dest)
            expect(a.cmd('SADD',source,'a','b'),2)
            expect(a.cmd('SADD',dest,'d' if added else 'a'),1)
            expect(a.cmd('WATCH',dest),OK)
            expect(a.cmd('MULTI'),OK)
            expect(a.cmd('SADD',dest,'c'),QUEUED)
            expect(b.cmd('SMOVE',source,dest,'a'),1)
            expect(a.cmd('EXEC'),None if added else [1])
            expect(a.cmd('SCARD',dest),2)
            expect(a.cmd('SCARD',source),1)
    print(json.dumps({'topologies':pairs}))

def linear(a, b, oracle):
    counts=[]
    for count in (128, 512, 4000):
        key='multifix:stream:'+str(count)
        a.cmd('DEL',key)
        before=0 if oracle else int(info(a,'STATS')['atomic_entries'])
        expect(a.cmd('MULTI'),OK)
        for i in range(1,count+1):a.send('XADD',key,str(i)+'-0','f','v')
        for i in range(count):expect(a.read(),QUEUED)
        expect(a.cmd('EXEC'),[(str(i)+'-0').encode() for i in range(1,count+1)])
        expect(a.cmd('XLEN',key),count)
        expect(a.cmd('XRANGE',key,'1-0','1-0'),[[b'1-0',[b'f',b'v']]])
        expect(a.cmd('XREVRANGE',key,'+','-','COUNT',1),[[str(count).encode()+b'-0',[b'f',b'v']]])
        if not oracle:
            installed=int(info(a,'STATS')['atomic_entries'])-before
            print(json.dumps({'xadds':count,'installed_records':installed}),flush=True)
            counts.append((count,installed))
    assert all(installed == 1 for count,installed in counts), ('one private version per repeated-key transaction',counts)

def slowlog(a, b, oracle):
    expect(a.cmd('CONFIG','SET','slowlog-log-slower-than',100000),OK)
    expect(a.cmd('CLIENT','SETNAME','multifix-slow'),OK)
    expect(a.cmd('SLOWLOG','RESET'),OK)
    expect(a.cmd('MULTI'),OK)
    expect(a.cmd('DEBUG','SLEEP','0.2'),QUEUED)
    expect(a.cmd('EXEC'),[OK])
    expect(a.cmd('SLOWLOG','LEN'),1)
    entries=a.cmd('SLOWLOG','GET')
    expect(len(entries),1)
    expect(entries[0][3],[b'DEBUG',b'SLEEP',b'0.2'])
    expect(entries[0][5],b'multifix-slow')
    assert entries[0][2]>=100000,entries
    expect(a.cmd('SLOWLOG','RESET'),OK)
    expect(a.cmd('MULTI'),OK)
    expect(a.cmd('DEBUG','SLEEP','0.11'),QUEUED)
    expect(a.cmd('PING'),QUEUED)
    expect(a.cmd('DEBUG','SLEEP','0.21'),QUEUED)
    expect(a.cmd('EXEC'),[OK,b'PONG',OK])
    entries=a.cmd('SLOWLOG','GET')
    expect([entry[3] for entry in entries],
           [[b'DEBUG',b'SLEEP',b'0.21'],[b'DEBUG',b'SLEEP',b'0.11']])
    expect(a.cmd('CONFIG','SET','slowlog-log-slower-than',-1),OK)

def held(a, count=1):
    for _ in range(100):
        if int(info(a,'CLIENTS')['blocked_clients']) == count:return
        time.sleep(.01)
    raise AssertionError(('pause never held the client',info(a,'CLIENTS')))

def pause(a, b, oracle):
    expect(a.cmd('MULTI'),OK)
    expect(a.cmd('SET','multifix:p1','v'),QUEUED)
    expect(a.cmd('CLIENT','PAUSE',60000,'WRITE'),QUEUED)
    expect(a.cmd('SET','multifix:p2','v'),QUEUED)
    expect(a.cmd('EXEC'),[OK,OK,OK])
    b.send('SET','multifix:p3','v')
    held(a)
    expect(a.cmd('MGET','multifix:p1','multifix:p2','multifix:p3'),[b'v',b'v',None])
    expect(a.cmd('CLIENT','UNPAUSE'),OK)
    expect(b.read(),OK)
    expect(a.cmd('FLUSHDB'),OK)
    before=int(info(a,'STATS')['expired_keys'])
    expect(a.cmd('MULTI'),OK)
    for key in ('multifix:e1','multifix:e2'):
        expect(a.cmd('SET',key,'v','PX',10),QUEUED)
    expect(a.cmd('CLIENT','PAUSE',60000,'WRITE'),QUEUED)
    expect(a.cmd('EXEC'),[OK,OK,OK])
    time.sleep(.05)
    for key in ('multifix:e1','multifix:e2'):expect(a.cmd('GET',key),None)
    expect(int(info(a,'STATS')['expired_keys']),before)
    assert a.cmd('RANDOMKEY') in (b'multifix:e1',b'multifix:e2')
    expect(a.cmd('CLIENT','UNPAUSE'),OK)
    for key in ('multifix:e1','multifix:e2'):expect(a.cmd('GET',key),None)
    expect(int(info(a,'STATS')['expired_keys']),before+2)
    # Redis measures the timeout from EXEC's frozen command time. A long
    # command after PAUSE can exhaust it before EXEC returns; retiring the
    # pause with a fresh clock would incorrectly hold this next write.
    expect(a.cmd('MULTI'),OK)
    expect(a.cmd('CLIENT','PAUSE',2000,'WRITE'),QUEUED)
    expect(a.cmd('DEBUG','SLEEP','2.1'),QUEUED)
    expect(a.cmd('EXEC'),[OK,OK])
    b.sock.settimeout(1.0)
    expect(b.cmd('SET','multifix:deadline','v'),OK)

def pause_exec(a, b, oracle):
    for command,reply in ((('SET','multifix:held','v'),OK),
                          (('EVAL','return 12',0),12),
                          (('EVAL','#!lua\nreturn 13',0),13)):
        expect(b.cmd('MULTI'),OK)
        expect(b.cmd(*command),QUEUED)
        expect(a.cmd('CLIENT','PAUSE',60000,'WRITE'),OK)
        b.send('EXEC')
        held(a)
        if command[0]=='SET':expect(a.cmd('GET','multifix:held'),None)
        expect(a.cmd('CLIENT','UNPAUSE'),OK)
        expect(b.read(),[reply])
    expect(a.cmd('CLIENT','PAUSE',60000,'WRITE'),OK)
    expect(b.cmd('MULTI'),OK)
    expect(b.cmd('GET','multifix:held'),QUEUED)
    expect(b.cmd('PING'),QUEUED)
    expect(b.cmd('EXEC'),[b'v',b'PONG'])
    expect(a.cmd('CLIENT','UNPAUSE'),OK)

CASES={'RESET-IN-MULTI':reset,'WATCH-SPURIOUS-INVALIDATION':watch,
       'EXEC-REPEATED-KEY-LINEAR':linear,'SLOWLOG-EXEC-BODY-NOT-LOGGED':slowlog,
       'PAUSE-IN-MULTI':pause,'PAUSE-EXEC-NOT-HELD':pause_exec}
def main():
    p=argparse.ArgumentParser();p.add_argument('host');p.add_argument('port',type=int)
    p.add_argument('--case',choices=CASES,required=True);p.add_argument('--oracle',action='store_true')
    args=p.parse_args()
    a=Conn(args.host,args.port,timeout=15);b=Conn(args.host,args.port,timeout=15)
    try:
        CASES[args.case](a,b,args.oracle)
        print('PASS',args.case)
    finally:
        a.close();b.close()
if __name__=='__main__':main()
