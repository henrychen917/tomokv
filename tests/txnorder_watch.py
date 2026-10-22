#!/usr/bin/env python3
"""Redis-7.4 WATCH oracle cases for FLUSH, SWAPDB and blocking command serves.

The asynchronous producer/serve window and post-CAS window are covered by
txnorder_watch_unit.cc; this battery checks their exact public replies.
"""
import argparse
import _lib


def main():
    p=argparse.ArgumentParser();p.add_argument('host');p.add_argument('port',type=int)
    p.add_argument('--databases',type=int,default=16);p.add_argument('--only',default='flush,serve')
    a=p.parse_args();only=set(a.only.split(','));admin=_lib.Conn(a.host,a.port)
    def run(name, setup, mutation, dirty, db=0):
        admin.must('SELECT',0);admin.must('FLUSHALL')
        setup()
        with _lib.Conn(a.host,a.port) as watch:
            watch.must('SELECT',db);assert watch.must('WATCH','watched')==b'OK'
            mutation()
            assert watch.must('MULTI')==b'OK'
            assert watch.must('PING')==b'QUEUED'
            result=watch.must('EXEC');expected=None if dirty else [b'PONG']
            assert result==expected,(name,result,expected)
            print('PASS',name,repr(result),flush=True)
    if 'flush' in only:
        for command in ['FLUSHDB','FLUSHALL']:
            for style in [(),('SYNC',),('ASYNC',)]:
                run(command+' '+str(style)+' absent',lambda:None,
                    lambda:admin.must(command,*style),False)
                run(command+' '+str(style)+' present',lambda:admin.must('SET','watched','v'),
                    lambda:admin.must(command,*style),True)
        if a.databases>1:
            def other():
                admin.must('SELECT',1);admin.must('SET','watched','other');admin.must('SELECT',0)
            run('FLUSHDB does not dirty another database',other,lambda:admin.must('FLUSHDB'),False,1)
            run('FLUSHALL dirties another database',other,lambda:admin.must('FLUSHALL'),True,1)
            for left,right in [(False,False),(True,False),(False,True),(True,True)]:
                def setup():
                    if left:admin.must('SET','watched','left')
                    if right:other()
                run('SWAPDB existence '+str((left,right)),setup,
                    lambda:admin.must('SWAPDB',0,1),left or right)
            def swapped():
                other();admin.must('SWAPDB',0,1)
            run('FLUSHDB after SWAPDB follows the new physical database',swapped,
                lambda:admin.must('FLUSHDB'),True)
            run('FLUSHDB after absent SWAPDB stays clean',lambda:admin.must('SWAPDB',0,1),
                lambda:admin.must('FLUSHDB'),False)
    if 'serve' in only:
        for command in [('BLPOP','watched',1),('BRPOP','watched',1),
                        ('BLMPOP',1,1,'watched','LEFT'),
                        ('BZPOPMIN','watched',1),('BZPOPMAX','watched',1),
                        ('BZMPOP',1,1,'watched','MIN'),
                        ('BRPOPLPUSH','watched','dest',1),
                        ('BLMOVE','watched','dest','LEFT','RIGHT',1)]:
            zset=command[0].startswith('BZ')
            run(command[0]+' signalModifiedKey',
                lambda:admin.must(*(('ZADD','watched',1,'v') if zset else ('LPUSH','watched','v'))),
                lambda:admin.must(*command),True)
        # Redis does not signalModifiedKey for XREADGROUP's PEL bookkeeping.
        def stream():
            admin.must('XADD','watched','1-0','f','v')
            admin.must('XGROUP','CREATE','watched','g','0')
        run('XREADGROUP metadata preserves WATCH',stream,
            lambda:admin.must('XREADGROUP','GROUP','g','c','STREAMS','watched','>'),False)
    admin.close()


if __name__=='__main__':main()
