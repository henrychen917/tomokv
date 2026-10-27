#!/usr/bin/env python3
"""Offline PAD-A: frozen PRE behaviour, padding to the candidate's .text size.

This controls total text footprint; it does not reproduce individual POST
function addresses. No server or performance work is started.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/blockfix2/pre-source/build'
PAD = ROOT / 'build/blockfix2/pad-a'


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


def main():
    PAD.mkdir(parents=True, exist_ok=True)
    source = PRE.parent
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'],
                                     cwd=source, text=True)
    command = next(shlex.split(line) for line in recipe.splitlines() if ' -o build/tomokv ' in line)
    command = [str(source / arg) if arg.startswith('build/') else arg for arg in command]
    command[command.index('-o') + 1] = str(PAD / 'tomokv')
    subprocess.run(command, cwd=ROOT, check=True)
    baseline = text_size(PAD / 'tomokv')
    assert baseline == text_size(PRE / 'tomokv'), 'frozen PRE reconstruction drift'
    candidate = text_size(ROOT / 'build/tomokv')
    padding = candidate - baseline
    assert padding >= 0, 'candidate shrank; appended PRE padding cannot form this control'
    elf = Elf(PRE / 'src/cmd/xshard.o')
    note = elf.section_data(elf.names.index('.note.gnu.property'))
    assembly = PAD / 'padding.s'
    assembly.write_text('.section .text.blockfix2_pad_a,"ax",@progbits\n'
        '.globl blockfix2_pad_a\n.type blockfix2_pad_a,@function\nblockfix2_pad_a:\n'
        f'.fill {padding},1,0x90\n.size blockfix2_pad_a,.-blockfix2_pad_a\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
        ','.join(map(str, note)) + '\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
    command.insert(command.index('-o'), str(PAD / 'padding.o'))
    subprocess.run(command, cwd=ROOT, check=True)
    assert text_size(PAD / 'tomokv') == candidate, 'PAD text-size mismatch'
    arms = {}
    for name, binary in [('PRE', PRE / 'tomokv'), ('POST', ROOT / 'build/tomokv'), ('PAD-A', PAD / 'tomokv')]:
        elf = Elf(binary)
        arms[name] = dict(path=str(binary.relative_to(ROOT)), text_bytes=text_size(binary),
            sha256=hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest(),
            sections={name: dict(address=section[3], bytes=section[5])
                      for name, section in zip(elf.names, elf.sections)
                      if name in ('.text', '.plt', '.plt.sec', '.tdata', '.tbss')})
    report = dict(kind='A: behaviour twin', padding_bytes=padding,
        limitation='PRE behaviour with POST total .text size; not an exact per-function layout twin.',
        pad_link=command, arms=arms)
    (ROOT / 'docs/blockfix2/binary-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(arms, indent=2))


if __name__ == '__main__': main()
