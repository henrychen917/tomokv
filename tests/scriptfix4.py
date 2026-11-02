#!/usr/bin/env python3
"""Promoted round-5 T1/T8b, T5/T6, T31b, T6-T9 and T19-T21 witnesses.

Raw RESP probes and persistence window assertions from round5-read/tests;
resource selection is parameterized and every defect is a failing assertion.
No performance verdict. All subprocesses inherit LC_ALL=C.
"""
import argparse, contextlib, hashlib, json, os, resource, select, signal, socket
import subprocess, threading, time, traceback
from pathlib import Path

class Error(str): pass


class Push(list): pass


def plain(x):
    if isinstance(x, Error): return {'error': str(x)}
    if isinstance(x, Push): return {'push': [plain(v) for v in x]}
    if isinstance(x, bytes): return x.decode('utf-8', 'backslashreplace')
    if isinstance(x, list): return [plain(v) for v in x]
    if isinstance(x, dict): return {str(plain(k)): plain(v) for k,v in x.items()}
    return x


def enc(args):
    args = [a if isinstance(a, bytes) else str(a).encode() for a in args]
    return b'*%d\r\n'%len(args)+b''.join(b'$%d\r\n'%len(a)+a+b'\r\n' for a in args)


class Conn:
    def __init__(self, port):
        self.s=socket.create_connection(('127.0.0.1',port),2); self.s.settimeout(2)
        self.buf=bytearray(); self.pushes=[]
    def __enter__(self): return self
    def __exit__(self,*a): self.s.close()
    def close(self): self.s.close()
    def take(self,n):
        while len(self.buf)<n:
            b=self.s.recv(65536)
            if not b: raise EOFError('peer closed')
            self.buf.extend(b)
        out=bytes(self.buf[:n]); del self.buf[:n]; return out
    def line(self):
        while b'\r\n' not in self.buf:
            b=self.s.recv(65536)
            if not b: raise EOFError('peer closed')
            self.buf.extend(b)
        n=self.buf.index(b'\r\n'); return self.take(n+2)[:-2]
    def read(self):
        tag=self.take(1); v=self.line()
        if tag==b'+': return v
        if tag==b'-': return Error(v.decode())
        if tag==b':': return int(v)
        if tag in (b'$', b'='):
            n=int(v)
            if n<0: return None
            b=self.take(n); assert self.take(2)==b'\r\n'; return b
        if tag in (b'*', b'~', b'>'):
            n=int(v)
            if n<0: return None
            out=[self.read() for _ in range(n)]; return Push(out) if tag==b'>' else out
        if tag==b'%': return {self.read():self.read() for _ in range(int(v))}
        if tag==b'_': return None
        if tag==b'#': return v==b't'
        if tag==b',': return float(v)
        if tag==b'(': return int(v)
        raise ValueError((tag,v))
    def cmd(self,*args):
        self.s.sendall(enc(args))
        while True:
            r=self.read()
            if isinstance(r,Push): self.pushes.append(r)
            else: return r
    def pipe(self,commands):
        self.s.sendall(b''.join(enc(c) for c in commands)); out=[]
        while len(out)<len(commands):
            r=self.read()
            if isinstance(r,Push): self.pushes.append(r)
            else: out.append(r)
        return out
    def drain(self,timeout=.15):
        out=self.pushes; self.pushes=[]; deadline=time.monotonic()+timeout
        while self.buf or select.select([self.s],[],[],max(0,deadline-time.monotonic()))[0]:
            out.append(self.read())
            if time.monotonic()>=deadline and not self.buf: break
        return out


@contextlib.contextmanager
def server(engine, mode='1s', extra=(), port=None):
    port=port or (PORT_BASE if engine=='tomo' else PORT_BASE+1)
    assert ARGS.port <= port <= ARGS.port + 1
    check=subprocess.run(['ss','-ltnH','sport','=',str(port)],capture_output=True,text=True,check=True)
    assert not check.stdout.strip(), f'port {port} occupied'
    directory=ROOT/'runtime'/f'{engine}-{mode}-{os.getpid()}-{time.time_ns()}'
    directory.mkdir(parents=True)
    cmd=['taskset','-c',ARGS.cores, TOMO if engine=='tomo' else REDIS,
         '--bind','127.0.0.1','--port',str(port),'--save','','--appendonly','no','--dir',str(directory)]
    if engine=='tomo':
        cmd += ['--shards','16','--net-io',ARGS.engine,'--thread-mode',mode,'--read-local','0','--flip-auto','0','--databases','16','--enable-debug-command','yes']
        # Function-library upvalues are per executor; keep each key on one owner.
        cmd += ['--key-lb','0','--client-lb','0']
        if mode=='2s': cmd += ['--ratio',ARGS.ratio]
    cmd+=list(extra)
    with (directory/'server.log').open('w') as log:
        p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        print(json.dumps({'lifecycle':'start','engine':engine,'mode':mode,'pid':p.pid,'command':cmd,'log':str(directory/'server.log')}),flush=True)
        try:
            deadline=time.monotonic()+12
            while True:
                if p.poll() is not None: raise RuntimeError((directory/'server.log').read_text())
                try:
                    with Conn(port) as c: pong=c.cmd('PING')
                    assert pong==b'PONG' or isinstance(pong,Error)
                    break
                except (ConnectionRefusedError,TimeoutError):
                    if time.monotonic()>deadline: raise
                    time.sleep(.03)
            yield port
        finally:
            if p.poll() is None:
                subprocess.run(['kill',str(p.pid)],check=True)
                try: p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    subprocess.run(['kill','-KILL',str(p.pid)],check=True); p.wait(timeout=3)
            for attempt in range(100):
                closed=subprocess.run(['ss','-ltnH','sport','=',str(port)],capture_output=True,text=True,check=True)
                if not closed.stdout.strip(): break
                time.sleep(.01)
            print(json.dumps({'lifecycle':'stop','pid':p.pid,'exit':p.returncode,'port':port,'ss':closed.stdout.strip(),'closed':not closed.stdout.strip()}),flush=True)
            assert not closed.stdout.strip()


def keys(frames):
    result=[]
    for f in frames:
        if isinstance(f,Push) and f and f[0]==b'invalidate':
            result.extend(f[1] if f[1] is not None else [None])
    return result


def tracking_probe(port,engine,mode):
    out={}
    with Conn(port) as c, Conn(port) as w:
        assert c.cmd('HELLO',3)
        body="return redis.call('GET',KEYS[1])"
        sha=w.cmd('SCRIPT','LOAD',body)
        robody='#!lua flags=no-writes\n'+body
        rosha=w.cmd('SCRIPT','LOAD',robody)
        assert w.cmd('FUNCTION','LOAD',"#!lua name=cc5tracking\nredis.register_function('cc5read',function(keys,args) return redis.call('GET',keys[1]) end); redis.register_function{function_name='cc5ro',callback=function(keys,args) return redis.call('GET',keys[1]) end,flags={'no-writes'}}")==b'cc5tracking'
        cases=[('eval',['EVAL',body]),('evalsha',['EVALSHA',sha]),
               ('eval_shebang',['EVAL',robody]),('evalsha_shebang',['EVALSHA',rosha]),
               ('fcall',['FCALL','cc5read']),('fcall_flag',['FCALL','cc5ro']),
               ('eval_ro',['EVAL_RO',body]),('evalsha_ro',['EVALSHA_RO',sha]),
               ('fcall_ro',['FCALL_RO','cc5ro'])]
        for name,command in cases:
            key='cc5:script:'+name
            assert c.cmd('CLIENT','TRACKING','OFF')==b'OK'
            assert c.cmd('CLIENT','TRACKING','ON')==b'OK'
            assert w.cmd('SET',key,'before')==b'OK'
            assert c.cmd('GET',key)==b'before'
            assert w.cmd('SET',key,'armed')==b'OK'
            armed=c.drain(.2)
            assert key.encode() in keys(armed),(engine,mode,name,'arming control absent',armed)
            value=c.cmd(*command,1,key)
            assert value==b'armed',(name,value)
            assert w.cmd('SET',key,'after')==b'OK'
            observed=c.drain(.3)
            assert c.cmd('GET',key)==b'after'
            assert w.cmd('SET',key,'final')==b'OK'
            positive=c.drain(.2)
            assert key.encode() in keys(positive),(engine,mode,name,'delivery control absent',positive)
            invalidated=key.encode() in keys(observed)
            out[name]={'returned':value,'invalidated':invalidated,'observed':observed,'arming':armed,'positive':positive}
            if engine=='redis': assert invalidated,(name,observed)
    return out


def inval_keys(frames):
    out = []
    for f in frames:
        if isinstance(f, Push) and f and f[0] == b'invalidate':
            out.extend(f[1] if f[1] is not None else [None])
    return out


def rearm(c):
    assert c.cmd('CLIENT', 'TRACKING', 'OFF') == b'OK'
    assert c.cmd('CLIENT', 'TRACKING', 'ON') == b'OK'


def delivery_control(c, w, key):
    rearm(c)
    assert w.cmd('SET', key, 'c0') == b'OK'
    assert c.cmd('GET', key) == b'c0'
    assert w.cmd('SET', key, 'c1') == b'OK'
    got = inval_keys(c.drain(.25))
    return key.encode() in got


def overreg_probe(port, engine, mode):
    out = {}
    with Conn(port) as c, Conn(port) as w:
        assert c.cmd('HELLO', 3)
        out['control_before'] = delivery_control(c, w, 'cc5t6:ctl')
        # Case A: writable EVAL reads KEYS[1] only.
        rearm(c)
        assert w.cmd('SET', 'cc5t6:a', 'v1') == b'OK'
        out['A_reply'] = c.cmd('EVAL', "return redis.call('GET',KEYS[1])", 1, 'cc5t6:a')
        assert w.cmd('SET', 'cc5t6:a', 'v2') == b'OK'
        out['A_invalidated'] = inval_keys(c.drain(.3))
        # Case B: EVAL_RO reads nothing; one declared key and one ARGV value that names a key.
        rearm(c)
        assert w.cmd('SET', 'cc5t6:b', 'v1') == b'OK'
        assert w.cmd('SET', 'cc5t6:argv', 'v1') == b'OK'
        out['B_reply'] = c.cmd('EVAL_RO', "return 1", 1, 'cc5t6:b', 'cc5t6:argv')
        assert w.cmd('SET', 'cc5t6:b', 'v2') == b'OK'
        assert w.cmd('SET', 'cc5t6:argv', 'v2') == b'OK'
        out['B_invalidated'] = inval_keys(c.drain(.3))
        out['control_after'] = delivery_control(c, w, 'cc5t6:ctl2')
        out['trackinginfo'] = c.cmd('CLIENT', 'TRACKINGINFO')
    return out


def blocked_probe(port, engine, mode):
    out = {}
    with Conn(port) as t, Conn(port) as w, Conn(port) as a:
        w.cmd('FLUSHALL')
        t.cmd('HELLO', 3); t.cmd('CLIENT', 'TRACKING', 'ON')
        for rnd in range(3):
            key = f'tb{rnd}'
            w.cmd('XADD', key, '1-0', 'f', 'v')
            t.s.sendall(enc(['XREAD', 'BLOCK', '3000', 'STREAMS', key, '$']))
            end = time.monotonic() + 2
            while time.monotonic() < end and 'blocked_clients:1' not in a.cmd('INFO', 'clients').decode():
                time.sleep(0.02)
            assert 'blocked_clients:1' in a.cmd('INFO', 'clients').decode(), 'XREAD never parked'
            w.cmd('XADD', key, '2-0', 'f', 'wake')
            t.s.settimeout(2)
            reply = None
            pushes = []
            while reply is None:
                r = t.read()
                if isinstance(r, Push): pushes.append(r)
                else: reply = r
            before_after = pushes + t.drain(0.3)          # caused by the waking XADD 2-0
            w.cmd('XADD', key, '3-0', 'f', 'after')
            after = t.drain(0.3)                          # caused by the later XADD 3-0
            def inv(frames):
                return [[k.decode() for k in f[1]] if f[1] else None
                        for f in frames if isinstance(f, Push) and f[0] == b'invalidate']
            out[f'round{rnd}'] = {'reply_ok': isinstance(reply, (dict, list)),
                                  'woken_reply': reply,
                                  'inv_from_waking_xadd': inv(before_after),
                                  'inv_from_later_xadd': inv(after)}
        w.cmd('XADD', 'tbctl', '1-0', 'f', 'v')
        t.cmd('XREAD', 'STREAMS', 'tbctl', '0')
        w.cmd('XADD', 'tbctl', '2-0', 'f', 'v')
        out['control_nonblocking_xread_invalidated'] = any(
            isinstance(f, Push) and f[0] == b'invalidate' and f[1] and b'tbctl' in f[1] for f in t.drain(0.3))
    return out


def clean(v):
    if isinstance(v, bytes):
        return v.decode(errors='backslashreplace') if len(v) < 500 else {'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()}
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    if isinstance(v, dict): return {str(k):clean(x) for k,x in v.items()}
    return v


def emit(event, **kw):
    row = {'event':event, **clean(kw)}
    print(json.dumps(row), flush=True)
    with (OUT/'events.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')


class Resp:
    def __init__(self, port, timeout=5):
        self.s = socket.create_connection(('127.0.0.1',port), timeout)
        self.f = self.s.makefile('rb')
    @staticmethod
    def wire(args):
        parts=[x if isinstance(x,bytes) else str(x).encode() for x in args]
        return b'*%d\r\n'%len(parts)+b''.join(b'$%d\r\n'%len(x)+x+b'\r\n' for x in parts)
    def send(self,*args): self.s.sendall(self.wire(args))
    def read(self):
        l=self.f.readline()
        if not l: raise EOFError('connection closed')
        t,b=l[:1],l[1:-2]
        if t==b'+': return b
        if t==b'-': return {'error':b.decode(errors='replace')}
        if t==b':': return int(b)
        if t==b'$':
            n=int(b)
            if n<0: return None
            data=self.f.read(n); assert len(data)==n and self.f.read(2)==b'\r\n'; return data
        if t==b'*':
            n=int(b); return None if n<0 else [self.read() for _ in range(n)]
        raise AssertionError(l)
    def cmd(self,*args): self.send(*args); return self.read()
    def info(self, section='persistence'):
        data=self.cmd('INFO',section)
        assert isinstance(data,bytes), data
        return dict(l.split(':',1) for l in data.decode().splitlines() if ':' in l)
    def close(self): self.f.close(); self.s.close()


class Server:
    serial=0
    def __init__(self, extra=(), data=None, trace=None, expect_ready=True, oracle=None, single=False, fsize=None):
        Server.serial+=1
        self.data=Path(data or OUT/'data'); self.data.mkdir(parents=True,exist_ok=True)
        self.port=ARGS.port
        self.oracle=ARGS.oracle if oracle is None else oracle
        assert not self.listening(), 'port already occupied'
        binary=REDIS if self.oracle else BIN
        argv=['taskset','-c',CPUS,binary,'--bind','127.0.0.1','--port',str(self.port),'--save','','--appendonly','no','--dir',str(self.data),'--enable-debug-command','yes']
        if not self.oracle:
            argv+=['--thread-mode',ARGS.mode,'--shards','16','--net-io',ARGS.engine,
                   '--read-local','0','--reorder','0','--key-lb','0','--client-lb','0',
                   '--flip-auto','0','--databases','16']
            if ARGS.mode == '2s': argv += ['--ratio', ARGS.ratio]
        argv+=list(extra)
        self.tracepath=OUT/f'trace-{Server.serial}'
        if trace: argv=['strace','-f','-yy','-o',str(self.tracepath),'-e','trace=fsync,fdatasync,rename,unlink,openat,close','-e',trace]+argv
        self.logpath=OUT/f'server-{Server.serial}.log'; self.log=self.logpath.open('wb')
        def limits():
            resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            if fsize:
                resource.setrlimit(resource.RLIMIT_FSIZE,(fsize,fsize)); signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
        env=dict(os.environ,LC_ALL='C'); env.pop('TOMO_AOF_ACK_WINDOW',None)
        self.p=subprocess.Popen(argv,stdout=self.log,stderr=subprocess.STDOUT,env=env,preexec_fn=limits)
        self.pid=self.p.pid; self.c=None; self.ready=False; self.stopped=False
        ACTIVE.append(self)
        end=time.monotonic()+12
        while self.p.poll() is None and time.monotonic()<end:
            try:
                c=Resp(self.port,.4)
                if c.cmd('PING')==b'PONG':
                    self.pid=int(c.info('server')['process_id']); self.c=c; self.c.s.settimeout(8); self.ready=True; break
                c.close()
            except (OSError,EOFError): pass
            time.sleep(.02)
        if not self.ready and trace:
            try:
                children=Path(f'/proc/{self.p.pid}/task/{self.p.pid}/children').read_text().split()
                if len(children)==1: self.pid=int(children[0])
            except FileNotFoundError: pass
        emit('boot',argv=argv,pid=self.pid,launcher_pid=self.p.pid,ready=self.ready,exit=self.p.poll(),log=str(self.logpath))
        if expect_ready: assert self.ready,self.logpath.read_text(errors='replace')[-2500:]
    def listening(self):
        return subprocess.check_output(['ss','-ltnH',f'sport = :{self.port}'],text=True).strip()
    def stop(self, sig=signal.SIGTERM):
        if self.stopped: return
        if self.c:
            self.c.close(); self.c=None
        if self.p.poll() is None:
            os.kill(self.pid,sig)
            try: self.p.wait(12)
            except subprocess.TimeoutExpired:
                emit('stop_timeout',pid=self.pid); os.kill(self.pid,signal.SIGKILL); self.p.wait(5)
        deadline=time.monotonic()+3
        while self.listening() and time.monotonic()<deadline: time.sleep(.02)
        state=self.listening(); self.log.close(); self.stopped=True
        emit('stopped',pid=self.pid,exit=self.p.returncode,ss=state)
        assert not state
    def __enter__(self): return self
    def __exit__(self,*_): self.stop()



def lib(name, value):
    return ('#!lua name=' + name + '\nredis.register_function("' + name +
            '", function(keys,args) return ' + str(value) + ' end)').encode()


def late_commands(c, kind, n):
    """Arm one registry mutation kind on n connections; returns (name, argv, OK reply)."""
    if kind == 'load':
        return [(f'late{i}', ['FUNCTION', 'LOAD', lib(f'late{i}', 2)], f'late{i}'.encode())
                for i in range(n)]
    if kind == 'replace':
        for i in range(n):
            assert c.cmd('FUNCTION', 'LOAD', lib(f'repl{i}', 1)) == f'repl{i}'.encode()
        return [(f'repl{i}', ['FUNCTION', 'LOAD', 'REPLACE', lib(f'repl{i}', 2)],
                 f'repl{i}'.encode()) for i in range(n)]
    if kind == 'delete':
        for i in range(n):
            assert c.cmd('FUNCTION', 'LOAD', lib(f'victim{i}', 1)) == f'victim{i}'.encode()
        return [(f'victim{i}', ['FUNCTION', 'DELETE', f'victim{i}'], b'OK') for i in range(n)]
    if kind == 'restore':
        late = []
        for i in range(n):
            # This server's own DUMP frame: {initial, rest_i}. REPLACE adds rest_i.
            assert c.cmd('FUNCTION', 'LOAD', lib(f'rest{i}', 3)) == f'rest{i}'.encode()
            payload = c.cmd('FUNCTION', 'DUMP')
            assert isinstance(payload, bytes), payload
            assert c.cmd('FUNCTION', 'DELETE', f'rest{i}') == b'OK'
            late.append((f'rest{i}', ['FUNCTION', 'RESTORE', payload, 'REPLACE'], b'OK'))
        return late
    assert kind == 'flush'
    return [(f'flush{i}', ['FUNCTION', 'FLUSH'], b'OK') for i in range(n)]


def recovered_lost(c, kind, name):
    """True when an acknowledged late mutation is absent after restart."""
    reply = c.cmd('FCALL', 'initial' if kind == 'flush' else name, 0)
    if kind == 'load': return reply != 2
    if kind == 'replace': return reply != 2
    if kind == 'restore': return reply != 3
    return not (isinstance(reply, dict) and 'Function not found' in reply['error'])


def shutdown_round(kind):
    """PS5.1: a FUNCTION mutation arriving after the final snapshot's registry cut.

    The final save's first file sync (epoll: the temp file's fdatasync; io_uring: its
    rename, since the ring submits the sync itself; Redis: the RDB fsync) is delayed two
    seconds with strace. The temp image must already hold the initial library before the
    late commands are sent. Redis acknowledges none of them; neither may TomoKV.
    """
    extra = ['--save', '3600 1']
    syscall = 'fsync' if ARGS.oracle else ('fdatasync' if ARGS.engine == 'epoll' else 'rename')
    data = OUT / f'shutdown-{kind}-{"redis" if ARGS.oracle else "tomo"}'
    s = Server(extra, data=data, trace='inject=' + syscall + ':delay_enter=2s:when=1')
    c = s.c
    assert c.cmd('SET', 'anchor', 'saved') == b'OK'
    assert c.cmd('FUNCTION', 'LOAD', lib('initial', 1)) == b'initial'
    late = late_commands(c, kind, 12)
    clients = [Resp(ARGS.port, 4) for _ in late]
    os.kill(s.pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    temps = []
    while time.monotonic() < deadline:
        temps = list(s.data.glob('temp-*.rdb')) if ARGS.oracle else list(s.data.glob('dump.tomo.tmp.*'))
        if temps and temps[0].stat().st_size > 100: break
        if s.p.poll() is not None: break
        time.sleep(.001)
    assert temps and temps[0].exists(), 'final save window did not open'
    frozen = temps[0].read_bytes()
    emit('shutdown_cut', kind=kind, temp=str(temps[0]), bytes=len(frozen), has_initial=b'initial' in frozen)
    assert b'initial' in frozen
    replies = {}
    def send(entry, conn):
        name, argv, _ = entry
        try: replies[name] = conn.cmd(*argv)
        except (OSError, EOFError) as exc: replies[name] = {'closed': type(exc).__name__}
        finally: conn.close()
    threads = [threading.Thread(target=send, args=pair) for pair in zip(late, clients)]
    for t in threads: t.start()
    for t in threads: t.join(6)
    assert all(not t.is_alive() for t in threads)
    s.p.wait(8)
    s.stop()
    delays = [line for line in s.tracepath.read_text().splitlines() if '(DELAYED)' in line]
    assert any(str(temps[0]) in line and syscall + '(' in line for line in delays), delays
    emit('shutdown_sync_window', kind=kind, lines=delays)
    ack = [name for name, _, ok in late if replies.get(name) == ok]
    emit('shutdown_function_replies', kind=kind, replies=replies, acknowledged=ack)
    with Server(extra, data=data) as recovered:
        assert recovered.c.cmd('GET', 'anchor') == b'saved'
        lost = [name for name in ack if recovered_lost(recovered.c, kind, name)]
        if kind != 'flush' or not ack:
            assert recovered.c.cmd('FCALL', 'initial', 0) == 1
        emit('shutdown_function_recovery', kind=kind, acknowledged=ack, lost=lost)
        assert not ack, ('post-cut FUNCTION acknowledged', kind, ack, lost)


def shutdown_functions():
    # Every kind runs, so a failing arm reports each mutation kind's own observation.
    failures = []
    for kind in ('load', 'replace', 'delete', 'restore', 'flush'):
        try:
            shutdown_round(kind)
        except AssertionError as error:
            failures.append(kind)
            emit('shutdown_round_failed', kind=kind, error=str(error)[:2000])
            for s in ACTIVE:
                if not s.stopped: s.stop(signal.SIGKILL)
    assert not failures, ('PS5.1 kinds failed', failures)


def function_cron():
    """PS5.6: every successful FUNCTION LOAD/DELETE/FLUSH/RESTORE is one save change.

    Redis increments server.dirty once per successful mutation (FLUSH even when empty)
    and never for a refused one. Then FUNCTION LOAD alone must arm save 1 1, and a crash
    after that scheduled save must restore it (round-5 T19/T20/T21).
    """
    data = OUT / ('cron-' + ('redis' if ARGS.oracle else 'tomo'))
    with Server(['--save', '3600 1'], data=data) as s:
        c = s.c
        assert c.cmd('SAVE') == b'OK'
        def changes():
            return int(c.info()['rdb_changes_since_last_save'])
        observed = []
        def step(expected, *argv):
            before = changes()
            reply = c.cmd(*argv)
            delta = changes() - before
            observed.append({'argv': [a if isinstance(a, str) else '<payload>' for a in argv],
                             'reply': reply if not isinstance(reply, bytes) or len(reply) < 64 else '<bytes>',
                             'delta': delta, 'expected': expected})
            return reply
        step(1, 'FUNCTION', 'LOAD', lib('cnt', 1))
        step(0, 'FUNCTION', 'LOAD', lib('cnt', 1))             # exists: refused
        step(1, 'FUNCTION', 'LOAD', 'REPLACE', lib('cnt', 2))
        payload = step(0, 'FUNCTION', 'DUMP')
        step(0, 'FUNCTION', 'LIST')
        step(1, 'FUNCTION', 'DELETE', 'cnt')
        step(0, 'FUNCTION', 'DELETE', 'cnt')                    # missing: refused
        step(1, 'FUNCTION', 'RESTORE', payload)
        step(0, 'FUNCTION', 'RESTORE', payload)                 # APPEND collision: refused
        step(1, 'FUNCTION', 'RESTORE', payload, 'REPLACE')
        step(1, 'FUNCTION', 'FLUSH')
        step(1, 'FUNCTION', 'FLUSH', 'SYNC')                    # empty, still a change
        emit('function_dirty_steps', steps=observed)
        assert all(row['delta'] == row['expected'] for row in observed), observed
        before = c.info()
        assert c.cmd('FUNCTION', 'LOAD', b'#!lua name=cronlib\nredis.register_function("cronfn", function(keys,args) return 777 end)') == b'cronlib'
        after = c.info()
        assert c.cmd('CONFIG', 'SET', 'save', '1 1') == b'OK'
        deadline = time.monotonic() + 5
        polls = []
        while time.monotonic() < deadline:
            polls.append(c.info()); time.sleep(.1)
        final = polls[-1]
        emit('function_cron_observation', before=before, after=after, final=final, polls=len(polls))
        if not ARGS.oracle:
            assert int(final['rdb_save_cron_checks']) - int(before['rdb_save_cron_checks']) >= 3
        assert int(after['rdb_changes_since_last_save']) >= 1, after
        assert int(final['rdb_saves']) > int(before['rdb_saves']), final
        s.stop(signal.SIGKILL)
    with Server(['--save', '1 1'], data=data) as s:
        result = s.c.cmd('FCALL', 'cronfn', 0)
        emit('function_cron_recovery', reply=result)
        assert result == 777, result


CAP_BODY = 'while true do pcall(function() while true do end end) end'
# Every Lua form that catches an error, around an unbounded loop. TomoKV only: Redis
# has no instruction cap. The handler-loop and coroutine forms run after the cap trips.
CAP_VARIANTS = [
    ('xpcall', 'while true do xpcall(function() while true do end end, function(e) return e end) end'),
    ('xpcall-handler-loop', 'while true do xpcall(function() while true do end end, function(e) while true do end end) end'),
    ('error-handler-loop', "return xpcall(function() error('x') end, function(e) while true do end end)"),
    ('coroutine', 'while true do coroutine.resume(coroutine.create(function() while true do end end)) end'),
    ('coroutine-pcall', 'local co = coroutine.create(function() while true do pcall(function() while true do end end) end end) while true do coroutine.resume(co) end'),
    ('wrap', 'while true do pcall(coroutine.wrap(function() while true do end end)) end'),
    ('recursive-pcall', 'local function f() while true do pcall(f) end end f()'),
    ('caught-return', 'return pcall(function() while true do end end)'),
]
# A suspended coroutine kept in a library upvalue keeps the hook the cap installed.
# The next activation must count it normally, not charge each line as an interval.
COSTALE = ("#!lua name=costale\nlocal co\n"
           "redis.register_function('costale', function(keys, args)\n"
           "  if args[1] == 'trip' then\n"
           "    co = coroutine.create(function()\n"
           "      pcall(function() while true do end end) coroutine.yield('tripped')\n"
           "      local n = 0\n"
           "      for i = 1, 500 do n = n + i end\n"
           "      return n\n"
           "    end)\n"
           "  end\n"
           "  return {coroutine.resume(co)}\n"
           "end)\n")
BOUNDED = 'local n = 0 for i = 1, 5000 do n = n + i end return n'


def cap_recovered(c):
    assert c.cmd('EVAL', 'return 42', 1, 'cap:key') == 42
    assert c.cmd('EVAL', BOUNDED, 1, 'cap:key') == 12502500
    assert c.cmd('GET', 'cap:key') is None


def cap_probe(port, engine, mode):
    with Conn(port) as c, Conn(port) as admin:
        sha = c.cmd('SCRIPT', 'LOAD', CAP_BODY)
        library = "#!lua name=cap4\nredis.register_function{function_name='cap4',callback=function() " + CAP_BODY + " end,flags={'no-writes'}}"
        assert c.cmd('FUNCTION', 'LOAD', library) == b'cap4'
        if engine == 'redis': assert admin.cmd('CONFIG', 'SET', 'lua-time-limit', 10) == b'OK'
        for verb, code in [('EVAL', CAP_BODY), ('EVALSHA', sha), ('EVAL_RO', CAP_BODY),
                           ('EVALSHA_RO', sha), ('FCALL', 'cap4'), ('FCALL_RO', 'cap4')]:
            c.s.settimeout(3)
            c.s.sendall(enc([verb, code, 1, 'cap:key']))
            if engine == 'redis':
                time.sleep(.05)
                assert admin.cmd('FUNCTION' if verb.startswith('FCALL') else 'SCRIPT', 'KILL') == b'OK'
            reply = c.read()
            assert isinstance(reply, Error) and ('killed' in reply.lower() if engine == 'redis' else 'instruction limit' in reply), (verb, reply)
            cap_recovered(c)
            emit('cap', verb=verb, reply=reply, recovered=True)
        if engine == 'redis': return
        for label, body in CAP_VARIANTS:
            c.s.settimeout(3)
            reply = c.cmd('EVAL', body, 1, 'cap:key')
            assert isinstance(reply, Error) and 'instruction limit' in reply, (label, reply)
            cap_recovered(c)
            emit('cap', verb='EVAL', variant=label, reply=reply, recovered=True)
        assert c.cmd('FUNCTION', 'LOAD', COSTALE) == b'costale'
        tripped = c.cmd('FCALL', 'costale', 1, 'cap:key', 'trip')
        assert isinstance(tripped, Error) and 'instruction limit' in tripped, tripped
        resumed = c.cmd('FCALL', 'costale', 1, 'cap:key')
        emit('cap', verb='FCALL', variant='stale-coroutine-hook', tripped=tripped, resumed=resumed)
        assert resumed == [1, 125250], resumed
        cap_recovered(c)


def probe_server(engine):
    with server(engine, ARGS.mode) as port:
        if ARGS.case == 'cap': cap_probe(port, engine, ARGS.mode)
        elif ARGS.case == 'tracking':
            result = tracking_probe(port, engine, ARGS.mode)
            emit('tracking', engine=engine, result=result)
            assert all(r['invalidated'] for r in result.values()), result
            result = overreg_probe(port, engine, ARGS.mode)
            emit('tracking keys', engine=engine, result=result)
            assert result['control_before'] and result['control_after']
            assert result['A_invalidated'] == [b'cc5t6:a'], result
            assert result['B_invalidated'] == [], result
        else:
            result = blocked_probe(port, engine, ARGS.mode)
            emit('blocked', engine=engine, result=result)
            assert result['control_nonblocking_xread_invalidated'], result
            for n in range(3):
                row = result[f'round{n}']
                assert row['reply_ok'], row
                # Redis enrolls at park time (the waking XADD invalidates it) and again
                # when it re-runs the woken read (the later XADD invalidates that one).
                assert row['inv_from_waking_xadd'] == [[f'tb{n}']], row
                assert row['inv_from_later_xadd'] == [[f'tb{n}']], row


def run():
    # The Redis 7.4 oracle runs the same probe first, unless explicitly omitted.
    for oracle in ((True, False) if not ARGS.no_oracle else (False,)):
        ARGS.oracle = oracle
        if ARGS.case in ('shutdown', 'dirty'):
            (shutdown_functions if ARGS.case == 'shutdown' else function_cron)()
        else:
            probe_server('redis' if oracle else 'tomo')
        emit('leg passed', case=ARGS.case, oracle=oracle)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('case',choices=['cap','tracking','blocked','shutdown','dirty'])
    p.add_argument('--binary',required=True); p.add_argument('--redis',required=True)
    p.add_argument('--cores',required=True); p.add_argument('--port',type=int,required=True)
    p.add_argument('--mode',choices=['1s','2s'],required=True)
    p.add_argument('--engine',choices=['uring','epoll'],required=True)
    p.add_argument('--ratio',default='6:2')
    p.add_argument('--no-oracle',action='store_true',help='TomoKV leg only (diagnostics)')
    p.add_argument('--output',type=Path,required=True)
    ARGS=p.parse_args(); ARGS.oracle=False; ROOT=OUT=ARGS.output.resolve(); OUT.mkdir(parents=True,exist_ok=True)
    TOMO=BIN=str(Path(ARGS.binary).resolve()); REDIS=ARGS.redis; CPUS=ARGS.cores
    PORT_BASE=ARGS.port; ACTIVE=[]; os.environ['LC_ALL']='C'
    emit('invocation', argv=os.sys.argv, affinity=sorted(os.sched_getaffinity(0)))
    try:
        run(); emit('PASS', case=ARGS.case)
    finally:
        for s in ACTIVE:
            if not s.stopped: s.stop()
