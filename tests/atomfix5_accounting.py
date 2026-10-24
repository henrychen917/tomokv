#!/usr/bin/env python3
"""AT4.19: acknowledged list writes survive an undecided multi-owner EXEC."""
import argparse
import collections
import contextlib
import json
from pathlib import Path
import select
import traceback
from types import SimpleNamespace

from atomfix5 import boot
from _lib import Conn, encode
from txniso import Battery, WindowMiss


def producers(port, keys):
    clients, expected = [], {key: [] for key in keys}
    for i in range(8):
        key = keys[i % 2]
        tokens = [f'writer:{i}:{n}'.encode() for n in range(32)]
        clients.append((Conn('127.0.0.1', port, timeout=10), key, tokens))
        expected[key].extend(tokens)
    return clients, expected


def publish(clients):
    for c, key, tokens in clients:
        c.raw(b''.join(encode('RPUSH', key, token) for token in tokens))


def drain(clients):
    replies = []
    for c, key, tokens in clients:
        for token in tokens:
            reply = c.read()
            assert isinstance(reply, int) and reply > 0, (key, token, reply)
            replies.append((key, reply))
    return replies


def exact(admin, keys, expected, replies):
    # Integer lengths also have to account exactly once for every RPUSH. Each
    # list starts empty and has no removals, so 1..129 must appear once each.
    for key in keys:
        actual = admin.must('LRANGE', key, 0, -1)
        want = expected[key] + [b'unit']
        assert collections.Counter(actual) == collections.Counter(want), dict(
            key=key, acknowledged=len(want), visible=len(actual),
            missing=list((collections.Counter(want)-collections.Counter(actual)).elements()),
            duplicated=list((collections.Counter(actual)-collections.Counter(want)).elements()))
        lengths = [value for k, value in replies if k == key]
        assert sorted(lengths) == list(range(1, len(want)+1)), (key, lengths)
    return dict(acknowledged=len(replies), visible=sum(len(v)+1 for v in expected.values()),
                missing=0, duplicated=0)


def oracle_case(admin, port):
    keys=['atomfix5:oracle:a','atomfix5:oracle:b']
    admin.must('DEL', *keys)
    clients, expected=producers(port,keys)
    try:
        with contextlib.closing(Conn('127.0.0.1',port)) as c:
            c.raw(b''.join(encode(*cmd) for cmd in [('MULTI',),('RPUSH',keys[0],'unit'),
                ('MGET',*keys),('RPUSH',keys[1],'unit'),('EXEC',)]))
            assert [c.read() for _ in range(4)] == [b'OK']+[b'QUEUED']*3
            reply=c.read()
            assert reply == [1,[None,None],1],reply
        publish(clients)
        return exact(admin,keys,expected,[(keys[0],1),(keys[1],1)]+drain(clients))
    finally:
        for c,_,_ in clients:c.close()


def directed(port,mode):
    battery=Battery(SimpleNamespace(host='127.0.0.1',port=port,mode=mode,pre=False))
    try:
        for attempt in range(4):
            keys=battery.pair()
            clients,expected=producers(port,keys)
            sent=False
            replies=[]
            try:
                before=battery.counter('atomic_txn_writer_waits')
                commands=[('RPUSH',keys[0],'unit'),('MGET',*keys),('RPUSH',keys[1],'unit')]
                with battery.parked(commands,writes=True) as holder:
                    publish(clients)
                    sent=True
                    # A production waiter or an early reply from the broken
                    # control proves the competing requests reached the owner.
                    battery.wait(lambda: battery.counter('atomic_txn_writer_waits') > before or
                                 any(select.select([c.sock],[],[],0)[0] for c,_,_ in clients),
                                 'writers never reached the held unit',timeout=.2)
                    reply=holder.read()
                    assert isinstance(reply,list) and len(reply)==3 and reply[1]==[None,None],reply
                sent=False
                replies=drain(clients)
                result=exact(battery.admin,keys,expected,[(keys[0],reply[0]),(keys[1],reply[2])]+replies)
                waits=battery.counter('atomic_txn_writer_waits')-before
                assert waits>0,'no conflicting writer waited on the undecided unit'
                result.update(attempt=attempt+1,writer_waits=waits,owners=battery.admin.must('DEBUG','SHARDS',*keys))
                assert result['owners'][0][1] != result['owners'][1][1],result
                return result
            except WindowMiss:
                # Only a missed arming is retried, with fresh keys. A data or
                # reply failure is never retried. Retire all old traffic first.
                if attempt==3:raise AssertionError('undecided-unit window never opened in four fresh attempts')
            finally:
                if sent:drain(clients)
                for c,_,_ in clients:c.close()
        raise AssertionError('missing directed result')
    finally:
        battery.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary',required=True)
    p.add_argument('--oracle',required=True)
    p.add_argument('--cores',required=True)
    p.add_argument('--ratio',default='6:2')
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    failures=[]
    with boot(args.oracle,args.cores,args.port+1,args.output/'oracle',['--databases','16'],True) as admin:
        print(json.dumps(dict(oracle=oracle_case(admin,args.port+1))),flush=True)
    for mode in ('1s','2s'):
        for engine in ('uring','epoll'):
            for db in (1,16):
                label=f'{mode}-{engine}-db{db}-atomic1'
                flags=['--shards','16','--thread-mode',mode,'--atomic','1','--databases',str(db),
                       '--read-local','1' if mode=='1s' else '0','--net-io',engine,
                       '--key-lb','0','--client-lb','0','--flip-auto','0']
                if mode=='2s':flags+=['--ratio',args.ratio]
                try:
                    with boot(args.binary,args.cores,args.port,args.output/label,flags):
                        for repeat in range(4):
                            result=directed(args.port,mode)
                            print(json.dumps(dict(leg=label,repeat=repeat,**result)),flush=True)
                except Exception:
                    failures.append(label)
                    traceback.print_exc()
    print(json.dumps(dict(failures=failures)),flush=True)
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
