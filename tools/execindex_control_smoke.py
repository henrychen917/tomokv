#!/usr/bin/env python3
"""Bounded correctness smoke of the exact-image control pair, no load generator."""
import argparse,hashlib,itertools,json,socket,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PORT=46890
class Resp:
    def __init__(self):
        self.socket=socket.create_connection(('127.0.0.1',PORT),timeout=20);self.file=self.socket.makefile('rb')
    def read(self):
        line=self.file.readline();kind=line[:1];value=line[1:-2]
        if kind==b'+':return value
        if kind==b':':return int(value)
        if kind==b'$':
            n=int(value)
            if n<0:return None
            data=self.file.read(n);assert self.file.read(2)==b'\r\n';return data
        if kind==b'*':return None if int(value)<0 else [self.read() for _ in range(int(value))]
        raise AssertionError(line)
    def cmd(self,*args):
        data=[str(a).encode() for a in args]
        self.socket.sendall(b'*'+str(len(data)).encode()+b'\r\n'+b''.join(b'$'+str(len(a)).encode()+b'\r\n'+a+b'\r\n' for a in data));return self.read()
    def close(self):self.file.close();self.socket.close()
def main():
    global PORT
    parser=argparse.ArgumentParser();parser.add_argument('--visits',action='store_true')
    parser.add_argument('--cores', default='96-103');parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--artifacts', type=Path, default=ROOT/'build/execindex')
    parser.add_argument('--output', type=Path)
    args=parser.parse_args();PORT=args.port
    artifacts=args.artifacts.resolve()
    rows=[]
    arms=['PRE-visits','POST-visits'] if args.visits else ['POST-layout','PAD-A']
    for arm,mode,engine,db in itertools.product(arms,['1s','2s'],['uring','epoll'],[1,16]):
        with socket.socket() as guard:guard.bind(('127.0.0.1',PORT))
        path=artifacts/arm;directory=artifacts/'control-data'/f'{arm}-{mode}-{engine}-{db}';directory.mkdir(parents=True,exist_ok=True)
        cmd=['taskset','-c',args.cores,str(path),'--port',str(PORT),'--bind','127.0.0.1','--shards','16','--thread-mode','fused' if mode=='1s' else 'split','--net-io',engine,'--databases',str(db),'--atomic','1','--key-lb','0','--client-lb','0','--flip-auto','0','--save','','--dir',str(directory)]
        if mode=='2s':cmd+=['--ratio','6:2']
        if args.visits:cmd+=['--enable-debug-command','yes']
        clients=[]
        with (directory/'server.log').open('w') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            try:
                end=time.monotonic()+30
                while True:
                    assert proc.poll() is None,'early server exit'
                    try:c=Resp();clients.append(c);break
                    except OSError:
                        assert time.monotonic()<end,'boot timeout';time.sleep(.05)
                d=Resp();clients.append(d)
                before=c.cmd('DEBUG','TXN-REGISTRY-VISITS') if args.visits else None
                assert c.cmd('MSET','execindex:a',0,'execindex:b',0)==b'OK'
                assert c.cmd('MULTI')==b'OK'
                assert c.cmd('INCR','execindex:a')==b'QUEUED'
                assert c.cmd('INCR','execindex:b')==b'QUEUED'
                assert c.cmd('EXEC')==[1,1]
                assert c.cmd('MGET','execindex:a','execindex:b')==[b'1',b'1']
                assert c.cmd('WATCH','execindex:a')==b'OK'
                assert d.cmd('INCR','execindex:a')==2
                assert c.cmd('MULTI')==b'OK'
                assert c.cmd('INCR','execindex:b')==b'QUEUED'
                assert c.cmd('EXEC') is None
                info=c.cmd('INFO').decode();assert 'atomic_txn_order_violations:0\r\n' in info
                after=c.cmd('DEBUG','TXN-REGISTRY-VISITS') if args.visits else None
                if args.visits:assert after>before,'registry visit counter never fired'
            finally:
                for c in clients:c.close()
                proc.terminate()
                try:rc=proc.wait(timeout=20)
                except subprocess.TimeoutExpired:proc.kill();proc.wait();raise
                assert rc==0,rc
        rows.append(dict(arm=arm,mode=mode,engine=engine,databases=db,pass_=True,visits_before=before,visits_after=after,command=cmd,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (args.output or ROOT/('docs/execindex/debug-smoke.json' if args.visits else 'docs/execindex/pad-smoke.json')).write_text(json.dumps(rows,indent=2)+'\n');print('PASS',len(rows),'control-image correctness cells')
if __name__=='__main__':main()
