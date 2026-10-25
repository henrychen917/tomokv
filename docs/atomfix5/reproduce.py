#!/usr/bin/env python3
"""Diagnostic reproductions, not performance measurements or gate receipts."""
import argparse
import collections
import concurrent.futures
import contextlib
import json
from pathlib import Path
import sys
import threading
import time
import traceback
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from atomfix5 import boot
from _lib import Conn, RespError, encode, info


def pair(admin):
    keys = [f'atomfix5:{i}' for i in range(256)]
    geo = admin.must('DEBUG', 'SHARDS', *keys)
    other = next(i for i in range(1, len(keys)) if geo[i][1] != geo[0][1])
    print(json.dumps(dict(keys=[keys[0], keys[other]], geometry=[geo[0], geo[other]])), flush=True)
    return keys[0], keys[other]


def scripts(admin, port, keys):
    a, b = keys
    body = "local n=redis.call('INCR',KEYS[1]);redis.call('INCR',KEYS[2]);return n"
    library = "#!lua name=atomfix5\nredis.register_function('atomfix5',function(keys,args) " + body.replace('KEYS','keys') + ' end)'
    assert admin.must('FUNCTION', 'LOAD', 'REPLACE', library) == b'atomfix5'
    outcomes = {}
    for name in ('EVAL', 'FCALL'):
        admin.must('MSET', a, 0, b, 0)
        barrier = threading.Barrier(8)
        command = (name, body if name == 'EVAL' else 'atomfix5', 2, a, b)
        def worker(index):
            counts = collections.Counter()
            with contextlib.closing(Conn('127.0.0.1', port, timeout=30)) as c:
                barrier.wait(10)
                for batch in range(50):
                    c.raw(encode(*command) * 16)
                    for _ in range(16):
                        reply = c.read()
                        counts[str(reply) if isinstance(reply, RespError) else 'OK'] += 1
            return counts
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            counts = sum(pool.map(worker, range(8)), collections.Counter())
        values = admin.must('MGET', a, b)
        assert values == [str(counts['OK']).encode()] * 2, (counts, values)
        outcomes[name] = dict(counts)
    return outcomes



def script_window(admin, port, keys):
    a,b=keys
    clients=[]
    try:
        admin.must('DEBUG','SCRIPT-STAGE-DEFER',250000)
        clients=[Conn('127.0.0.1',port,timeout=10) for _ in range(64)]
        for c in clients:c.send('EVAL',"return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}",2,a,b)
        counts=collections.Counter(str(r) if isinstance(r,RespError) else 'OK' for r in (c.read() for c in clients))
    finally:
        admin.must('DEBUG','SCRIPT-STAGE-DEFER',0)
        for c in clients:c.close()
    return dict(counts)


def pops(admin, port, keys):
    a, b = keys
    outcomes = {}
    for kind in ('LMPOP', 'ZMPOP'):
        admin.must('DEL', a, b)
        count = 12000
        if kind == 'LMPOP':
            for base in range(0, count, 512):
                admin.must('RPUSH', b, *[str(i) for i in range(base, min(base+512,count))])
        else:
            for base in range(0, count, 512):
                admin.must('ZADD', b, *[x for i in range(base,min(base+512,count)) for x in (i,str(i))])
        barrier = threading.Barrier(16)
        command = (kind, 2, a, b, 'LEFT' if kind == 'LMPOP' else 'MIN')
        def worker(index):
            counts = collections.Counter()
            with contextlib.closing(Conn('127.0.0.1', port, timeout=30)) as c:
                barrier.wait(10)
                for turn in range(400):
                    if index < 8:
                        if kind == 'LMPOP': c.must('LPUSH', a, f'hot:{index}:{turn}')
                        else: c.must('ZADD', a, turn, f'hot:{index}:{turn}')
                    reply = c.cmd(*command)
                    counts['null' if reply is None else str(reply) if isinstance(reply, RespError) else 'OK'] += 1
            return counts
        with concurrent.futures.ThreadPoolExecutor(16) as pool:
            counts = sum(pool.map(worker, range(16)), collections.Counter())
        remain = admin.must('LLEN' if kind == 'LMPOP' else 'ZCARD', b)
        assert remain > 0, ('fallback not continuously populated', remain)
        outcomes[kind] = dict(counts=counts, fallback_remaining=remain)
    return outcomes


def slots(admin, port, keys):
    a, b = keys
    admin.must('DEL', a, b)
    # Each lane moves its own member back and forth; all first hops fan out to two owners.
    admin.must('SADD', a, *[str(i) for i in range(32)])
    barrier = threading.Barrier(32)
    def worker(index):
        counts = collections.Counter()
        with contextlib.closing(Conn('127.0.0.1', port, timeout=60)) as c:
            barrier.wait(10)
            commands = [encode('SMOVE', *( (a,b) if n%2==0 else (b,a)), str(index)) for n in range(256)]
            for batch in range(10):
                c.raw(b''.join(commands))
                for n in range(256):
                    reply = c.read()
                    counts[str(reply) if isinstance(reply, RespError) else str(reply)] += 1
        return counts
    with concurrent.futures.ThreadPoolExecutor(32) as pool:
        counts = sum(pool.map(worker, range(32)), collections.Counter())
    return dict(counts=counts, source=admin.must('SCARD',a), destination=admin.must('SCARD',b))


def window(admin, port, keys):
    a,b=keys
    admin.must('MSET',a,0,b,0)
    before=info(admin,'stats')
    clients=[]
    samples=[]
    try:
        admin.must('DEBUG','ATOMIC-COMMIT-DELAY',2000)
        clients=[Conn('127.0.0.1',port,timeout=60) for _ in range(400)]
        wire=b''.join(encode(*c) for c in [('MULTI',),('INCR',a),('INCR',b),('EXEC',)])
        for c in clients: c.raw(wire)
        end=time.monotonic()+1
        while time.monotonic()<end:
            snap=info(admin,'stats')
            samples.append({k:snap[k] for k in ('atomic_credit_pool','atomic_inflight','atomic_window_stalls')})
            if snap['atomic_credit_pool']=='0': break
        for c in clients:
            replies=[c.read() for _ in range(4)]
            assert replies[:3]==[b'OK',b'QUEUED',b'QUEUED'] and isinstance(replies[3],list),replies
    finally:
        admin.must('DEBUG','ATOMIC-COMMIT-DELAY',0)
        for c in clients:c.close()
    after=info(admin,'stats')
    values=admin.must('MGET',a,b)
    assert values==[b'400',b'400'],values
    return dict(samples=samples, before=before['atomic_window_stalls'],after=after['atomic_window_stalls'])


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--binary',required=True)
    p.add_argument('--oracle',default='/home/user/Projects/redis74/src/redis-server')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',nargs='+',default=['scripts','pops','slots','window'])
    args=p.parse_args()
    results=[]
    for mode in ('1s','2s'):
        for atomic in (0,1):
            label=f'{mode}-atomic{atomic}'
            flags=['--shards','16','--thread-mode',mode,'--atomic',str(atomic),'--databases','16',
                   '--net-io','uring','--read-local','1' if mode=='1s' else '0',
                   '--key-lb','0','--client-lb','0','--flip-auto','0']
            if mode=='2s':flags+=['--ratio','6:2']
            with boot(args.binary,'48-55',34810,args.output/label,flags) as admin:
                keys=pair(admin)
                for case in args.cases:
                    try:
                        result=globals()[case](admin,34810,keys)
                        record=dict(leg=label,case=case,result=result)
                    except Exception:
                        traceback.print_exc()
                        record=dict(leg=label,case=case,error=traceback.format_exc())
                    print(json.dumps(record),flush=True);results.append(record)
    if 'scripts' in args.cases:
        with boot(args.oracle,'48-55',34810,args.output/'oracle',['--databases','16'],True) as admin:
            result=scripts(admin,34810,['atomfix5:a','atomfix5:b'])
            record=dict(leg='Redis7.4',case='scripts',result=result)
            print(json.dumps(record),flush=True);results.append(record)
    (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
