#!/usr/bin/env python3
"""Disposable, root-specific correctness controls; never performance arms."""
import hashlib, json, os, shlex, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
OUT=ROOT/'build/pubtrackfix/plants'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    assert os.sched_getaffinity(0) <= set(range(32,48))
    OUT.mkdir(parents=True,exist_ok=True)
    post=ROOT/'build/tomokv'
    recipe=subprocess.check_output(['make','-n','-W','build/src/main.o','all'],cwd=ROOT,text=True)
    link=shlex.split(next(x for x in recipe.splitlines() if ' -o build/tomokv ' in x))
    results={'post_sha256':sha(post),'plants':{}}
    for name,needle,patch in [('reply-off','IoLoop21pubsub_finish_pending',None),('eviction','FlatStore16evict_over_limit',None)]:
        elf=Elf(post);data=bytearray(elf.data);edits=[]
        symbols=[s for s in elf.symbols if s['name'].startswith('_ZN') and needle in s['name'] and s['info'] & 15 == 2]
        assert len(symbols)==2,[(s['name'],s['size']) for s in symbols]
        for s in symbols:
            section=elf.sections[s['sec']];offset=section[4]+s['value']-section[3]
            if name=='eviction':
                assert data[offset:offset+4]==bytes.fromhex('f30f1efa')
                offset+=4;original=bytes(data[offset:offset+3]);replacement=bytes.fromhex('31c0c3')
            else:
                body=elf.body(s);pattern=bytes.fromhex('83e0f7');assert body.count(pattern)==1
                offset+=body.index(pattern)+2;original=bytes(data[offset:offset+1]);replacement=b'\xff'
            data[offset:offset+len(replacement)]=replacement
            edits.append(dict(symbol=s['name'],file_offset=offset,before=original.hex(),after=replacement.hex()))
        binary=OUT/('tomokv-'+name);binary.write_bytes(data);binary.chmod(0o755)
        results['plants'][name]=dict(path=str(binary),sha256=sha(binary),edits=edits)
    for name in ('consumer','bcast'):
        cmd=link.copy();binary=OUT/('tomokv-'+name);cmd[cmd.index('-o')+1]=str(binary)
        inputs=[]
        for namespace in ('','db0/'):
            rel='src/cmd/'+('t_stream_groups' if name=='consumer' else 'tracking')+'.o'
            original='build/'+namespace+rel
            if name=='consumer':obj=ROOT/'build/pubtrackfix/pre'/namespace/rel
            else:
                src=OUT/('tracking-'+('db0' if namespace else 'normal')+'.cc')
                source=(ROOT/'src/cmd/tracking.cc').read_text()
                old='''            tracking_deliver_frame(state, id,
                Slice(array.data(), static_cast<uint32_t>(array.size())), false, true);'''
                new='''            for (const auto& key : keys)
                tracking_deliver_frame(state, id,
                    Slice(key.data(), static_cast<uint32_t>(key.size())), false);'''
                assert source.count(old)==1;src.write_text(source.replace(old,new))
                obj=src.with_suffix('.o')
                compile=['g++','-std=c++20','-O2','-g','-Wall','-Wextra','-march=native','-pthread','-DTOMO_JEMALLOC','-I.','-Isrc/cmd']
                if namespace:compile+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
                compile+=['-c',str(src),'-o',str(obj)]
                subprocess.run(compile,cwd=ROOT,check=True)
            cmd[cmd.index(original)]=str(obj);inputs.append(dict(path=str(obj),sha256=sha(obj)))
        subprocess.run(cmd,cwd=ROOT,check=True)
        results['plants'][name]=dict(path=str(binary),sha256=sha(binary),link=cmd,changed_inputs=inputs)
    (ROOT/'docs/pubtrackfix/plants.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
