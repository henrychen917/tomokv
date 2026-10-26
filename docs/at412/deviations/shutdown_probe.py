import sys, subprocess, tempfile, threading, time
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[3] / 'tests'))
from _lib import Conn, wait_ready, encode
import at412
binary, mode, atomic, kind = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
d = tempfile.mkdtemp(prefix='at412-dev-')
argv = ['taskset','-c','48-55',binary,'--bind','127.0.0.1','--port','20200','--dir',d,'--save','','--shards','16',
        '--thread-mode',mode,'--atomic',atomic,'--enable-debug-command','yes','--databases','16','--key-lb','0','--client-lb','0','--flip-auto','0']
if mode == '2s': argv += ['--ratio','6:2']
p = subprocess.Popen(argv, stdout=open(d+'/log','w'), stderr=subprocess.STDOUT)
stop = threading.Event()
try:
    c = wait_ready('127.0.0.1', 20200, process=p, timeout=20)
    keys = at412.pair(c, 'z', False)
    c.must('MSET', keys[0], 0, keys[1], 0)
    c.must('SADD', keys[0]+'{s}', *range(1000))
    def worker(i):
        try:
            x = Conn('127.0.0.1', 20200, timeout=5)
            while not stop.is_set():
                if kind == 'script':
                    x.send('EVAL', at412.WRITE, 2, *keys)
                elif kind == 'exec':
                    x.raw(encode('MULTI')+encode('INCR', keys[0])+encode('INCR', keys[1])+encode('EXEC'))
                    x.read(); x.read(); x.read()
                else:
                    x.send('RENAME', keys[0], keys[1]) if i % 2 else x.send('RENAME', keys[1], keys[0])
                x.read()
        except Exception:
            pass
    ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(12)]
    for t in ts: t.start()
    time.sleep(1.5)
    c.send('SHUTDOWN', 'NOSAVE')
    try: c.read()
    except Exception: pass
    rc = p.wait(timeout=30)
    print(kind, mode, atomic, 'rc', rc)
finally:
    stop.set()
    if p.poll() is None: p.kill(); p.wait()
