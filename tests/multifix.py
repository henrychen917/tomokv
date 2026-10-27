#!/usr/bin/env python3
"""Directed transaction roots; one root per invocation and exact wire replies."""
import argparse
import json
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

CASES={'RESET-IN-MULTI':reset,'WATCH-SPURIOUS-INVALIDATION':watch}
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
