#!/usr/bin/env python3
"""Exact RESP regressions for the four selected pubtrackfix mechanisms.

One invocation owns a gate row: Redis, then both engines/modes, both database
namespaces, both atomic settings and both read-local settings. No rate assertions.
"""
import argparse
import contextlib
import itertools
import json
import select
import socket
import traceback
from pathlib import Path
from authfix import Run, Server
from _lib import encode

ROOTS = ('TRACK-BCAST-BATCH', 'PUBSUB-REPLY-OFF-PUSH',
         'PUBSUB-IMPLICIT-CONSUMER-EVENT', 'PUBSUB-EVICT-ON-MAXMEMORY')


def bulk(s):
    s = s if isinstance(s, bytes) else s.encode()
    return b'$%d\r\n' % len(s) + s + b'\r\n'


def array(*items, push=False):
    return (b'>' if push else b'*') + str(len(items)).encode() + b'\r\n' + b''.join(items)


class Wire:
    def __init__(self, port, rows):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=2)
        self.sock.settimeout(2)
        self.file = self.sock.makefile('rb')
        self.rows = rows

    def close(self):
        self.file.close()
        self.sock.close()

    def send(self, *args):
        self.rows.append({'send': [repr(v) for v in args]})
        self.sock.sendall(encode(*args))

    def frame(self):
        line = self.file.readline()
        assert line.endswith(b'\r\n'), line
        tag, body = line[:1], line[1:-2]
        if tag in (b'$', b'=') and int(body) >= 0:
            data = self.file.read(int(body) + 2)
            assert len(data) == int(body) + 2 and data.endswith(b'\r\n')
            return line + data
        if tag in (b'*', b'>', b'~', b'%'):
            return line + b''.join(self.frame() for _ in range(max(0, int(body)) * (2 if tag == b'%' else 1)))
        assert tag in (b'+', b'-', b':', b'_', b',', b'#', b'$'), line
        return line

    def read(self, expected=None):
        got = self.frame()
        self.rows.append({'reply_hex': got.hex(), 'expected_hex': expected.hex() if expected is not None else None})
        if expected is not None:
            assert got == expected, (got, expected)
        return got

    def cmd(self, expected, *args):
        self.send(*args)
        return self.read(expected)


def probe(case, port, rows, eviction_key='foo'):
    with contextlib.ExitStack() as stack:
        def client():
            c = Wire(port, rows); stack.callback(c.close); return c
        a, b = client(), client()
        if case == ROOTS[0]:
            a.cmd(None, 'HELLO', 3)
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'ON', 'BCAST')
            a.cmd(b'+OK\r\n', 'MSET', 'c', 3, 'a', 1, 'b', 2)
            a.read(array(bulk('invalidate'), array(bulk('a'), bulk('b'), bulk('c')), push=True))
            a.cmd(b'+PONG\r\n', 'PING')  # no leftover per-key frames
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'OFF')
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'ON', 'BCAST', 'PREFIX', 'a:', 'PREFIX', 'b:')
            a.cmd(b'+OK\r\n', 'MULTI')
            for key in ('b:2', 'a:2', 'b:1', 'a:1', 'a:1', 'c:1'):
                a.cmd(b'+QUEUED\r\n', 'INCR', key)
            a.cmd(array(*([b':1\r\n']*4 + [b':2\r\n', b':1\r\n'])), 'EXEC')
            for prefix in ('a:', 'b:'):
                a.read(array(bulk('invalidate'), array(bulk(prefix+'1'), bulk(prefix+'2')), push=True))
            a.cmd(b'+PONG\r\n', 'PING')
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'OFF')
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'ON', 'BCAST', 'NOLOOP')
            a.cmd(b'+OK\r\n', 'MSET', 'x', 1, 'y', 2)
            a.cmd(b'+PONG\r\n', 'PING')
            b.cmd(b'+OK\r\n', 'MSET', 'y', 3, 'x', 4)
            a.read(array(bulk('invalidate'), array(bulk('x'), bulk('y')), push=True))
            a.cmd(b'+PONG\r\n', 'PING')
            # RESP2 redirect carriage must preserve the grouped array too.
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'OFF')
            c = client()
            ident = c.cmd(None, 'CLIENT', 'ID')
            c.cmd(array(bulk('subscribe'), bulk('__redis__:invalidate'), b':1\r\n'), 'SUBSCRIBE', '__redis__:invalidate')
            a.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'ON', 'BCAST', 'REDIRECT', int(ident[1:-2]))
            a.cmd(b'+OK\r\n', 'MSET', 'z', 1, 'q', 2)
            c.read(array(bulk('message'), bulk('__redis__:invalidate'), array(bulk('q'), bulk('z'))))
        elif case == ROOTS[1]:
            for proto, verb, mode in itertools.product((2, 3), ('SUBSCRIBE', 'PSUBSCRIBE', 'SSUBSCRIBE'), ('OFF', 'SKIP')):
                c = client()
                if proto == 3: c.cmd(None, 'HELLO', 3)
                c.send('CLIENT', 'REPLY', mode)
                c.cmd(array(bulk(verb.lower()), bulk('ch'), b':1\r\n', push=proto == 3), verb, 'ch')
                publish = 'SPUBLISH' if verb == 'SSUBSCRIBE' else 'PUBLISH'
                a.cmd(b':1\r\n', publish, 'ch', 'hello')
                parts = [bulk('pmessage'), bulk('ch'), bulk('ch'), bulk('hello')] if verb == 'PSUBSCRIBE' else [bulk('smessage' if verb == 'SSUBSCRIBE' else 'message'), bulk('ch'), bulk('hello')]
                c.read(array(*parts, push=proto == 3))
                unsub = {'SUBSCRIBE':'UNSUBSCRIBE', 'PSUBSCRIBE':'PUNSUBSCRIBE', 'SSUBSCRIBE':'SUNSUBSCRIBE'}[verb]
                c.cmd(array(bulk(unsub.lower()), bulk('ch'), b':0\r\n', push=proto == 3), unsub, 'ch')
                c.cmd(array(bulk(unsub.lower()), b'_\r\n' if proto == 3 else b'$-1\r\n', b':0\r\n', push=proto == 3), unsub)
                c.cmd(b'+OK\r\n', 'CLIENT', 'REPLY', 'ON')
                c.cmd(b'+PONG\r\n', 'PING')
        elif case == ROOTS[2]:
            a.cmd(b'+OK\r\n', 'CONFIG', 'SET', 'notify-keyspace-events', 'Kt')
            b.cmd(array(bulk('psubscribe'), bulk('*'), b':1\r\n'), 'PSUBSCRIBE', '*')
            def event(key, name): b.read(array(bulk('pmessage'), bulk('*'), bulk('__keyspace@0__:'+key), bulk(name)))
            a.cmd(b'+OK\r\n', 'XGROUP', 'CREATE', 's', 'g', '$', 'MKSTREAM'); event('s','xgroup-create')
            a.cmd(bulk('1-0'), 'XADD', 's', '1-0', 'f', 'v'); event('s','xadd')
            tracker = client(); tracker.cmd(None, 'HELLO', 3)
            tracker.cmd(b'+OK\r\n', 'CLIENT', 'TRACKING', 'ON', 'BCAST', 'PREFIX', 's')
            a.cmd(None, 'XREADGROUP', 'GROUP', 'g', 'Alice', 'STREAMS', 's', '>'); event('s','xgroup-createconsumer')
            a.cmd(None, 'XCLAIM', 's', 'g', 'Mike', 0, '1-0', 'FORCE'); event('s','xgroup-createconsumer')
            a.cmd(None, 'XAUTOCLAIM', 's', 'g', 'Auto', 0, '0-0'); event('s','xgroup-createconsumer')
            a.cmd(None, 'XCLAIM', 's', 'g', 'Mike', 0, '1-0', 'FORCE')
            a.cmd(b':1\r\n', 'PUBLISH', 'fence', 'done')
            b.read(array(bulk('pmessage'), bulk('*'), bulk('fence'), bulk('done')))  # existing consumer emitted nothing
            d = client(); d.send('XREADGROUP','GROUP','g','Blocked','BLOCK',0,'STREAMS','s','>')
            event('s','xgroup-createconsumer')  # must arrive while the read is still blocked
            # Consumer metadata emits keyspace events without signalModifiedKey.
            # The received events witness completion; the real write below proves
            # this tracking connection is armed and able to receive invalidations.
            assert not select.select([tracker.sock], [], [], .15)[0], 'consumer creation invalidated tracking'
            a.cmd(bulk('2-0'),'XADD','s','2-0','f','v'); event('s','xadd')
            d.read(array(array(bulk('s'),array(array(bulk('2-0'),array(bulk('f'),bulk('v')))))))
            tracker.read(array(bulk('invalidate'), array(bulk('s')), push=True))
            tracker.cmd(b'+PONG\r\n', 'PING')
        else:
            a.cmd(b'+OK\r\n', 'CONFIG', 'SET', 'notify-keyspace-events', 'Ee')
            a.cmd(b'+OK\r\n', 'CONFIG', 'SET', 'maxmemory-policy', 'allkeys-lru')
            b.cmd(array(bulk('psubscribe'), bulk('*'), b':1\r\n'), 'PSUBSCRIBE', '*')
            a.cmd(b'+OK\r\n', 'SET', eviction_key, 'bar')
            a.cmd(b'+OK\r\n', 'CONFIG', 'SET', 'maxmemory', 1)
            b.read(array(bulk('pmessage'),bulk('*'),bulk('__keyevent@0__:evicted'),bulk(eviction_key)))
            a.cmd(b'+OK\r\n', 'CONFIG', 'SET', 'maxmemory', 0)
            a.cmd(b':0\r\n', 'DBSIZE')


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',choices=ROOTS,required=True)
    p.add_argument('--binary',required=True);p.add_argument('--oracle',required=True)
    p.add_argument('--cores',required=True);p.add_argument('--port',type=int,required=True)
    p.add_argument('--ratio',default='6:2');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    failures=0
    for binary,oracle in ((args.oracle,True),(args.binary,False)):
        run=Run(args,binary,oracle)
        legs=[('redis','oracle',16,1,0)] if oracle else itertools.product(('1s','2s'),('uring','epoll'),(1,16),(0,1),(0,1))
        variants=('foo','') if args.case==ROOTS[3] else ('foo',)
        for (mode,engine,db,atomic,local),key in itertools.product(legs,variants):
            label=f'{mode}-{engine}-db{db}-a{atomic}-r{local}'
            if args.case==ROOTS[3]:label+='-'+('foo' if key else 'empty-key')
            extra=['--enable-debug-command','yes']
            if not oracle: extra += ['--net-io',engine,'--databases',str(db),'--atomic',str(atomic),'--read-local',str(local)]
            rows=[]
            try:
                with Server(run,label,mode,extra=extra): probe(args.case,args.port,rows,key)
                run.check(label,True,True)
            except Exception:
                traceback.print_exc();run.check(label,False,True)
            (run.path/(label+'-wire.json')).write_text(json.dumps(rows,indent=2)+'\n')
        failures+=run.finish()
    return int(failures != 0)

if __name__=='__main__': raise SystemExit(main())
