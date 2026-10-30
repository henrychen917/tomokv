#!/usr/bin/env python3
"""Build command fixtures in the same two-image layout as PAD-A, no servers."""
import hashlib,json,re,struct,subprocess,shutil
from pathlib import Path
from exec1s_pad import recipe
from lbstall_artifacts import Elf
from exec1s_scope import BUILD,OUT,save,archive_probe
ROOT=Path(__file__).resolve().parents[1]
PAIR=ROOT/'build/exec1s'
PREFIX='exec1s_pre_'
def main():
    pre=PAIR/'pre-source'
    mapping=dict(line.split() for line in (PAIR/'pad-symbols.map').read_text().splitlines())
    old=recipe(pre,pre/'build')
    renamed=[str(PAIR/'pad-objects'/Path(x).relative_to(pre/'build')) for x in old
             if x.endswith('.o') and not x.endswith('/src/core/version.o')]
    for ns in ('normal','db0'):
        dest=BUILD/('PAD-A-'+ns);dest.mkdir(exist_ok=True)
        archive_probe('PAD-A',ns)
        flags=['g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(pre)]
        if ns=='db0':flags+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
        cmd=flags+['-c',str(ROOT/'tests/txnorder_command_scope.cc'),'-o',str(dest/'original-probe.o')]
        subprocess.run(cmd,check=True)
        names=set(mapping)
        for line in subprocess.check_output(['nm','-g','--defined-only','--format=posix',str(dest/'original-probe.o')],text=True).splitlines():
            if len(line.split())>=2:names.add(line.split()[0])
        groups=subprocess.check_output(['readelf','--section-groups',str(dest/'original-probe.o')],text=True)
        names.update(re.findall(r'COMDAT group section .*\[([^\]]+)\] contains',groups))
        table={name:mapping.get(name,PREFIX+name) for name in names};table['main']=PREFIX+'scope_main'
        rename=dest/'symbols.map';rename.write_text(''.join(f'{a} {b}\n' for a,b in sorted(table.items())))
        subprocess.run(['objcopy','--redefine-syms',str(rename),str(dest/'original-probe.o'),str(dest/'pre-probe.o')],check=True)
        link=recipe(ROOT,ROOT/'build')
        link=[str(BUILD/('POST-'+ns)/'original-main.o') if x==str(ROOT/'build/db0/src/main.o') else x for x in link]
        link[link.index('-o')+1]=str(dest/'post-layout-probe')
        at=link.index('-o');link[at:at]=renamed+[str(BUILD/('POST-'+ns)/'probe.o'),str(dest/'pre-probe.o')]
        with (OUT/('PAD-A-'+ns+'-build.log')).open('w') as log:
            subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
        elf=Elf(dest/'post-layout-probe');f=elf.functions();source=f['main'];target=f[PREFIX+'scope_main']
        section=elf.sections[source['sec']];offset=section[4]+source['value']-section[3];pc=source['value']
        raw=bytearray(elf.data)
        if raw[offset:offset+4]==b'\xf3\x0f\x1e\xfa':offset+=4;pc+=4
        raw[offset:offset+5]=b'\xe9'+struct.pack('<i',target['value']-(pc+5))
        binary=dest/'probe';binary.write_bytes(raw);binary.chmod(0o755)
        save(OUT/('PAD-A-'+ns+'-build.json'),dict(compile=cmd,link=link,
             kind='A: common layout with PRE command-scope entry',symbol_prefix=PREFIX,
             sha256=hashlib.sha256(raw).hexdigest(),post_sha256=hashlib.sha256(elf.data).hexdigest(),
             production_binary=str(ROOT/'build/exec1s-PAD-A'),
             production_sha256=hashlib.sha256((PAIR/'PAD-A').read_bytes()).hexdigest()))
        layout=BUILD/('POST-layout-'+ns);layout.mkdir(exist_ok=True)
        archive_probe('POST-layout',ns)
        shutil.copy2(dest/'post-layout-probe',layout/'probe')
        save(OUT/('POST-layout-'+ns+'-build.json'),dict(compile=cmd,link=link,
             kind='common layout with POST command-scope entry',
             sha256=hashlib.sha256(elf.data).hexdigest(),
             production_binary=str(ROOT/'build/exec1s-POST-layout'),
             production_sha256=hashlib.sha256((PAIR/'POST-layout').read_bytes()).hexdigest()))
        subprocess.run([str(binary),'GET','1s','1','1','-1'],check=True)
        print('PAD-A',ns,'scope built',flush=True)
if __name__=='__main__':main()
