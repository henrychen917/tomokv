#!/usr/bin/env python3
"""Offline LaneFull ELF proofs and schema controls. Never executes a server arm.

Use under taskset -c 112-127. Raw dumps use the existing exact ELF collector; the
comparison also checks allocated relocations, linked addresses and the ELF entry.
PAD-A restores PRE's two constant-zero INFO rows in POST's generated assembly.
PAD-B removes those rows from PRE's generated assembly using zero-precision zero
arguments. Only assembler string directives change; no handwritten code path.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile

from flipsettle_artifacts import snapshot, corrupt_control, digest, write_json
from ttlstate_proof import compare_files
from lbstall_artifacts import Elf


def compare(pre, post, out):
    paths = ['tomokv'] + sorted(str(p.relative_to(pre)) for p in pre.glob('src/**/*.o'))
    paths += sorted(str(p.relative_to(pre)) for p in pre.glob('db0/src/**/*.o'))
    assert len(paths) == 85, 'review production TU inventory'
    rows = {p: compare_files(pre / p, post / p) for p in paths}
    write_json(out, dict(equal=all(r['okay'] for r in rows.values()), files=rows))
    executable_equal = [p for p,r in rows.items() if all(x['raw_equal'] and x['layout_equal'] for x in r['executable'])]
    print('Exact executable sections identical:',len(executable_equal),'/',len(paths))
    print('Changed executable bytes/layout:',*[p for p in paths if p not in executable_equal])
    print('Complete identity including relocations/data/addresses:', all(r['okay'] for r in rows.values()))
    return all(r['okay'] for r in rows.values())


def functions(elf):
    return sorted((s['name'],s['value'],s['size'],elf.names[s['sec']]) for s in elf.symbols
                  if s['info'] & 15 == 2 and 0 < s['sec'] < len(elf.names)
                  and elf.sections[s['sec']][2] & 4)


def schema_twin(base, out, kind):
    out.mkdir(parents=True,exist_ok=True)
    source = out / 'source'; source.mkdir(exist_ok=True)
    with tarfile.open(base / 'source.tar') as archive:
        archive.extractall(source, members=(x for x in archive.getmembers()
            if x.name.startswith(('src/','third_party/'))), filter='data')
    commands = [shlex.split(x) for x in (base / 'build.log').read_text().splitlines()
                if x.startswith('g++ ')]
    for tree in ['src','db0']:
        shutil.copytree(base / tree,out / tree,dirs_exist_ok=True)
    proofs=[]
    with (out / 'build.log').open('w') as log:
        def run(cmd,cwd=None):
            log.write(shlex.join(cmd)+'\n');log.flush()
            subprocess.run(cmd,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
        for name in ['src/cmd/t_server.o','db0/src/cmd/t_server.o']:
            matches=[c for c in commands if c[-1]=='build/'+name]
            assert matches, name
            cmd=matches[-1].copy();cmd[cmd.index('-c')]='-S'
            label='db0' if name.startswith('db0/') else 'normal'
            cmd[-1]=label+'.s';run(cmd,source)
            run(['g++','-c',label+'.s','-o',label+'-roundtrip.o'],source)
            proof=compare_files(base/name,source/(label+'-roundtrip.o'))
            assert proof['okay'], ('unmodified assembly must round-trip',proof['errors'])
            asm=(source/(label+'.s')).read_text(); changed=asm
            for prefix in ['', 'mget_']:
                if kind == 'A-get' and prefix: continue
                if kind == 'A-mget' and not prefix: continue
                field='read_local_'+prefix+'fallback_lane_full'
                old=field+r':%llu\r\n'
                if kind=='B':
                    assert changed.count(old)==1,(field,changed.count(old))
                    changed=changed.replace(old,'%.0llu')
                else:
                    anchor='read_local_'+prefix+r'fallback_generation:%llu\r\n'
                    assert changed.count(anchor)==1,(field,changed.count(anchor))
                    changed=changed.replace(anchor,anchor+field+r':0\r\n')
            (source/(label+'-twin.s')).write_text(changed)
            run(['g++','-c',label+'-twin.s','-o',str((out/name).resolve())],source)
            before,after=Elf(base/name),Elf(out/name)
            for i,section in enumerate(before.sections):
                if section[2]&4:
                    j=after.names.index(before.names[i])
                    assert before.section_data(i)==after.section_data(j),before.names[i]
            assert functions(before)==functions(after)
            proofs.append(dict(object=name,roundtrip=proof,original_assembly_sha256=digest(asm.encode()),
                twin_assembly_sha256=digest(changed.encode()),executable_bytes_and_function_layout_equal=True))
        links=[c for c in commands if '-c' not in c and 'build/tomokv' in c]
        assert links
        cmd=[str((out/c.removeprefix('build/')).resolve()) if c.startswith('build/') else c for c in links[-1]]
        run(cmd)
    before,after=Elf(base/'tomokv'),Elf(out/'tomokv')
    assert functions(before)==functions(after),'every linked function address AND size must match base'
    layouts=[]
    for i,section in enumerate(before.sections):
        if section[2]&4:
            j=after.names.index(before.names[i]);s=after.sections[j]
            assert section[2:6]==s[2:6] and section[8]==s[8],before.names[i]
            layouts.append(dict(name=before.names[i],address=s[3],size=s[5],alignment=s[8]))
    assert before.data[24:32]==after.data[24:32], 'ELF entry point changed'
    write_json(out/'layout.json',dict(kind=kind,
        definition='A: PRE observable behavior with POST text size/function layout' if kind.startswith('A') else
                   'B: POST observable behavior with PRE text size/function layout',
        source=str(base),source_sha256=digest(before.data),twin_sha256=digest(after.data),
        function_table_equal=True,functions=len(functions(after)),entry_equal=True,executable_layouts=layouts,
        object_proofs=proofs,scope='schema formats only; no runtime selector; no footer NOP padding'))
    print(kind, 'schema twin:',len(functions(after)),'function addresses/sizes match',base)


def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('snapshot');s.add_argument('arm',type=Path)
    c=sub.add_parser('compare')
    for name in ['pre','post','out']:c.add_argument(name,type=Path)
    p=sub.add_parser('twin');p.add_argument('kind',choices=['A','B','A-get','A-mget'])
    p.add_argument('base',type=Path);p.add_argument('out',type=Path)
    n=sub.add_parser('negative-control');n.add_argument('elf',type=Path);n.add_argument('out',type=Path)
    a=ap.parse_args()
    if a.cmd=='snapshot':snapshot(a.arm)
    elif a.cmd=='compare':
        if not compare(a.pre,a.post,a.out):raise SystemExit(1)
    elif a.cmd=='twin':schema_twin(a.base,a.out,a.kind)
    else:corrupt_control(a.elf,a.out)

if __name__=='__main__':main()
