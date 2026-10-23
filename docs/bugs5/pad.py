"""PAD(A): PRE behavior and POST total .text size; not per-function placement."""
import hashlib,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
SRC=ROOT/'build/bugs5/pre-source';BASE=ROOT/'build/bugs5/pad';BASE.mkdir(exist_ok=True)
def size(path):
 e=Elf(path);return e.sections[e.names.index('.text')][5]
pre=ROOT/'build/tomokv-PRE';rebuilt=SRC/'build/tomokv';post=ROOT/'build/tomokv'
assert size(pre)==size(rebuilt)
gap=size(post)-size(rebuilt);assert gap>0,gap
asm=BASE/'pad.cc';obj=BASE/'pad.o'
asm.write_text('asm(R"(.pushsection .text.bugs5_pad,"ax",@progbits\n.fill '+str(gap)+',1,0x90\n.popsection\n)");\n')
subprocess.run(['g++','-std=c++20','-O2','-g','-march=native','-c',str(asm),'-o',str(obj)],check=True)
link=shlex.split(next(l for l in reversed((ROOT/'docs/bugs5/build-pre-rebuilt.log').read_text().splitlines()) if l.startswith('g++ ') and ' -Wl,--wrap=main ' in l))
output=ROOT/'build/tomokv-PAD-A';link[link.index('-o')+1]=str(output);link.insert(link.index('-o'),str(obj))
subprocess.run(link,cwd=SRC,check=True)
assert size(output)==size(post),(size(output),size(post))
receipt=dict(kind='A: behaviour twin',scope=__doc__,padding_bytes=gap,link_argv=link,
 arms={n:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),text_bytes=size(p)) for n,p in [('pre',pre),('rebuilt',rebuilt),('post',post),('pad_a',output)]})
(ROOT/'docs/bugs5/pad.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt['arms']),flush=True)
