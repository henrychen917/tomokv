#!/usr/bin/env python3
"""PAD-A (behaviour twin): PRE objects linked with inert padding to POST's total .text size.

txnfix4 changes no type, layout lock, TLS or global data, so the twin keeps PRE's objects
byte-for-byte and appends one never-executed .text section of NOPs. It controls total text
size, not individual function addresses or alignment. Writes docs/txnfix4/binary-manifest.json.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lbstall_artifacts import Elf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/txnfix4/pre-source'
PAD = ROOT / 'build/txnfix4/pad-a'
SECTIONS = ('.text', '.rodata', '.data', '.bss', '.tbss', '.tdata')


def size(binary, name):
    elf = Elf(binary)
    return elf.sections[elf.names.index(name)][5] if name in elf.names else 0


def addr(binary, name):
    elf = Elf(binary)
    return elf.sections[elf.names.index(name)][3] if name in elf.names else 0


def end(binary, name):
    return addr(binary, name) + size(binary, name)


def main():
    PAD.mkdir(parents=True, exist_ok=True)
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'], cwd=PRE,
                                     text=True)
    command = shlex.split(next(line for line in recipe.splitlines() if ' -o build/tomokv ' in line))
    command = [str(PRE / arg) if arg.startswith('build/') else arg for arg in command]
    command[command.index('-o') + 1] = str(PAD / 'tomokv')
    subprocess.run(command, cwd=ROOT, check=True)
    padding = size(ROOT / 'build/tomokv', '.text') - size(PAD / 'tomokv', '.text')
    assert padding >= 0, padding
    note = Elf(PRE / 'build/src/cmd/xshard.o')
    note = note.section_data(note.names.index('.note.gnu.property'))
    assembly = PAD / 'padding.s'
    assembly.write_text('.section .text.txnfix4_pad_a,"ax",@progbits\n'
                        '.globl txnfix4_pad_a\n.type txnfix4_pad_a,@function\ntxnfix4_pad_a:\n'
                        f'.fill {padding},1,0x90\n.size txnfix4_pad_a,.-txnfix4_pad_a\n'
                        '.section .note.GNU-stack,"",@progbits\n'
                        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
                        ','.join(map(str, note)) + '\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
    command.insert(command.index('-o'), str(PAD / 'padding.o'))
    subprocess.run(command, cwd=ROOT, check=True)
    # Alignment of the appended section can round the first try; trim once to match exactly.
    extra = size(PAD / 'tomokv', '.text') - size(ROOT / 'build/tomokv', '.text')
    if extra:
        assembly.write_text(assembly.read_text().replace(f'.fill {padding},', f'.fill {padding - extra},'))
        padding -= extra
        subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
        subprocess.run(command, cwd=ROOT, check=True)
    assert size(PAD / 'tomokv', '.text') == size(ROOT / 'build/tomokv', '.text')
    # POST's new functions also grow its unwind tables (.eh_frame_hdr, .eh_frame,
    # .gcc_except_table), which moves its RELRO and data segments. Append the same number of
    # never-referenced bytes to the twin's .gcc_except_table, so .tdata, .data and .bss start
    # where POST's do. .rodata already starts at POST's address after the .text padding.
    ro_padding = end(ROOT / 'build/tomokv', '.gcc_except_table') - end(PAD / 'tomokv', '.gcc_except_table')
    assert ro_padding >= 0, ro_padding
    if ro_padding:
        assembly.write_text(assembly.read_text() +
                            '.section .gcc_except_table.txnfix4_pad_a,"a",@progbits\n'
                            f'.fill {ro_padding},1,0\n')
        subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
        subprocess.run(command, cwd=ROOT, check=True)
    assert size(PAD / 'tomokv', '.text') == size(ROOT / 'build/tomokv', '.text')
    placed = {name: (addr(PAD / 'tomokv', name), addr(ROOT / 'build/tomokv', name))
              for name in ('.text', '.rodata', '.tdata', '.tbss', '.data', '.bss')}
    assert all(a == b for a, b in placed.values()), placed
    arms = {}
    for arm, path in [('PRE', PRE / 'build/tomokv'), ('POST', ROOT / 'build/tomokv'),
                      ('PAD-A', PAD / 'tomokv')]:
        arms[arm] = dict(path=str(path.relative_to(ROOT)),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         sections={s: size(path, s) for s in SECTIONS},
                         addresses={s: hex(addr(path, s)) for s in SECTIONS})
    receipt = dict(kind='A: behaviour twin', padding_bytes=padding,
                   except_table_padding_bytes=ro_padding, arms=arms, link=command,
                   source='PRE objects from build/txnfix4/pre-source (git archive 9d6ab5526)',
                   layout='No struct, layout lock, TLS or global data changes in txnfix4; the twin '
                          'keeps PRE objects, adds one inert NOP .text section (POST .text size and '
                          '.rodata start) and unreferenced .gcc_except_table bytes (POST .tdata, '
                          '.data and .bss starts).',
                   limitation='Controls section extents and data addresses, not individual '
                              'function addresses or alignment; unwind-table contents differ.')
    (ROOT / 'docs/txnfix4/binary-manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(arms, indent=2))


if __name__ == '__main__':
    main()
