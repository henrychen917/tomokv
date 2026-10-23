#!/usr/bin/env python3
"""PAD-A: link PRE objects unchanged, matching POST total executable .text size.

This controls total text size, not individual function addresses. Existing layout
locks are unchanged by datafix1; Config's new pointer consumes reserved storage.
Run pinned to the lane's CPUs. Never starts a server or workload.
"""
import argparse,hashlib,json,subprocess
from pathlib import Path
from lbstall_artifacts import Elf


def text_size(path):
    e=Elf(path)
    return e.sections[e.names.index('.text')][5]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pre',type=Path,default=Path('build/datafix1/pre-src/build'))
    p.add_argument('--post',type=Path,default=Path('build/tomokv'))
    p.add_argument('--output',type=Path,default=Path('build/datafix1/PAD-A'))
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    objects=subprocess.check_output(['make','--no-print-directory','-s','BUILD_ROOT='+str(a.pre),
        '--eval=datafix1-pad-list:;@echo $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ)','datafix1-pad-list'],text=True).split()
    wanted=text_size(a.post);padding=0
    for _ in range(3):
        source=a.output/'padding.S';obj=a.output/'padding.o';binary=a.output/'tomokv'
        source.write_text('.text\n.globl tomo_datafix1_pad\n.type tomo_datafix1_pad,@function\n'
            'tomo_datafix1_pad:\n.fill %d,1,0x90\n'%padding+
            '.size tomo_datafix1_pad,.-tomo_datafix1_pad\n.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['g++','-c',str(source),'-o',str(obj)],check=True)
        subprocess.run(['g++','-pthread',*objects,str(obj),'-o',str(binary),
            '-Wl,--wrap=main','-ljemalloc','-luring','-pthread','-lssl','-lcrypto','-lm'],check=True)
        actual=text_size(binary)
        if actual==wanted:break
        padding+=wanted-actual
        assert padding>=0,'PRE behavior already exceeds POST text size'
    assert actual==wanted,(actual,wanted)
    result=dict(kind='A: behaviour twin',behavior='PRE objects unchanged',
        layout='POST total .text size; existing layout lock sizes/offsets; function addresses may differ',
        limitation='Not an exact placement twin. Config locale pointer occupies PRE reserved bytes.',
        padding_bytes=padding,text_bytes=wanted,
        objects={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in objects},
        sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (a.output/'kind.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='objects'},indent=2))


if __name__=='__main__':main()
