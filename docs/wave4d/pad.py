"""Build PAD(A): PRE source behavior, POST .text size; no handler is patched.

This controls total text size, not every function's position or internal layout.
"""
import hashlib,json,shlex,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
BASE=ROOT/'build/wave4d/pad';SRC=BASE/'source';SRC.mkdir(parents=True,exist_ok=True)
for folder in ('src','third_party'):shutil.copytree(ROOT/folder,SRC/folder,dirs_exist_ok=True)
shutil.copyfile(ROOT/'Makefile',SRC/'Makefile')
p=SRC/'src/core/server.h'
original=subprocess.check_output(['git','show','a44aef25c:src/core/server.h'],cwd=ROOT)
p.write_bytes(original)
command=['make','-j32','BUILD_ROOT='+str(BASE/'objects'),'all']
with (BASE/'build.log').open('w') as log:subprocess.run(command,cwd=SRC,stdout=log,stderr=subprocess.STDOUT,check=True)
def text_size(path):
 elf=Elf(path);return elf.sections[elf.names.index('.text')][5]
pre=ROOT/'build/wave4c/tomokv-pre';rebuilt=BASE/'objects/tomokv';post=ROOT/'build/tomokv'
assert text_size(pre)==text_size(rebuilt),'PRE rebuild text size changed'
gap=text_size(post)-text_size(rebuilt);assert 0<gap<256, gap
asm=BASE/'pad.cc';obj=BASE/'pad.o'
asm.write_text('asm(R"(.pushsection .text.wave4d_pad,\"ax\",@progbits\n.fill '+str(gap)+',1,0x90\n.popsection\n)");\n')
mk=BASE/'pad.mk';mk.write_text(str(obj)+': '+str(asm)+'\n\tg++ -std=c++20 -O2 -g -march=native -c $< -o $@\n')
subprocess.run(['make','-j32','-f',str(mk)],cwd=ROOT,check=True)
link=shlex.split(next(line for line in reversed((BASE/'build.log').read_text().splitlines()) if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line))
output=ROOT/'build/wave4d/tomokv-pad-a';link[link.index('-o')+1]=str(output);link.insert(link.index('-o'),str(obj))
subprocess.run(link,cwd=SRC,check=True)
assert text_size(output)==text_size(post)
receipt=dict(kind='A',scope=__doc__,source_revision='a44aef25c',build_argv=command,link_argv=link,padding_bytes=gap,
             arms={name:dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),text_bytes=text_size(path)) for name,path in [('merged',pre),('rebuilt_pre',rebuilt),('post',post),('pad_a',output)]})
(ROOT/'docs/wave4d/pad.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('PAD(A)',gap,receipt['arms']['pad_a'],flush=True)
