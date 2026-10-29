#!/usr/bin/env python3
"""Finite EXEC correctness schedules and post-join counters; no rate measurements."""
from contextlib import ExitStack
import json
import select
from pathlib import Path
import sys
import time
from authfix import Resp
from _lib import encode, lbsignals
from shutdown_report import load_report


def wb_window(admin, client):
    for attempt in range(3):
        names=['exec1s-wb:'+str(attempt)+':'+str(i) for i in range(256)]
        routes=admin.cmd('DEBUG','SHARDS',*names)
        pair=[names[0],next(k for k,r in zip(names,routes) if r[1]!=routes[0][1])]
        assert admin.cmd('MSET',pair[0],0,pair[1],0)==b'OK'
        assert admin.cmd('DEBUG','TXN-PLACE-DEFER',600000)==b'OK'
        def polls():
            return next(int(line.split(':')[1]) for line in admin.cmd('INFO','stats').decode().splitlines()
                        if line.startswith('atomic_txn_fast_polls:'))
        before=polls(); began=time.monotonic(); armed=False
        client.sock.sendall(encode('MULTI')+encode('INCR',pair[0])+encode('INCR',pair[1])+encode('EXEC'))
        try:
            while time.monotonic()-began < .3:
                if polls()>before:
                    armed=time.monotonic()-began < .3
                    break
            if armed:
                assert not select.select([client.sock],[],[],0)[0], 'own block escaped before its EXEC'
                assert admin.cmd('PING')==b'PONG', 'other client must remain serviceable'
                assert not select.select([client.sock],[],[],0)[0], 'other client reply must precede the held EXEC'
            assert client.read()==b'OK' and client.read()==b'QUEUED' and client.read()==b'QUEUED'
            assert client.read()==[1,1]
        finally:
            assert admin.cmd('DEBUG','TXN-PLACE-DEFER',0)==b'OK'
        if armed:
            return
    raise AssertionError('WB hold window never opened on three fresh states')


def live(port, case, wb=False):
    with ExitStack() as stack:
        clients = [stack.enter_context(Resp(port)) for _ in range(64)]
        admin = clients[0]
        for c in clients:
            assert c.cmd('PING') == b'PONG'
        snap = lbsignals(admin)
        assert sum(t.clients for t in snap.threads) == 64, '64 accepted clients must be visible'
        if case == 'plain':
            for i,c in enumerate(clients):
                assert c.cmd('SET', 'exec1s-plain:'+str(i), i) == b'OK'
                assert c.cmd('GET', 'exec1s-plain:'+str(i)) == str(i).encode()
            return
        names = ['exec1s-key:'+str(i) for i in range(1024)]
        routes = admin.cmd('DEBUG', 'SHARDS', *names)
        same = [k for k,r in zip(names,routes) if r[0] == routes[0][0]]
        other = next(k for k,r in zip(names,routes) if r[1] != routes[0][1])
        assert len(same)>=18
        # An interactive client must get MULTI/QUEUED before sending EXEC.
        assert admin.cmd('MULTI') == b'OK'
        assert admin.cmd('INCR', 'exec1s-interactive') == b'QUEUED'
        assert admin.cmd('EXEC') == [1]
        for pair in (same[:2], [same[0],other]):
            assert admin.cmd('MSET', pair[0],0,pair[1],0) == b'OK'
            expected = set(range(1,65))
            for c in clients:
                c.sock.sendall(encode('MULTI')+encode('INCR',pair[0])+encode('INCR',pair[1])+encode('EXEC'))
            seen=set()
            for c in clients:
                assert c.read()==b'OK'
                assert c.read()==b'QUEUED' and c.read()==b'QUEUED'
                answer=c.read()
                assert isinstance(answer,list) and len(answer)==2 and answer[0]==answer[1],answer
                seen.add(answer[0])
            assert seen==expected, seen
            assert admin.cmd('MGET',*pair)==[b'64',b'64']
        # A split owner can run ordinary batch cleanup between two-key EXECs.
        # Sixteen distinct keys in ONE owner task deterministically cross X2's
        # eight-record threshold before that task reaches eager reclamation.
        # This is a finite arming schedule, independent of client arrival speed.
        keys=same[2:18]
        assert admin.cmd('DEL',*keys)==0
        admin.sock.sendall(encode('MULTI')+b''.join(encode('INCR',k) for k in keys)+encode('EXEC'))
        assert admin.read()==b'OK'
        for _ in keys: assert admin.read()==b'QUEUED'
        assert admin.read()==[1]*len(keys)
        assert admin.cmd('MGET',*keys)==[b'1']*len(keys)
        if wb: wb_window(admin,clients[1])
        stats=admin.cmd('INFO','stats').decode()
        assert 'atomic_txn_order_violations:0\r\n' in stats


def shutdown(path,mode,case,wb):
    report=load_report(path)
    rows=[r['exec1s'] for r in report['threads']]
    totals={k:sum(r[k] for r in rows) for k in rows[0]}
    assert totals['clients_peak']>=64, totals
    if mode=='1s':
        assert totals['owner_passes']>0 and totals['io_enters']>0, totals
        if case=='plain':
            assert totals['extra_passes']==0, totals
        else:
            assert totals['extra_passes']>0, totals
        # The fixed plain exchange includes no executor-side persistence or wake
        # traffic. Startup/shutdown enters are bounded by the long idle spin.
        assert totals['ex_enters'] <= totals['owner_passes']*.05+64, totals
    else:
        assert totals['extra_passes']==0, totals
    if case!='plain':
        assert totals['eager_collapses']>0 and totals['blind_clear']>0, totals
        if wb: assert totals['wb_exec_holds']>0, totals
    print(json.dumps(dict(mode=mode,case=case,counters=totals),sort_keys=True))

if __name__=='__main__':
    if sys.argv[1]=='shutdown':
        shutdown(sys.argv[2],sys.argv[3],sys.argv[4], '--wb' in sys.argv[5:])
    else: live(int(sys.argv[1]),sys.argv[2], '--wb' in sys.argv[3:])
