#!/usr/bin/env python3
"""Serverless PAD-A (PRE behaviour, POST text extent) and inverse PAD-B.

POST is smaller. PAD-A recompiles only PRE's GEO TU without alignment padding
then fills its linked text extent to POST. Main-command objects remain PRE.
It controls total text size, not individual function placement or GEO codegen.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cmdfix2'
DOC = ROOT / 'docs/cmdfix2'


def sections(path):
    e = Elf(path)
    return {n: dict(address=e.sections[e.names.index(n)][3], size=e.sections[e.names.index(n)][5])
            for n in ('.text', '.rodata', '.plt', '.plt.sec', '.data', '.bss')}


def link_recipe(source, objects):
    recipe = subprocess.check_output(['make', '-Bn', 'BUILD_ROOT=' + str(objects), 'all'], cwd=source, text=True)
    return shlex.split(next(l for l in recipe.splitlines() if l.startswith('g++ ') and
                           ' -c ' not in l and ' -o '+str(objects/'tomokv')+' ' in l))


def padded(label, source, objects, replacements, target, match_writable=False):
    link = [replacements.get(v, v) for v in link_recipe(source, objects)]
    assembly = OUT / (label + '.S'); obj = OUT / (label + '.o'); binary = OUT / label
    link.insert(link.index('-o'), str(obj)); link[link.index('-o') + 1] = str(binary)
    padding = 5
    readonly_padding = 0
    for attempt in range(4):
        assert padding >= 5, (label, padding)
        assembly.write_text('.text\n.globl tomo_cmdfix2_pad\n.type tomo_cmdfix2_pad,@function\n'
            'tomo_cmdfix2_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
            '.size tomo_cmdfix2_pad,.-tomo_cmdfix2_pad\n'
            '.section .note.GNU-stack,"",@progbits\n'
            '.section .note.gnu.property,"a",@note\n.balign 8\n'
            '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n'
            '.section .rodata.cmdfix2pad,"a",@progbits\n.fill %d,1,0\n'
            % (padding - 5, readonly_padding))
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(link, cwd=source, check=True, stdout=subprocess.DEVNULL)
        actual = sections(binary)
        assert actual['.text']['address'] == target['.text']['address'], (actual, target)
        if actual['.text'] == target['.text']:
            if match_writable and actual['.data']['address'] != target['.data']['address']:
                delta = target['.data']['address'] - actual['.data']['address']
                assert delta > 0, (label, actual, target)
                readonly_padding += delta
                continue
            break
        padding += target['.text']['size'] - actual['.text']['size']
    assert actual['.text'] == target['.text']
    if match_writable:
        assert all(actual[name]['address'] == target[name]['address'] for name in ('.data', '.bss'))
    return dict(padding_bytes=padding, readonly_padding_bytes=readonly_padding,
                sections=actual, target=target, link=link,
                sha256=hashlib.sha256(binary.read_bytes()).hexdigest())


def main():
    assert os.sched_getaffinity(0) <= set(range(100,112))
    source = OUT / 'pre-source'; objects = OUT / 'pre-objects'
    replacements = {}; compiles = []
    for ns in ('src', 'db0/src'):
        original = objects / ns / 'cmd/geo.o'; obj = OUT / ('pad-pre-geo-' + ns.replace('/', '-') + '.o')
        command = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
            '-falign-functions=1', '-falign-jumps=1', '-falign-loops=1', '-falign-labels=1',
            '-DTOMO_JEMALLOC', '-I'+str(source)]
        if ns.startswith('db0'): command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        command += ['-c', str(source/'src/cmd/geo.cc'), '-o', str(obj)]
        subprocess.run(command, check=True); compiles.append(command); replacements[str(original)] = str(obj)
    a = padded('PAD-A', source, objects, replacements, sections(OUT/'POST'), match_writable=True)
    a.update(kind='A: behaviour twin; total text extent control', source_commit='9d6ab5526',
        behavior='PRE source and objects; only PRE GEO compiled with alignment padding disabled', compiles=compiles,
        limitation='Not an exact symbol-layout twin. GEO code alignment/codegen can differ from PRE; do not attribute GEO rates from this control.')
    b = padded('PAD-B', ROOT, ROOT/'build', {}, sections(OUT/'PRE'))
    b.update(kind='B: inverse control', behavior='Unmodified POST objects plus unreachable text padding')
    for label, row in [('pad-a',a),('pad-b',b)]:
        (DOC/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
        print(label, row['sha256'], row['sections']['.text'], flush=True)


if __name__ == '__main__': main()
