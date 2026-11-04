#!/usr/bin/env python3
"""PAD-A: PRE behaviour, inert POST blocking-registry layout and total text size."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/blockfix4/pre-source'
PAD = ROOT / 'build/blockfix4/pad-a'


def size(binary, name):
    elf = Elf(binary)
    return elf.sections[elf.names.index(name)][5]


def main():
    PAD.mkdir(parents=True, exist_ok=True)
    source = PAD / 'source'
    shutil.copytree(PRE / 'src', source / 'src', dirs_exist_ok=True)
    path = source / 'src/cmd/blocking.inc'
    text = path.read_text()
    marker = '    std::unordered_map<BlockingQueueKey, BlockingQueue, BlockingQueueHash, BlockingQueueEqual> queues_;'
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, '    bool blockfix4_inert_servicing_ = false;\n' + marker, 1))
    replacements = {}
    compiles = []
    for namespace in ('', 'db0/'):
        for unit in ('xshard',):
            target = 'build/' + namespace + 'src/cmd/' + unit + '.o'
            recipe = subprocess.check_output(['make', '-n', '-B', target], cwd=PRE, text=True)
            command = shlex.split(next(line for line in recipe.splitlines() if line.endswith(' -o ' + target)))
            output = PAD / (('db0-' if namespace else '') + unit + '.o')
            command = [str(source / arg) if arg == 'src/cmd/' + unit + '.cc' else arg for arg in command]
            command[command.index('-o') + 1] = str(output)
            subprocess.run(command, cwd=PRE, check=True)
            replacements[str(PRE / target)] = str(output)
            compiles.append(command)
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'], cwd=PRE, text=True)
    command = shlex.split(next(line for line in recipe.splitlines() if ' -o build/tomokv ' in line))
    command = [str(PRE / arg) if arg.startswith('build/') else arg for arg in command]
    command = [replacements.get(arg, arg) for arg in command]
    command[command.index('-o') + 1] = str(PAD / 'tomokv')
    subprocess.run(command, cwd=ROOT, check=True)
    padding = size(ROOT / 'build/tomokv', '.text') - size(PAD / 'tomokv', '.text')
    assert padding >= 0, padding
    elf = Elf(PRE / 'build/src/cmd/xshard.o')
    note = elf.section_data(elf.names.index('.note.gnu.property'))
    assembly = PAD / 'padding.s'
    assembly.write_text('.section .text.blockfix4_pad_a,"ax",@progbits\n'
        '.globl blockfix4_pad_a\n.type blockfix4_pad_a,@function\nblockfix4_pad_a:\n'
        f'.fill {padding},1,0x90\n.size blockfix4_pad_a,.-blockfix4_pad_a\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' + ','.join(map(str, note)) + '\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
    command.insert(command.index('-o'), str(PAD / 'padding.o'))
    subprocess.run(command, cwd=ROOT, check=True)
    assert size(PAD / 'tomokv', '.text') == size(ROOT / 'build/tomokv', '.text')
    arms = {}
    for arm, path in [('PRE', PRE / 'build/tomokv'),
                      ('POST', ROOT / 'build/tomokv'), ('PAD-A', PAD / 'tomokv')]:
        arms[arm] = dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         sections={s: size(path, s) for s in ('.text', '.bss', '.data', '.tbss')})
    receipt = dict(kind='A: behaviour twin', padding_bytes=padding, arms=arms, compile=compiles, link=command,
        layout='PRE behaviour with the POST BlockingRegistry bool and map offset; all locked types, TLS and global data unchanged.',
        limitation='Controls total text size and registry layout, not individual function addresses or alignment.')
    (ROOT / 'docs/blockfix4/binary-manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    shutil.rmtree(source)
    print(json.dumps(arms, indent=2))


if __name__ == '__main__': main()
