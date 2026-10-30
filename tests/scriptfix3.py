#!/usr/bin/env python3
"""Additional cache/environment witnesses, reusing scriptfix2's exact oracle runner.

The existing scriptfix2 battery and gate rows remain unchanged. Run all database,
mode, engine and atomic legs with the same arguments as that runner.
"""
import hashlib
import scriptfix2
original_extras=scriptfix2.extras
def extras(root):
    steps=original_extras(root);commands=[]
    if root=='EVALSHA-SHA-CASE':
        source="#!lua flags=no-writes\nerror('warm case line')"
        sha=hashlib.sha1(source.encode()).hexdigest()
        commands.append(['script','load',source])
        for _ in range(3):
            for spelling in (sha,sha.upper(),''.join(c.upper() if i%2 else c for i,c in enumerate(sha))):
                commands += [['evalsha',spelling,0],['evalsha_ro',spelling,0],['script','exists',spelling]]
        # OR-folding must not equate digit bytes with 0x10..0x19 controls.
        malformed=[sha[:i]+chr(ord(c)^32)+sha[i+1:] for i,c in enumerate(sha) if c.isdigit()]
        assert malformed
        commands.append(['script','exists',*malformed])
        commands += [['evalsha',malformed[0],0],['script','flush'],['evalsha',sha.upper(),0]]
        # Different metadata identities must never reuse a previous compiled
        # body. Duplicate LOAD preserves a warm entry; FLUSH retires its table.
        # Exact oracle values/readonly errors make stale closure selection fail.
        for generation in range(6):
            commands.append(['script','flush'])
            for slot in range(8):
                value=generation*8+slot
                text=('' if slot%2 else '#!lua flags=no-writes\n')+f'return {value}'
                digest=hashlib.sha1(text.encode()).hexdigest()
                commands += [['script','load',text],['eval',text,0],
                             ['script','load',text],['evalsha',digest,0],
                             ['evalsha_ro',digest.upper(),0]]
    if root=='LUA-SANDBOX-GLOBALS':
        body="redis.register_function('EnvCase',function(keys,args) if args[1] then cjson.encode_number_precision(tonumber(args[1])) end return {cjson.encode_number_precision(),type(redis.replicate_commands),loadstring('return type(redis.replicate_commands)')()} end)"
        library='#!lua name=scriptfix3\n'+body
        commands.append(['function','load',library])
        for _ in range(3):
            commands += [['eval',"cjson.encode_number_precision(4) return {cjson.encode_number_precision(),type(redis.replicate_commands)}",0],
                         ['fcall','ENVCASE',0,3],['fcall','envcase',0],
                         ['eval','return cjson.encode_number_precision()',0]]
        commands += [['script','flush'],['fcall','EnvCase',0],
                     ['eval','return cjson.encode_number_precision()',0],
                     ['eval','cjson.encode_number_precision(7) return 1',0],
                     ['function','flush'],['function','load',library],['fcall','envcase',0],
                     ['eval','return cjson.encode_number_precision()',0]]
    return steps+[{'c':'a','send':command} for command in commands]
scriptfix2.extras=extras
if __name__=='__main__':raise SystemExit(scriptfix2.main())
