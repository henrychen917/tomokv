import sys, subprocess, tempfile, time
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[3] / 'tests'))
from _lib import Conn, wait_ready
import at412
binary = sys.argv[1]
d = tempfile.mkdtemp(prefix='at412-dev-')
argv = ['taskset','-c','48-55',binary,'--bind','127.0.0.1','--port','20200','--dir',d,'--save','','--shards','16',
        '--thread-mode','2s','--ratio','6:2','--atomic','1','--enable-debug-command','yes','--databases','16']
p = subprocess.Popen(argv, stdout=open(d+'/log','w'), stderr=subprocess.STDOUT)
try:
    c = wait_ready('127.0.0.1', 20200, process=p, timeout=20)
    keys = at412.pair(c, 'd', False)
    c.must('MSET', keys[0], 'before', keys[1], 1)
    s = Conn('127.0.0.1', 20200, timeout=5)
    before = at412.stats(c)
    c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 300000)
    s.send('EVAL', "return redis.call('SET',KEYS[1],'v')", 2, *keys)
    at412.wait(lambda: at412.stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'], 'park')
    c.must('CONFIG', 'SET', 'maxmemory', 1)
    print('DEL under maxmemory with a parked script holding intents:', c.cmd('DEL', keys[0]))
    print('script:', s.read())
    c.must('CONFIG', 'SET', 'maxmemory', 0)
    print('after:', c.cmd('MGET', *keys))
finally:
    p.terminate(); p.wait()
