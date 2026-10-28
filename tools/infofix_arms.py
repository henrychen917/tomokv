#!/usr/bin/env python3
"""Link frozen PRE objects into a behaviour-twin PAD-A and cold-root regression.

No servers or benchmarks are launched. All input objects stay in this worktree.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BASE = '393d6ceb129d8c99dffd70959d6a19267c525fe0'
ARM = ROOT / 'build/infofix'
REPORT = ROOT / 'docs/infofix'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(path, name):
    elf = Elf(path)
    row = elf.sections[elf.names.index(name)]
    return dict(address=row[3], size=row[5])


def main():
    link = json.loads((REPORT / 'pre-link.json').read_text())
    post = ARM / 'post/tomokv'
    post.parent.mkdir(exist_ok=True)
    import shutil
    shutil.copy2(ROOT / 'build/tomokv', post)
    pre = ARM / 'pre/tomokv'
    wanted = section(post, '.text')
    previous = section(pre, '.text')
    rodata = max(0, section(post, '.rodata')['size'] - section(pre, '.rodata')['size'])
    padding = wanted['size'] - previous['size']
    pad = ARM / 'pad-a/tomokv'
    pad.parent.mkdir(exist_ok=True)
    asm, obj = pad.parent / 'padding.S', pad.parent / 'padding.o'
    cmd = [str(ARM / 'pre' / x.removeprefix('build/')) if x.endswith('.o') and x.startswith('build/') else x for x in link]
    cmd[cmd.index('-o') + 1] = str(pad)
    cmd.insert(cmd.index('-o'), str(obj))
    cmd.append(f'-Wl,--section-start=.text=0x{wanted["address"]:x}')
    for _ in range(6):
        if padding < 5:
            raise RuntimeError('POST text is too small for additive PRE-behaviour PAD-A')
        asm.write_text('.text\n.globl tomo_infofix_unused_pad\n'
            '.type tomo_infofix_unused_pad,@function\ntomo_infofix_unused_pad:\n'
            'endbr64\nret\n.fill %d,1,0x90\n'
            '.size tomo_infofix_unused_pad,.-tomo_infofix_unused_pad\n'
            '.section .rodata\n.fill %d,1,0\n'
            '.section .note.GNU-stack,"",@progbits\n'
            '.section .note.gnu.property,"a",@note\n.balign 8\n'
            '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n' % (padding - 5, rodata))
        subprocess.run(['g++', '-c', str(asm), '-o', str(obj)], check=True)
        subprocess.run(cmd, cwd=ROOT, check=True)
        actual = section(pad, '.text')
        if actual == wanted:
            break
        if actual['address'] != wanted['address']:
            raise RuntimeError((actual, wanted))
        padding += wanted['size'] - actual['size']
    assert section(pad, '.text') == wanted
    mutant = ARM / 'regression/tomokv'
    mutant.parent.mkdir(exist_ok=True)
    restored = ('/cmd/t_server.o', '/cmd/cmdmeta.o', '/cmd/slowlog.o', '/cmd/xshard.o')
    regression = [str(ARM / 'pre' / x.removeprefix('build/'))
        if x.endswith(restored) else x for x in link]
    regression[regression.index('-o') + 1] = str(mutant)
    subprocess.run(regression, cwd=ROOT, check=True)
    report = dict(base=BASE, pad_kind='A: behaviour twin',
        pad_behaviour='Unmodified PRE production objects; only unreachable code/data padding added.',
        pad_match='POST .text virtual start and total size; additive .rodata size control.',
        pad_limitation='Individual function/data placement is not identical to POST; no exact symbol-layout claim.',
        padding_bytes=padding, rodata_padding=rodata,
        regression='POST with PRE t_server/cmdmeta/slowlog/xshard objects in both namespaces; restores all four cold compatibility defects.',
        arms={name:dict(path=str(path.relative_to(ROOT)), sha256=digest(path),
                       text=section(path,'.text'), rodata=section(path,'.rodata'))
              for name,path in [('PRE',pre),('POST',post),('PAD-A',pad),('REGRESSION',mutant)]},
        pad_link=cmd, regression_link=regression)
    (REPORT / 'arms.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k: v for k,v in report.items() if not k.endswith('_link')},indent=2))


if __name__ == '__main__':
    main()
