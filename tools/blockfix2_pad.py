#!/usr/bin/env python3
"""Offline PAD-A: PRE behaviour, POST BlockingState layout and .text size.

This controls total text footprint; it does not reproduce individual POST
function addresses. No server or performance work is started.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shlex
import shutil
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
    overlay = PAD / 'source'
    if overlay.exists(): shutil.rmtree(overlay)
    shutil.copytree(source / 'src', overlay / 'src')
    blocking = overlay / 'src/cmd/blocking.inc'
    text = blocking.read_text()
    marker = '    std::atomic<bool> counted{false};'
    assert text.count(marker) == 1
    # Inert fields: exact candidate offsets and allocation size, PRE behaviour.
    # Unused padding has no initialization or lifetime work.
    text = text.replace(marker, marker + '\n    BlockingState* count_previous;\n'
                        '    BlockingState* count_next;\n    bool count_linked;', 1)
    blocking.write_text(text)
    (overlay / 'tests').mkdir()
    for name in ['blockfix2_unit.cc', 'atomic_survivors_unit.cc']:
        shutil.copy2(source / 'tests' / name, overlay / 'tests' / name)
    for path in (source / 'tests').glob('*.inc'):
        shutil.copy2(path, overlay / 'tests' / path.name)
    jobs = []
    replacements = {}
    for ns in ['normal', 'db0']:
        obj = 'build/' + ('db0/' if ns == 'db0' else '') + 'src/cmd/xshard.o'
        lines = subprocess.check_output(['make', '-n', '-B', obj], cwd=source, text=True)
        compile_command = shlex.split(next(line for line in lines.splitlines()
                                          if line.endswith(' -o ' + obj)))
        compile_command = [str(overlay / arg) if arg == 'src/cmd/xshard.cc' else arg
                           for arg in compile_command]
        compile_command[compile_command.index('-o') + 1] = str(PAD / (ns + '-xshard.o'))
        replacements[str(source / obj)] = str(PAD / (ns + '-xshard.o'))
        jobs.append((compile_command, PAD / (ns + '-build.log')))
    def compile_one(job):
        command, log = job
        with log.open('w') as output:
            subprocess.run(command, cwd=source, stdout=output, stderr=subprocess.STDOUT, check=True)
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(compile_one, jobs))
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'],
                                     cwd=source, text=True)
    command = next(shlex.split(line) for line in recipe.splitlines() if ' -o build/tomokv ' in line)
    command = [str(source / arg) if arg.startswith('build/') else arg for arg in command]
    command = [replacements.get(arg, arg) for arg in command]
    command[command.index('-o') + 1] = str(PAD / 'tomokv')
    subprocess.run(command, cwd=ROOT, check=True)
    baseline = text_size(PAD / 'tomokv')
    layout = subprocess.check_output(['gdb', '-nx', '-batch',
        '-ex', 'p sizeof(tomo::BlockingState)', '-ex', 'p sizeof(tomo_db0::BlockingState)',
        str(PAD / 'tomokv')], text=True)
    assert layout.strip().splitlines() == ['$1 = 240', '$2 = 240'], layout
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
    for name, binary in [('PRE', PRE / 'tomokv'), ('POST', ROOT / 'build/blockfix2/post/tomokv'), ('PAD-A', PAD / 'tomokv')]:
        elf = Elf(binary)
        arms[name] = dict(path=str(binary.relative_to(ROOT)), text_bytes=text_size(binary),
            sha256=hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest(),
            sections={name: dict(address=section[3], bytes=section[5])
                      for name, section in zip(elf.names, elf.sections)
                      if name in ('.text', '.plt', '.plt.sec', '.tdata', '.tbss')})
    report = dict(kind='A: behaviour twin', padding_bytes=padding,
        blocking_state_bytes=dict(PRE=216, POST=240, PAD_A=240),
        limitation='PRE behaviour with POST BlockingState layout and total .text size; not an exact per-function text-layout twin.',
        pad_compile=[job[0] for job in jobs], pad_link=command, arms=arms)
    (ROOT / 'docs/blockfix2/binary-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    # The serverless refusal witnesses must use the same inert field layout.
    jobs = []
    for name in ['blockfix2-unit', 'blockfix2-db0-unit']:
        recipe = subprocess.check_output(['make', '-n', '-B', '-f', 'Makefile', '-f',
            'tools/blockfix2.mk', 'build/' + name], cwd=source, text=True)
        unit = shlex.split(next(line for line in recipe.splitlines() if ' -o build/' + name + ' ' in line))
        unit = [str(source / arg) if arg.startswith('build/') else arg for arg in unit]
        unit = [replacements.get(arg, arg) for arg in unit]
        unit = [str(overlay / arg) if arg == 'tests/blockfix2_unit.cc' else arg for arg in unit]
        unit.insert(unit.index('-I.'), '-I' + str(overlay))
        unit[unit.index('-o') + 1] = str(PAD / name)
        jobs.append((unit, PAD / (name + '-build.log')))
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(compile_one, jobs))
    print(json.dumps(arms, indent=2))


if __name__ == '__main__': main()
