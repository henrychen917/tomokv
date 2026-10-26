"""Small protocol reproductions for the main Tcl failure families; no load generator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn, RespError
from redis_tcl import stop

CASES = {
 'reset-multi': [('a',['MULTI']),('a',['RESET']),('a',['EXEC'])],
 'reset-monitor': [('a',['MONITOR']),('a',['RESET'])],
 'multi-oom-queue': [('a',['SET','foo','bar']),('a',['MULTI']),('b',['CONFIG','SET','maxmemory',1]),
                     ('a',['LPUSH','list','value']),('b',['CONFIG','SET','maxmemory',0]),('a',['EXEC'])],
 'multi-flushall': [('a',['MULTI']),('a',['FLUSHALL','SYNC']),('a',['EXEC'])],
 'xread-last': [('a',['XADD','s','1-0','f','v']),('a',['XREAD','STREAMS','s','+'])],
 'xrange-exclusive-infinity': [('a',['XADD','s','1-0','f','v']),('a',['XRANGE','s','(-','+'])],
 'restore-idletime': [('a',['SET','k','v']),('a',['DUMP','k']),
                       ('a',['RESTORE','copy',0,'$DUMP','IDLETIME',1000]),('a',['OBJECT','IDLETIME','copy'])],
 'function-casing': [('a',['FUNCTION','LOAD',"#!lua name=lib\nredis.register_function('hello',function() return 'hello1' end)"]),
                      ('a',['FCALL','HELLO',0])],
 'function-duplicate-list-option': [('a',['FUNCTION','LIST','WITHCODE','WITHCODE'])],
 'function-name-format': [('a',['FUNCTION','LOAD',"#!lua name=lib\nredis.register_function('bad-name!',function() return 1 end)"])],
 'function-duplicate-metadata': [('a',['FUNCTION','LOAD',"#!lua name=first name=second\nredis.register_function('f',function() return 1 end)"])],
 'function-load-unknown-option': [('a',['FUNCTION','LOAD','foo','bar',"#!lua name=lib\nredis.register_function('f',function() return 1 end)"])],
 'zmpop-count-error': [('a',['ZMPOP',1,'z','MIN','COUNT','invalid'])],
 'bzmpop-numkeys-error': [('a',['BZMPOP',0,'invalid','z','MIN'])],
 'info-cpu': [('a',['INFO','CPU'])],
 'latency-histogram': [('a',['CONFIG','SET','latency-tracking','yes']),('a',['SET','k','v']),('a',['LATENCY','HISTOGRAM','SET'])],
 'slowlog-exec': [('a',['CONFIG','SET','slowlog-log-slower-than',0]),('a',['SLOWLOG','RESET']),
                    ('a',['MULTI']),('a',['PING']),('a',['EXEC']),('a',['SLOWLOG','LEN'])],
 'lua-time-limit-config': [('a',['CONFIG','SET','lua-time-limit',100])],
 'appendonly-live-config': [('a',['CONFIG','SET','appendonly','yes'])],
}
for name,script in {
 'lua-cjson': "return cjson.decode('1')", 'lua-cmsgpack': "return cmsgpack.pack(1)",
 'lua-bit': 'return bit.band(3,1)', 'lua-sha1hex': "return redis.sha1hex('x')",
 'lua-error-reply': "return redis.error_reply('MY_ERR message')",
 'lua-status-reply': "return redis.status_reply('MY_OK message')",
 'lua-prng': 'math.randomseed(1); return type(math.random())',
 'lua-clock': 'return type(os.clock())', 'lua-ping': "return redis.call('PING')",
 'lua-blocking': "return redis.call('BLPOP','k',0)",
 'lua-undeclared-key': "return redis.call('SET','k','v')",
 'lua-mget': "return redis.call('MGET',KEYS[1])",
 'lua-number-string': "return tostring(9007199254740991)",
 'lua-shebang': '#!lua flags=no-writes\nreturn redis.call("SET",KEYS[1],"v")',
 'lua-version-api': 'return redis.REDIS_VERSION_NUM',
 'lua-error-arity': "return redis.call('GET')", 'lua-missing-command': 'return redis.call()',
}.items():
    CASES[name]=[('a',['EVAL',script,1,'k'])]
CASES['lua-undeclared-key'][0][1][2:] = [0]
CASES['lua-number-string'] = [('a',['EVAL',"return redis.call('SET',KEYS[1],9007199254740991)",1,'k']),
                              ('a',['GET','k'])]
CASES['restore-lfu'] = [('a',['CONFIG','SET','maxmemory-policy','allkeys-lfu']),('a',['SET','k','v']),
    ('a',['DUMP','k']),('a',['RESTORE','copy',0,'$DUMP','FREQ',100]),('a',['OBJECT','FREQ','copy'])]

def value(v):
    if isinstance(v, RespError): return {'error':str(v)}
    if isinstance(v,bytes):
        try:return v.decode('utf-8')
        except UnicodeDecodeError:return {'hex':v.hex()}
    if isinstance(v,list):return [value(x) for x in v]
    return v

def run(args, name, commands, mode, binary):
    folder=args.output/name/mode;folder.mkdir(parents=True,exist_ok=True)
    cmd=['taskset','-c',args.cores,str(binary),'--port',str(args.port),'--bind','127.0.0.1',
         '--save','','--appendonly','no','--dir',str(folder),'--enable-debug-command','yes']
    if mode!='redis':
        cmd+=['--thread-mode',mode,'--shards','16','--databases','16']
        if mode=='2s':cmd+=['--ratio','6:2']
    clients={};result=[];process=None
    with (folder/'server.log').open('w') as out:
        try:
            process=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
            for _ in range(100):
                try:
                    c=Conn('127.0.0.1',args.port,timeout=1);c.cmd('PING');c.close();break
                except OSError:time.sleep(.02)
            else:raise RuntimeError('server did not boot')
            dumped=None
            for ident, original in commands:
                c=clients.setdefault(ident,None)
                if c is None:c=clients[ident]=Conn('127.0.0.1',args.port,timeout=2)
                argv=[dumped if v=='$DUMP' else v for v in original]
                reply=c.cmd(*argv)
                if argv[0]=='DUMP':dumped=reply
                result.append(dict(connection=ident,argv=original,reply=value(reply)))
        except Exception as error:result.append(dict(infrastructure_error=str(error)))
        finally:
            for c in clients.values():
                if c:c.close()
            stop(process)
    return dict(server_argv=cmd,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),commands=result)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cores',default='32-39');p.add_argument('--port',type=int,default=45830)
    args=p.parse_args();args.output=args.output.resolve();results={}
    for name,commands in CASES.items():
        results[name]={mode:run(args,name,commands,mode,binary) for mode,binary in
            [('2s',ROOT/'build/tomokv'),('1s',ROOT/'build/tomokv'),
             ('redis',Path('/home/user/Projects/redis/src/redis-server'))]}
        (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(name,flush=True)

if __name__=='__main__':main()
