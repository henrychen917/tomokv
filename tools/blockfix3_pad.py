#!/usr/bin/env python3
"""PAD-A: PRE behaviour, inert POST cold-statistics layout and total text size."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'build/blockfix3/pre-source'
PAD = ROOT / 'build/blockfix3/pad-a'


def size(binary, name):
    elf = Elf(binary)
    return elf.sections[elf.names.index(name)][5]


def main():
    PAD.mkdir(parents=True, exist_ok=True)
    source = PAD / 'source'
    shutil.copytree(PRE / 'src', source / 'src', dirs_exist_ok=True)
    path = source / 'src/cmd/t_server.cc'
    text = path.read_text()
    marker = '    std::vector<uint64_t> rejected_calls, failed_calls;'
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, marker + '\n    uint64_t blockfix3_inert_stats[2];', 1))
    path = source / 'src/cmd/t_stream_groups.cc'
    text = path.read_text()
    marker = 'constexpr uint32_t kMaxIdText = 128;'
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, marker + '\n'
        '[[gnu::used]] std::atomic<uint64_t> xreadgroup_nogroup{0};\n'
        '[[gnu::used]] std::atomic<uint64_t> xreadgroup_usec{0};', 1))
    replacements = {}
    compiles = []
    for namespace in ('', 'db0/'):
        for unit in ('t_server', 't_stream_groups'):
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
    assembly.write_text('.section .text.blockfix3_pad_a,"ax",@progbits\n'
        '.globl blockfix3_pad_a\n.type blockfix3_pad_a,@function\nblockfix3_pad_a:\n'
        f'.fill {padding},1,0x90\n.size blockfix3_pad_a,.-blockfix3_pad_a\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' + ','.join(map(str, note)) + '\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(PAD / 'padding.o')], check=True)
    command.insert(command.index('-o'), str(PAD / 'padding.o'))
    subprocess.run(command, cwd=ROOT, check=True)
    assert size(PAD / 'tomokv', '.text') == size(ROOT / 'build/tomokv', '.text')
    arms = {}
    for arm, path in [('PRE', ROOT / 'build/blockfix3/pre/tomokv'),
                      ('POST', ROOT / 'build/tomokv'), ('PAD-A', PAD / 'tomokv')]:
        arms[arm] = dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         sections={s: size(path, s) for s in ('.text', '.bss', '.data', '.tbss')})
    receipt = dict(kind='A: behaviour twin', padding_bytes=padding, arms=arms, compile=compiles, link=command,
        layout='PRE BlockingState and locked layouts equal POST; inert 16-byte StatBaseline tail and two 8-byte stream counters per namespace match POST cold data.',
        limitation='Controls total text size and cold data sizes, not individual function addresses or alignment.')
    (ROOT / 'docs/blockfix3/binary-manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    shutil.rmtree(source)
    print(json.dumps(arms, indent=2))


if __name__ == '__main__': main()
