import ast, json, random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from _lib import Conn, RespError
from _differ_aclkeys import wait_blocked
from psfix import boot
root=Path('build/aclkeys4/minimize'); root.mkdir(exist_ok=True)
node=next(n for n in ast.parse(Path('tests/differ.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='gen_multidb')
ns={}; exec(compile(ast.Module(body=[node],type_ignores=[]),'<generator>','exec'),ns)
ops=ns['gen_multidb'](random.Random(7))
cases={'alone':[], 'double_swap':[['SWAPDB',0,1]]*2, 'single_swap':[['SWAPDB',0,1]],
'self_swap':[['SWAPDB',2,2]], 'invalid':[['SWAPDB',0,'bad'],['SWAPDB','bad',0],['SWAPDB',0,99]],
'exec_one':[['MULTI'],['SWAPDB',0,1],['EXEC']],
'exec_two':[['MULTI'],['SWAPDB',0,1],['SWAPDB',0,1],['EXEC']],
'swap_flush':[['SWAPDB',0,1],['FLUSHALL']],
'random_swaps':[x for x in ops[47:] if x[0]=='SWAPDB'],
'select_one':[['SELECT',1]]}
for label,arming in cases.items():
    directory=root/label; directory.mkdir(exist_ok=True)
    row={'label':label,'arming':arming}
    argv=[str(Path('build/aclkeys4/aclkeys3-original').resolve()),'--port','18340','--bind','127.0.0.1','--shards','16','--ratio','6:2','--databases','16','--atomic','0','--save','','--dir',str(directory.resolve()),'--enable-debug-command','yes']
    with boot(argv,'112-119',18340,directory/'server.log'):
        a=Conn('127.0.0.1',18340,timeout=2,buffering=0); w=Conn('127.0.0.1',18340,timeout=2,buffering=0)
        try:
            row['boot_shards']=a.cmd('DEBUG','SHARDS','block:aclkeys')
            row['arming_replies']=[repr(a.cmd(*op)) for op in arming]
            if label=='select_one': assert w.cmd('SELECT',1)==b'OK'
            row['config']={x:repr(a.cmd('CONFIG','GET',x)) for x in ('notify-keyspace-events','timeout','maxmemory')}
            row['before_shards']=a.cmd('DEBUG','SHARDS','block:aclkeys')
            row['topology']=a.cmd('DEBUG','LBSIGNALS').decode()
            a.cmd('DEL','block:aclkeys'); ident=w.cmd('CLIENT','ID'); w.send('XREAD','BLOCK',0,'STREAMS','block:aclkeys',0)
            wait_blocked(a,(w.sock,w.file),ident,lambda c,args:c.cmd(*args),lambda v:v,lambda f:w.read(),timeout=2)
            # Witness the physical alias too, so registration's eager reprobe cannot hide a missed publish.
            deadline=time.monotonic()+2
            while b'blocking_waiters:1\r\n' not in a.cmd('INFO'):
                assert time.monotonic()<deadline,'waiter never registered'
            row['client_list']=a.cmd('CLIENT','LIST').decode()
            assert a.cmd('XADD','block:aclkeys','1-0','field','value')==b'1-0'
            try: row['wake']=repr(w.read())
            except TimeoutError: row['wake']='TIMEOUT'
            row['after_shards']=a.cmd('DEBUG','SHARDS','block:aclkeys')
            row['stream']=repr(a.cmd('XRANGE','block:aclkeys','-','+'))
        finally: w.close(); a.close()
    (directory/'result.json').write_text(json.dumps(row,indent=2)+'\n')
    print(label,row['wake'],row['boot_shards'],row['before_shards'],flush=True)
