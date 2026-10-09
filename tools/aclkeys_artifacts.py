#!/usr/bin/env python3
"""Offline ACL lane evidence and inverse text-size control; never runs a server."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

import lbstall_artifacts as audit
from psfix_artifacts import layouts
from rlfence_artifacts import instructions


def arm(path):
    elf = audit.Elf(path)
    return dict(sha256=hashlib.sha256(elf.data).hexdigest(),
                text_bytes=elf.sections[elf.names.index('.text')][5])


def instruction_count(path, symbol):
    text = subprocess.check_output(
        ['objdump', '-dw', '--disassemble=' + symbol, str(path)], text=True)
    return len(instructions(text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--link-log', type=Path, required=True)
    parser.add_argument('--pad', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    arms = {name: arm(root / 'tomokv') for name, root in
            (('PRE', args.pre), ('POST', args.post))}
    before, after = layouts(args.pre / 'tomokv'), layouts(args.post / 'tomokv')
    assert before == after, 'size or member layout changed'
    (args.output / 'layouts.json').write_text(json.dumps(before, indent=2) + '\n')

    # ccfix_audit inventories the union of bodies in every PRE object. Explicitly
    # account for the new feature objects too, including their compiler helpers.
    added = []
    for obj in sorted(args.post.rglob('*.o')):
        relative = obj.relative_to(args.post)
        if (args.pre / relative).exists():
            continue
        elf = audit.Elf(obj)
        for symbol, body in elf.functions().items():
            added.append(dict(object=str(relative), symbol=symbol, bytes=body['size'],
                              instructions=instruction_count(obj, symbol)))
    changed = json.loads((args.output / 'changed-bodies.json').read_text())
    for row in changed:
        for name, root in (('pre', args.pre), ('post', args.post)):
            row[name + '_instructions'] = (instruction_count(root / row['object'], row['symbol'])
                                           if row[name + '_size'] else 0)
        symbol = row['symbol']
        if '14acl_check_keys' in symbol:
            row['reason'] = 'ACL key extraction and its argument-view callback'
        elif '19acl_pattern_allowed' in symbol:
            row['reason'] = 'ACL key-pattern predicate moved to aclkeys.cc'
        else:
            row['reason'] = 'Unresolved cold code-generation drift in the changed ACL TU'
    (args.output / 'changed-bodies.json').write_text(json.dumps(changed, indent=2) + '\n')
    (args.output / 'added-bodies.json').write_text(json.dumps(added, indent=2) + '\n')

    # Type B: candidate behavior with padding restoring PRE's total .text size.
    # Preserve GNU property notes: otherwise adding an unannotated assembly object
    # silently removes CET properties and changes the PLT and .text start address.
    delta = arms['PRE']['text_bytes'] - arms['POST']['text_bytes']
    assert delta >= 4, 'this inverse control requires a shrinking candidate'
    args.pad.mkdir(parents=True, exist_ok=True)
    source_object = audit.Elf(args.post / 'src/cmd/acl.o')
    prop = source_object.section_data(source_object.names.index('.note.gnu.property'))
    property_path = (args.pad / 'property.bin').resolve()
    property_path.write_bytes(prop)
    assembly = args.pad / 'pad.s'
    assembly.write_text(
        '.section .text\n.balign 1\n.globl tomo_aclkeys_inverse_pad\n'
        '.type tomo_aclkeys_inverse_pad,@function\ntomo_aclkeys_inverse_pad:\n'
        '.byte 0xf3,0x0f,0x1e,0xfa\n' + f'.fill {delta - 4},1,0x90\n'
        '.size tomo_aclkeys_inverse_pad,.-tomo_aclkeys_inverse_pad\n'
        '.section .note.GNU-stack,"",@progbits\n'
        '.section .note.gnu.property,"a",@note\n.p2align 3\n'
        f'.incbin "{property_path}"\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(args.pad / 'pad.o')], check=True)
    link = next(shlex.split(line) for line in reversed(args.link_log.read_text().splitlines())
                if line.startswith('g++ ') and ' -o ' + str(args.post / 'tomokv') + ' ' in line)
    link.insert(link.index('-o'), str(args.pad / 'pad.o'))
    link[link.index('-o') + 1] = str(args.pad / 'tomokv')
    subprocess.run(link, check=True)
    arms['PAD-B'] = arm(args.pad / 'tomokv')
    assert arms['PAD-B']['text_bytes'] == arms['PRE']['text_bytes']
    post, pad = audit.Elf(args.post / 'tomokv'), audit.Elf(args.pad / 'tomokv')
    assert post.section_data(post.names.index('.note.gnu.property')) == \
        pad.section_data(pad.names.index('.note.gnu.property'))
    old, new = post.functions(), pad.functions()
    existing_text = [name for name, fn in old.items() if post.names[fn['sec']] == '.text']
    assert all((old[name]['value'], old[name]['size']) ==
               (new[name]['value'], new[name]['size']) for name in existing_text)
    result = dict(arms=arms, layouts_equal=True, new_object_bodies=len(added),
                  pad_kind='B: candidate behavior plus padding restoring PRE total .text size',
                  pad_bytes=delta, pad_existing_text_addresses_equal=len(existing_text),
                  pad_limitation='Does not restore PRE per-function addresses or data layout')
    (args.output / 'artifacts.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
