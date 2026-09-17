#!/usr/bin/env python3
"""Build cumulative native arms and a function-layout-matched kind-A control, offline.

The native arm-5 is retained: padding only PRE to POST's total size is not an exact
layout control. The matched pair uses function sections and a union of fixed-size
function slots, so both sides receive the same link layout. No server is executed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess

from lbstall_artifacts import Elf


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/audit'


def run(args, log=None):
    print(shlex.join(map(str, args)), flush=True)
    if log:
        with Path(log).open('w') as stream:
            subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(args, cwd=ROOT, check=True)


def make_args(folder, arm, sections=False):
    return ['make', '-j8', f'BUILD={folder}', f'AUDIT_ARM={arm}',
            'CXX=g++ -ffunction-sections' if sections else 'CXX=g++', 'all']


def build(folder, arm, sections=False):
    folder.mkdir(parents=True, exist_ok=True)
    args = make_args(folder, arm, sections)
    run(args, folder / 'build.log')
    # Obtain the actual release link command, including the repository's allocator libraries.
    dry = subprocess.check_output(args[:1] + ['-nB'] + args[2:], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in dry.splitlines()
                if line.startswith('g++ ') and f'-o {folder}/tomokv ' in line]
    assert len(commands) == 1, 'one production link command required'
    link = commands[0]
    (folder / 'link.json').write_text(json.dumps(link, indent=2) + '\n')
    return link


def witness(folder, arm, expected=None):
    folder.mkdir(parents=True, exist_ok=True)
    run(['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
         f'-DTOMO_CACHE_AUDIT_ARM={arm}', '-I.', 'tests/cache_layout_test.cc',
         '-o', str(folder / 'layout-witness')], folder / 'witness-build.log')
    run([str(folder / 'layout-witness'), str(arm if expected is None else expected)],
        folder / 'witness.log')


def inputs(link, folder):
    """Index executable sections by COMDAT identity or object-local identity."""
    found = {}
    for filename in link:
        if not filename.endswith('.o'):
            continue
        elf = Elf(filename)
        groups = {}
        for section in elf.sections:
            if section[1] != 17:  # SHT_GROUP
                continue
            data = elf.data[section[4]:section[4] + section[5]]
            members = struct.unpack('<' + 'I' * (len(data) // 4), data)
            if members[0] & 1:  # GRP_COMDAT
                signature = elf.tables[section[6]][section[7]]['name']
                groups.update({index: signature for index in members[1:]})
        for index, section in enumerate(elf.sections):
            if not section[2] & 4 or not section[5]:
                continue
            name = elf.names[index]
            assert name.startswith('.text'), f'unexpected executable input: {name}'
            key = ('group', groups[index], name) if index in groups else (
                'local', str(Path(filename).relative_to(folder)), name)
            if key in found:
                assert key[0] == 'group', f'duplicate non-COMDAT section {key}'
                continue
            found[key] = dict(file=filename, section=name, size=section[5], align=section[8])
    assert found
    return found


def imports(post, pre, directory):
    # Put the same unreachable PLT references first in both links. Otherwise the aligned
    # allocation calls can change PLT size/order before .text, despite matching all functions.
    names = set()
    for path in (post, pre):
        elf = Elf(path)
        for index, section in enumerate(elf.sections):
            if section[1] == 11:  # SHT_DYNSYM
                names.update(s['name'].split('@')[0] for s in elf.tables[index]
                             if s['sec'] == 0 and s['info'] & 15 == 2)
    source = directory / 'imports.S'
    source.write_text('.section .text.audit_imports,"ax",@progbits\n.p2align 4\n'
                      '.globl __audit_imports\n.hidden __audit_imports\n'
                      '.type __audit_imports,@function\n__audit_imports:\nret\n' +
                      ''.join(f'call {name}@PLT\n' for name in sorted(names)) +
                      '.size __audit_imports,.-__audit_imports\n'
                      '.section .note.GNU-stack,"",@progbits\n')
    obj = directory / 'imports.o'
    run(['g++', '-c', str(source), '-o', str(obj)])
    return obj


def text_sections(elf):
    return [(name, s[3], s[4], s[5], s[8]) for name, s in zip(elf.names, elf.sections)
            if s[2] & 4]


def matched_pair():
    directory = OUT / 'matched'
    directory.mkdir(parents=True, exist_ok=True)
    folders = [directory / 'pre', directory / 'post']
    links = [build(folders[0], 0, True), build(folders[1], 5, True)]
    sections = [inputs(link, folder) for link, folder in zip(links, folders)]
    anchor = imports(folders[1] / 'tomokv', folders[0] / 'tomokv', directory)
    # Preserve POST's input order, reserving slots for PRE-only compiler clones as well.
    keys = list(sections[1]) + [key for key in sections[0] if key not in sections[1]]
    slots = []
    for key in keys:
        alternatives = [side[key] for side in sections if key in side]
        slots.append(dict(key=key, size=max(v['size'] for v in alternatives),
                          align=max(v['align'] for v in alternatives)))
    default = subprocess.check_output(['ld', '-pie', '--verbose'], text=True)
    default = default.split('==================================================')[1]
    marker = '  .text           :\n  {\n'
    assert default.count(marker) == 1, 'unknown GNU ld script format'
    outputs = [ROOT / 'build/tomokv-pad', ROOT / 'build/tomokv-layout']
    for side, (link, output) in enumerate(zip(links, outputs)):
        lines = [f'    KEEP("{anchor}"(.text.audit_imports))', '    FILL(0x90909090)']
        for number, slot in enumerate(slots):
            key = tuple(slot['key'])
            lines += [f'    . = ALIGN({max(16, slot["align"])});',
                      f'    __audit_slot_{number} = .;']
            if key in sections[side]:
                entry = sections[side][key]
                # Different COMDAT signatures can contain identically named local clones.
                # Match the selected object as well, never a global section-name wildcard.
                pattern = f'"{entry["file"]}"({entry["section"]})'
                lines.append(f'    KEEP({pattern})')
            lines.append(f'    . = __audit_slot_{number} + {slot["size"]};')
        script = directory / ('pre.ld' if side == 0 else 'post.ld')
        script.write_text(default.replace(marker, marker + '\n'.join(lines) + '\n'))
        command = link.copy()
        command.insert(1, str(anchor))
        command[command.index('-o') + 1] = str(output)
        command += [f'-Wl,-T,{script}', f'-Wl,-Map,{output}.map']
        run(command, directory / ('link-pre.log' if side == 0 else 'link-post.log'))
    pre, post = map(Elf, outputs)
    assert text_sections(pre) == text_sections(post), 'executable section layout mismatch'
    a, b = pre.functions(), post.functions()
    common = sorted(a.keys() & b.keys())
    mismatch = [name for name in common if a[name]['value'] != b[name]['value']]
    assert not mismatch, f'function entry mismatch: {mismatch[:10]}'
    for folder, arm in zip(folders, (0, 5)):
        witness(folder, arm)
    receipt = dict(kind='A: PRE data layout and allocation with matched POST function layout',
                   post=str(outputs[1].relative_to(ROOT)), pad=str(outputs[0].relative_to(ROOT)),
                   native_post='build/tomokv', native_pre='build/audit/arm-0/tomokv',
                   common_function_entries=len(common), function_entry_mismatches=0,
                   executable_sections=text_sections(post), reserved_function_slots=len(slots),
                   compiler_flag='-ffunction-sections on both matched arms only',
                   limitation='Function entry addresses and executable section extents match; '
                              'instruction and basic-block offsets within functions differ. '
                              'Use this PAD with tomokv-layout, not directly with native tomokv.',
                   sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in outputs})
    (directory / 'slots.json').write_text(json.dumps(slots, indent=2) + '\n')
    (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def manifest():
    paths = [ROOT / 'build/tomokv'] + [OUT / f'arm-{arm}/tomokv' for arm in range(6)]
    paths += [ROOT / 'build/tomokv-layout', ROOT / 'build/tomokv-pad']
    rows = []
    for path in paths:
        assert path.is_file(), path
        elf = Elf(path)
        rows.append(dict(binary=str(path.relative_to(ROOT)),
                         sha256=hashlib.sha256(elf.data).hexdigest(),
                         text_bytes=elf.sections[elf.names.index('.text')][5]))
    (OUT / 'manifest.json').write_text(json.dumps(rows, indent=2) + '\n')
    (OUT / 'SHA256SUMS').write_text(''.join(f'{r["sha256"]}  {r["binary"]}\n' for r in rows))
    print(json.dumps(rows, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('native', 'matched', 'manifest', 'all'))
    args = parser.parse_args()
    allowed = os.sched_getaffinity(0)
    assert allowed and allowed <= set(range(112, 128)), 'run under taskset -c 112-127'
    if args.mode in ('native', 'all'):
        build(ROOT / 'build', 5)
        for arm in range(6):
            folder = OUT / f'arm-{arm}'
            folder.mkdir(parents=True, exist_ok=True)
            if arm < 5:
                build(folder, arm)
            else:
                shutil.copy2(ROOT / 'build/tomokv', folder / 'tomokv')
            witness(folder, arm)
    if args.mode in ('matched', 'all'):
        matched_pair()
    if args.mode in ('manifest', 'all'):
        manifest()


if __name__ == '__main__':
    main()
