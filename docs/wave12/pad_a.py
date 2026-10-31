#!/usr/bin/env python3
"""PAD-A (behaviour twin): PRE e32b04a44 behaviour linked to POST's .text origin and extent.

Derived from docs/pubtrackfix/layout_pad.py. The composite also includes FLUSH's inert GroupAux fields; the
PRE objects (build/wave12/pre-tree, built by instructions.py) are linked unchanged
plus one padding object: an unreachable .text filler that makes .text start and end where
POST's does, and an unused .tbss block that gives the TLS segment POST's size (POST adds
the 16-byte owner_memory_config_hook). No server, load generator or measurement.
Limitation: individual function, TLS-variable and data-section addresses come from the
PRE link; they are not matched to POST one by one.
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf  # noqa: E402

OUT = ROOT / 'build/wave12/pad-a'
SOURCE = ROOT / 'build/wave12/pre-source'
TREE = SOURCE / 'build'
DOC = ROOT / 'docs/wave12/pad-a.json'
PRE = ROOT / 'build/wave12/tomokv-PRE'
POST = ROOT / 'build/wave12/tomokv-POST'
os.sched_setaffinity(0, set(range(64, 96)))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def section(p, name):
    e = Elf(p)
    s = e.sections[e.names.index(name)]
    return dict(address=s[3], size=s[5])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recipe = subprocess.check_output(['make', 'BUILD_ROOT=' + str(TREE), '-n', '-W',
                                      str(TREE / 'src/main.o'), 'all'], cwd=SOURCE, text=True)
    link = shlex.split(next(s for s in recipe.splitlines()
                            if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    # Match the only grown private heap structure while retaining PRE logic.
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    copied = OUT / 'source'
    for directory in ('src', 'third_party'):
        shutil.copytree(SOURCE / directory, copied / directory, dirs_exist_ok=True)
    path = copied / 'src/cmd/scatter_engine.inc'
    old = path.read_text()
    anchor = '    bool flush_keys_built = false;'
    assert old.count(anchor) == 1
    path.write_text(old.replace(anchor, anchor + '\n    AtomicEntry* flush_range = nullptr;\n    bool flush_changed = false;'))
    replacements = []
    for variant in ('src/cmd/xshard.o', 'db0/src/cmd/xshard.o'):
        target = str(TREE / variant)
        recipe = subprocess.check_output(['make', 'BUILD_ROOT='+str(TREE), '-B', '-n', target], cwd=SOURCE, text=True)
        compile = shlex.split(next(line for line in reversed(recipe.splitlines()) if line.startswith('g++ ') and line.endswith(' -o '+target)))
        obj = OUT / variant.replace('/', '_')
        compile[compile.index('-o')+1] = str(obj)
        replacements.append((target, obj, compile))
    def compile_one(item):
        target, obj, command = item
        with obj.with_suffix('.log').open('w') as log:
            subprocess.run(command, cwd=copied, stdout=log, stderr=subprocess.STDOUT, check=True)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(compile_one, replacements))
    for target, obj, _ in replacements:
        link[link.index(target)] = str(obj)
    output = OUT / 'tomokv' 
    link[link.index('-o') + 1] = str(output)
    assembly, obj = OUT / 'padding.S', OUT / 'padding.o'
    link.insert(link.index('-o'), str(obj))
    want_text, want_tbss = section(POST, '.text'), section(POST, '.tbss')
    base_text, base_tbss = section(TREE / 'tomokv', '.text'), section(TREE / 'tomokv', '.tbss')
    link += ['-Wl,--section-start=.text=' + hex(want_text['address'])]
    # The first link's size adjustment also includes the inert GroupAux growth.
    padding = want_text['size'] - base_text['size']
    tls = want_tbss['size'] - base_tbss['size']
    assert padding >= 5 and tls >= 0, (padding, tls)
    for _ in range(8):
        assembly.write_text(
            '.text\n.balign 1\n.globl wave12_pad_a\n.type wave12_pad_a,@function\n'
            'wave12_pad_a:\nendbr64\nret\n'
            f'.fill {padding - 5},1,0x90\n.size wave12_pad_a,.-wave12_pad_a\n'
            + (f'.section .tbss,"awT",@nobits\n.balign 8\n.globl wave12_pad_tls\n'
               f'.type wave12_pad_tls,@object\nwave12_pad_tls:\n.zero {tls}\n'
               f'.size wave12_pad_tls,{tls}\n' if tls else '')
            + '.section .note.GNU-stack,"",@progbits\n.section .note.gnu.property,"a",@note\n'
              '.balign 8\n.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n')
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        with (OUT / 'link.log').open('w') as f:
            subprocess.run(link, cwd=SOURCE, stdout=f, stderr=subprocess.STDOUT, check=True)
        got_text, got_tbss = section(output, '.text'), section(output, '.tbss')
        if got_text == want_text and got_tbss['size'] == want_tbss['size']:
            break
        assert got_text['address'] == want_text['address'], (got_text, want_text)
        padding += want_text['size'] - got_text['size']
        tls += want_tbss['size'] - got_tbss['size']
    else:
        raise AssertionError((got_text, want_text, got_tbss, want_tbss))
    sections = {}
    for label, path in (('PRE', PRE), ('POST', POST), ('PAD-A', output)):
        e = Elf(path)
        sections[label] = {n: dict(address=s[3], size=s[5]) for n, s in zip(e.names, e.sections)
                           if n in ('.text', '.rodata', '.eh_frame', '.gcc_except_table', '.tdata',
                                    '.tbss', '.init_array', '.data', '.bss')}
    result = dict(
        kind='A: behaviour twin',
        behavior='PRE e32b04a44 with inert POST GroupAux fields and unused TLS padding',
        matched='POST GroupAux member layout; POST .text origin and total size; POST .tbss total size',
        private_layout=dict(file='src/cmd/scatter_engine.inc', additions=['AtomicEntry* flush_range = nullptr', 'bool flush_changed = false']),
        compile=[item[2] for item in replacements],
        limitation='Individual function, TLS-variable and data-section addresses come from the '
                   'PRE link; they are not matched to POST one by one.',
        link=link, padding_text_bytes=padding, padding_tbss_bytes=tls,
        pre_text=base_text, post_text=want_text, pad_text=got_text,
        pre_tbss=base_tbss, post_tbss=want_tbss, pad_tbss=got_tbss, sections=sections,
        inputs_sha256=hashlib.sha256(''.join(sha(x) for x in link if x.endswith('.o')).encode()).hexdigest(),
        arms={a: dict(path=str(p.relative_to(ROOT)), sha256=sha(p))
              for a, p in (('PRE', PRE), ('POST', POST), ('PAD-A', output))})
    DOC.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['arms'], indent=2), flush=True)


if __name__ == '__main__':
    main()
