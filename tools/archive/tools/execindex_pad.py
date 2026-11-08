#!/usr/bin/env python3
"""Build an exact-image type-A control pair; never starts a server.

The common image links the production POST first and a symbol-isolated copy of
PRE second. POST-layout runs POST. PAD-A changes only main's five-byte jump to
PRE's entry. Both arms have identical text size, section layout, data, and every
function address. Keep POST-release as the ordinary deployment/merit candidate;
use POST-layout vs PAD-A to control the larger common image's layout separately.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import struct
import subprocess
from lbstall_artifacts import Elf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/execindex'

def recipe(source, objects):
    output=subprocess.check_output(['make','-C',str(source),'BUILD_ROOT='+str(objects),
        '-n','-W',str(objects/'src/main.o'),'all'],text=True)
    return shlex.split(next(line for line in output.splitlines()
        if ' -o '+str(objects/'tomokv')+' ' in line))

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--record', type=Path, default=ROOT/'docs/execindex/pad-a.json')
    parser.add_argument('--pre-source', type=Path, default=OUT/'pre-source')
    parser.add_argument('--pre-objects', type=Path, default=OUT/'pre-source/build')
    args = parser.parse_args()
    OUT = args.output.resolve(); OUT.mkdir(parents=True, exist_ok=True)
    pre = args.pre_source.resolve(); pre_objects = args.pre_objects.resolve()
    old=recipe(pre,pre_objects); new=recipe(ROOT,ROOT/'build')
    objects=[Path(x) for x in old if x.endswith('.o') and not x.endswith('/src/core/version.o')]
    symbols=set()
    for path in objects:
        for line in subprocess.check_output(['nm','-g','--defined-only','--format=posix',str(path)],text=True).splitlines():
            fields=line.split()
            if len(fields)>=2: symbols.add(fields[0])
        groups=subprocess.check_output(['readelf','--section-groups',str(path)],text=True)
        symbols.update(re.findall(r"COMDAT group section .*\[([^\]]+)\] contains",groups))
    assert 'main' in symbols
    mapping=OUT/'pad-symbols.map'
    mapping.write_text(''.join(f'{s} execindex_pre_{s}\n' for s in sorted(symbols)))
    renamed=[]
    for path in objects:
        dest=OUT/'pad-objects'/path.relative_to(pre_objects)
        dest.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['objcopy','--redefine-syms',str(mapping),str(path),str(dest)],check=True)
        renamed.append(str(dest))
    post=OUT/'POST-layout'; pad=OUT/'PAD-A'
    link=new[:]; link[link.index('-o')+1]=str(post)
    # Original object order comes first, preserving production COMDAT choices.
    at=link.index('-o'); link[at:at]=renamed
    with (OUT/'pad-link.log').open('w') as log:
        subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
    elf=Elf(post); functions=elf.functions()
    source=functions['main']; target=functions['execindex_pre_main']
    section=elf.sections[source['sec']]
    offset=section[4]+source['value']-section[3]; pc=source['value']
    raw=bytearray(elf.data)
    if raw[offset:offset+4]==b'\xf3\x0f\x1e\xfa': offset+=4; pc+=4
    assert source['size']>=pc-source['value']+5
    branch=b'\xe9'+struct.pack('<i',target['value']-(pc+5))
    old_bytes=raw[offset:offset+5].hex();raw[offset:offset+5]=branch
    pad.write_bytes(raw);pad.chmod(0o755)
    twin=Elf(pad)
    assert elf.sections==twin.sections and elf.symbols==twin.symbols
    changes=[i for i,(a,b) in enumerate(zip(elf.data,raw)) if a!=b]
    assert all(offset<=i<offset+5 for i in changes)
    record=dict(kind='A: PRE behaviour with the exact POST-layout image',
        release_candidate=str(ROOT/'build/tomokv'),release_sha256=sha(ROOT/'build/tomokv'),
        post_layout=str(post),post_sha256=sha(post),pad_a=str(pad),pad_sha256=sha(pad),
        matching_sections=True,matching_symbols=True,patch_offset=offset,
        before=old_bytes,after=branch.hex(),changed_bytes=len(changes),
        entry_source=source,entry_target=target,link=link,
        pre_objects={str(p):sha(p) for p in objects},
        limitation='The exact twin is POST-layout, not the smaller release image. Measure the release null separately.')
    args.record.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('link','pre_objects')},indent=2))
if __name__=='__main__':main()
