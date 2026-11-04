#!/usr/bin/env python3
"""Half-closed accepted input must drain across a bounded FLIP decision."""
import argparse
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import socket
import select
import threading
import time
import traceback

from _lib import Conn, RespError, encode, info
from cfgfix2 import Server


class Unarmed(Exception):
    pass


def trial(a, engine, atomic, databases, stays, attempt):
    label = f'{engine}-a{atomic}-d{databases}-stay{int(stays)}-try{attempt}'
    result = dict(label=label, passed=False)
    try:
        with Server(a, label, '2s', engine, extra=['--atomic', str(atomic),
                '--databases', str(databases), '--enable-debug-command', 'yes',
                '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']) as server, ExitStack() as stack:
            def connection(owner):
                for _ in range(128):
                    c = stack.enter_context(closing(Conn('127.0.0.1', a.port, timeout=5)))
                    if c.must('DEBUG', 'IO-THREAD') == owner:
                        return c
                raise AssertionError('required IO placement did not arm')
            held, control, observer = connection(4), connection(0), connection(0)
            identity = held.must('CLIENT', 'ID')
            result['client'] = identity
            refused_before = int(info(observer, 'stats')['flip_refused'])
            count = 65
            held.raw(encode('DEBUG', 'SLEEP', '.1') + encode('INCR', 'wave15:fin:flip')*count)
            held.sock.shutdown(socket.SHUT_WR)
            # DEBUG SLEEP is a synchronous acknowledged control, not a cancellable
            # BLPOP. Its buffered suffix must survive both FIN and FLIP admission.
            until = time.monotonic()+1
            while True:
                # FIN_WAIT2 proves the server's TCP stack accepted our FIN.
                if held.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 1)[0] == 5:
                    break
                if time.monotonic() >= until:
                    raise Unarmed('accepted FIN window did not arm')
            # A readable first reply would mean the sleep control already ended.
            if select.select([held.sock],[],[],0)[0]:
                raise Unarmed('sleep/FIN window did not arm')
            result['armed'] = True
            started = time.monotonic()
            control.send('FLIP', *( (7,1) if stays else (1,7) ))
            failure = []
            def drain():
                try:
                    assert held.read() == b'OK'
                    for i in range(1,count+1):
                        assert held.read() == i, i
                    assert held.file.read(1) == b'', 'EOF after all accepted replies'
                    result['drained'] = count
                except Exception:
                    failure.append(traceback.format_exc())
            reader = threading.Thread(target=drain)
            reader.start()
            reply = control.read()
            result['flip_seconds'] = time.monotonic()-started
            result['flip'] = str(reply) if isinstance(reply, RespError) else reply.decode()
            assert result['flip_seconds'] < 1, result
            assert reply == b'OK' or (isinstance(reply, RespError) and reply.message in (
                b'ERR FLIP refused: converting IO owns a blocked connection',
                b'ERR FLIP refused: a pinned connection closed',
                b'ERR FLIP refused: a connection is draining its end of stream')), reply
            reader.join(6)
            assert not reader.is_alive() and not failure, failure
            assert observer.must('GET','wave15:fin:flip') == str(count).encode()
            assert observer.must('PING') == b'PONG'
            assert int(info(observer, 'stats')['flip_refused'])-refused_before == int(isinstance(reply,RespError))
            result['passed'] = True
    except Unarmed as error:
        result['unarmed'] = str(error)
    except Exception:
        result['error'] = traceback.format_exc()
    print(json.dumps(result), flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','oracle','cores'):p.add_argument('--'+name,required=True)
    p.add_argument('--ratio',default='6:2')
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--single',action='store_true')
    a=p.parse_args();os.environ['LC_ALL']='C';a.output.mkdir(parents=True,exist_ok=False)
    attempts=[]; rows=[]
    for e in (['epoll'] if a.single else ['epoll','uring']):
        for at in ([1] if a.single else [0,1]):
            for db in ([16] if a.single else [1,16]):
                for stays in ([True] if a.single else [True,False]):
                    for attempt in range(16):
                        row=trial(a,e,at,db,stays,attempt);attempts.append(row)
                        if 'unarmed' not in row:break
                    rows.append(row)
    (a.output/'results.json').write_text(json.dumps(dict(rows=rows,attempts=attempts),indent=2)+'\n')
    return int(not all(r['passed'] for r in rows))


if __name__=='__main__':raise SystemExit(main())
