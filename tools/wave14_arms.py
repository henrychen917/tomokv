#!/usr/bin/env python3
"""Build-only wave14 layout twins and the Tcl planted regression."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from wave14 import ROOT, PRE, BUILD, DOC, save, sha


def regression(tag=''):
    name='tcl-regression'+('-'+tag if tag else '')
    out=BUILD/name;out.mkdir(parents=True,exist_ok=True)
    source=out/'source'
    shutil.copytree(ROOT/'src',source/'src',dirs_exist_ok=True)
    path=source/'src/cmd/t_server.cc'
    before='meta->last_command = child ? child : command_metadata_for(*spec);'
    after='meta->last_command = command_metadata_for(*spec); // planted: lose subcommand name'
    text=path.read_text();assert text.count(before)==1
    path.write_text(text.replace(before,after,1))
    replacements={};commands=[]
    for ns in ('','db0/'):
        target='build/'+ns+'src/cmd/t_server.o'
        lines=subprocess.check_output(['make','-Bn',target],text=True).splitlines()
        command=shlex.split(next(line for line in lines if line.startswith('g++ ') and line.endswith(' -o '+target)))
        dest=out/('db0.o' if ns else 'normal.o')
        command[command.index('src/cmd/t_server.cc')]=str(path)
        command[command.index('-o')+1]=str(dest)
        command.insert(1,'-gz=zlib')
        with dest.with_suffix('.build.log').open('w') as log:
            subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
        replacements[target]=str(dest);commands.append(command)
    lines=subprocess.check_output(['make','-n','-W','build/src/main.o','all'],text=True).splitlines()
    link=shlex.split(next(line for line in lines if line.startswith('g++ ') and ' -o build/tomokv ' in line))
    link=[replacements.get(x,x) for x in link];link[link.index('-o')+1]=str(out/'tomokv')
    with (out/'link.log').open('w') as log:subprocess.run(link,check=True,stdout=log,stderr=subprocess.STDOUT)
    manifest=json.loads((ROOT/'tests/redis_tcl_passing.json').read_text())
    spec=manifest['files']['unit/introspection']
    # Frozen upstream assertion, exercised through the ordinary partial Tcl job.
    required='CLIENT LIST with IDs in tests/unit/introspection.tcl'
    required_bare=required.split(' in tests/')[0]
    spec['skip_tests'].update({s.split(' in tests/')[0]:'Focused planted control' for s in spec['passed_tests'] if s!=required})
    spec['passed_tests']=[required]
    spec['isolated_tests']={k:v for k,v in spec.get('isolated_tests',{}).items() if k==required_bare}
    manifest['files']={'unit/introspection':spec}
    save(out/'manifest.json',manifest)
    save(DOC/(name+'-build.json'),dict(root='CLIENT-LIST-CMD-NAME',before=before,after=after,
        post_sha256=sha(ROOT/'build/tomokv'),source_sha256=sha(path),compile=commands,link=link,
        binary_sha256=sha(out/'tomokv'),manifest_sha256=sha(out/'manifest.json')))
    shutil.rmtree(source)


def main():
    assert os.sched_getaffinity(0)<=set(range(32))
    p=argparse.ArgumentParser();p.add_argument('kind',choices=('pad','tcl-regression'))
    p.add_argument('--tag',default='')
    a=p.parse_args()
    if a.kind=='pad':
        from exec1s_pad import build
        out=BUILD/'layout';out.mkdir(parents=True,exist_ok=True)
        build(PRE,ROOT,out,DOC/'pad-a.json')
    else:regression(a.tag)

if __name__=='__main__':main()
