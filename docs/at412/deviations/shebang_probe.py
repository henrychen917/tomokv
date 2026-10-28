import sys, subprocess, tempfile
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
    keys = at412.pair(c, 's', False)
    c.must('MSET', keys[0], 1, keys[1], 1)
    src = "#!lua flags=no-writes\nreturn {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}"
    print('EVAL_RO 2key shebang', c.cmd('EVAL_RO', src, 2, *keys))
    print('EVAL 2key shebang', c.cmd('EVAL', src, 2, *keys))
    print('EVAL 1key shebang', c.cmd('EVAL', "#!lua flags=no-writes\nreturn redis.call('GET',KEYS[1])", 1, keys[0]))
    print('EVAL_RO 2key plain', c.cmd('EVAL_RO', "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}", 2, *keys))
    c.must('SET', keys[0], 'x'); c.must('CONFIG', 'SET', 'maxmemory', 1)
    print('DEL under maxmemory', c.cmd('DEL', keys[0]))
    c.must('CONFIG', 'SET', 'maxmemory', 0)
finally:
    p.terminate(); p.wait()
