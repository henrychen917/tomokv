#!/usr/bin/env python3
"""Build an aggregate PAD-A: headline behavior, candidate private structures/text.

No production code is changed. Every source/build artifact stays in this worktree.
Function addresses are not individually matched; the receipt states that limit.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

OUT = ROOT / 'build/wave13/pad-a'
SOURCE = OUT / 'source'
PRE_SOURCE = ROOT / 'build/wave13/pre-source'
POST = ROOT / 'build/wave13/tomokv-POST'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def sections(path):
    elf = Elf(path)
    return {n: dict(address=s[3], size=s[5]) for n, s in zip(elf.names, elf.sections)
            if n in ('.text', '.rodata', '.data', '.bss', '.tbss', '.tdata')}


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    os.environ['LC_ALL'] = 'C'
    SOURCE.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'third_party', 'tools'):
        shutil.copytree(PRE_SOURCE / directory, SOURCE / directory, dirs_exist_ok=True)
    shutil.copy2(PRE_SOURCE / 'Makefile', SOURCE / 'Makefile')
    # These declarations add only empty/inert storage to PRE's implementation.
    shutil.copy2(ROOT / 'src/snapshot/snapshot.h', SOURCE / 'src/snapshot/snapshot.h')
    path = SOURCE / 'src/core/server.h'
    text = path.read_text()
    anchor = '    std::atomic<uint64_t> debug_script_stage_watch_tasks_{0};'
    addition = '''
    alignas(64) std::atomic<uint64_t> flip_session_clients_transferred_{0};
    std::atomic<uint64_t> flip_refused_s2_{0};
    std::atomic<uint64_t> flip_refused_close_{0};'''
    assert text.count(anchor) == 1
    path.write_text(text.replace(anchor, anchor + '\n' + addition))
    with (OUT / 'build.log').open('w') as log:
        subprocess.run(['make', '-j16', 'all'], cwd=SOURCE, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    objects = SOURCE / 'build'
    recipe = subprocess.check_output(['make', 'BUILD_ROOT=' + str(objects), '-n',
                                      '-W', str(objects / 'src/main.o'), 'all'],
                                     cwd=SOURCE, text=True)
    link = shlex.split(next(s for s in recipe.splitlines()
                           if ' -Wl,--wrap=main ' in s))
    binary = OUT / 'tomokv'
    link[link.index('-o') + 1] = str(binary)
    desired, baseline = sections(POST), sections(objects / 'tomokv')
    padding = {n: desired[n]['size'] - baseline[n]['size'] for n in ('.text', '.rodata')}
    assert min(padding.values()) >= 0, padding
    assembly, obj = OUT / 'padding.S', OUT / 'padding.o'
    link += [str(obj), '-Wl,--section-start=.text=' + hex(desired['.text']['address'])]
    for _ in range(8):
        assembly.write_text('.text\n.balign 1\n.globl wave13_pad_a\n'
                            '.type wave13_pad_a,@function\nwave13_pad_a:\n'
                            f'.fill {padding[".text"]},1,0x90\n.size wave13_pad_a,.-wave13_pad_a\n'
                            f'.section .rodata\n.fill {padding[".rodata"]},1,0\n'
                            '.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        with (OUT / 'link.log').open('w') as log:
            subprocess.run(link, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT, check=True)
        actual = sections(binary)
        if actual['.text'] == desired['.text'] and actual['.rodata']['size'] == desired['.rodata']['size']:
            break
        assert actual['.text']['address'] == desired['.text']['address']
        for name in padding:
            padding[name] += desired[name]['size'] - actual[name]['size']
            assert padding[name] >= 0
    else:
        raise AssertionError((actual, desired))
    delivered = ROOT / 'build/wave13/tomokv-PAD-A'
    shutil.copy2(binary, delivered)
    shutil.copy2(objects / 'tomokv.asserts.tsv', str(delivered) + '.asserts.tsv')
    receipt = dict(kind='A: behavior twin', behavior='7d2f8a205 headline behavior',
                   private_layout='POST SnapshotManager/SnapshotLoadPlan and Server diagnostic tail fields; unused in PRE',
                   matched='POST .text origin/extent and .rodata size; private structure offsets',
                   limitation='Individual function/data addresses are not matched; this aggregate control cannot isolate every placement effect.',
                   padding=padding, link=link, pre_sections=sections(ROOT / 'build/wave13/tomokv-PRE'),
                   post_sections=desired, pad_sections=actual,
                   post_sha256=sha(POST), pad_sha256=sha(delivered),
                   header_sha256={str(p.relative_to(SOURCE)): sha(p) for p in
                                  (SOURCE / 'src/snapshot/snapshot.h', path)})
    (ROOT / 'docs/wave13/pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
