#!/usr/bin/env python3
"""Offline persistfix2 PRE/control linking and identity evidence. No workloads."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys

import lbstall_artifacts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/persistfix2'
DOCS = ROOT / 'docs/persistfix2'


def section(binary):
    elf = lbstall_artifacts.Elf(binary)
    row = elf.sections[elf.names.index('.text')]
    return dict(address=row[3], size=row[5])


def recipes():
    return subprocess.check_output(['make', '-Bn', 'all'], cwd=ROOT, text=True).splitlines()


def link_command(lines):
    commands = [shlex.split(line) for line in lines if line.startswith('g++ ') and
                ' -c ' not in line and ' -o build/tomokv ' in line]
    assert len(commands) == 1
    return commands[0]


def pad_link(link, output, kind, behavior):
    folder = WORK / kind
    folder.mkdir(parents=True, exist_ok=True)
    link[link.index('-o') + 1] = str(output)
    subprocess.run(link, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    original = section(output)
    wanted = section(ROOT / 'build/tomokv')
    if original['address'] != wanted['address']:
        # New dynamic-symbol metadata can move the default text start. Preserve
        # PRE objects and let the linker relocate them to POST's text address.
        link.append('-Wl,--section-start=.text=' + hex(wanted['address']))
        subprocess.run(link, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        original = section(output)
    assert original['address'] == wanted['address'], (original, wanted)
    padding = wanted['size'] - original['size']
    assert padding >= 5, (kind, padding)
    obj = folder / 'padding.o'
    assembly = folder / 'padding.S'
    link.insert(link.index('-o'), str(obj))
    for _ in range(6):
        assembly.write_text('.text\n.globl tomo_persistfix2_text_pad\n'
            '.type tomo_persistfix2_text_pad,@function\n'
            'tomo_persistfix2_text_pad:\nendbr64\nret\n.fill %d,1,0x90\n'
            '.size tomo_persistfix2_text_pad,.-tomo_persistfix2_text_pad\n'
            '.section .note.GNU-stack,"",@progbits\n'
            '.section .note.gnu.property,"a",@note\n.balign 8\n'
            '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n' % (padding - 5))
        subprocess.run(['g++', '-c', str(assembly), '-o', str(obj)], check=True)
        subprocess.run(link, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        actual = section(output)
        assert actual['address'] == wanted['address'], (actual, wanted)
        if actual == wanted:
            break
        padding += wanted['size'] - actual['size']
    assert actual == wanted, (actual, wanted)
    report = dict(kind=kind, behavior=behavior, binary=str(output.relative_to(ROOT)),
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        before_padding=original, after_padding=actual, padding_bytes=padding,
        matched='POST total .text size and start address',
        limitation='Individual function placement and data sections are not a symbol-for-symbol layout match.')
    (DOCS / (kind + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def build_pad():
    link = link_command(recipes())
    for i, word in enumerate(link):
        if word.startswith('build/') and word.endswith('.o'):
            frozen = WORK / 'pre' / word.removeprefix('build/')
            assert frozen.is_file(), frozen
            link[i] = str(frozen)
    pad_link(link, ROOT / 'build/tomokv-persistfix2-pad-a', 'pad-a',
             'A: behaviour twin. Unmodified PRE 05a5e01a9 objects with POST total text size.')


def build_control():
    folder = WORK / 'control-d8'
    folder.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'src/persist/aof.cc'
    text = source.read_text()
    original = '''bool AofManager::deny_command(Op& op) const {
    if (!command_metadata_write(op) && !op.cmd_name().eq_icase("ping")) return false;
    reply_write_error(op);
    return true;
}'''
    assert text.count(original) == 1
    control = folder / 'aof.cc'
    control.write_text(text.replace(original, 'bool AofManager::deny_command(Op&) const { return false; }'))
    lines = recipes()
    link = link_command(lines)
    for prefix in ('src', 'db0/src'):
        target = 'build/' + prefix + '/persist/aof.o'
        command, = [shlex.split(line) for line in lines
                    if ' -c src/persist/aof.cc ' in line and line.endswith(' -o ' + target)]
        output = folder / ('db0-aof.o' if prefix.startswith('db0') else 'aof.o')
        command[command.index('-c') + 1] = str(control)
        command[command.index('-o') + 1] = str(output)
        command.insert(command.index('-c'), '-Isrc/persist')
        subprocess.run(command, cwd=ROOT, check=True)
        link[link.index(target)] = str(output)
    pad_link(link, ROOT / 'build/tomokv-persistfix2-control-d8', 'control-d8',
             'Throwaway POST with only post-error command refusal removed; never a shipping arm.')


def identity():
    # Reuse both existing normalizers without altering their comparisons.
    (WORK / 'pre/tomokv').symlink_to('../../tomokv-persistfix2-pre') if not (WORK / 'pre/tomokv').exists() else None
    result = subprocess.run([sys.executable, 'tools/psfix_artifacts.py', str(WORK / 'pre'),
                             'build', str(DOCS / 'object-identity')], cwd=ROOT,
                            stdout=(WORK / 'object-identity.log').open('w'), stderr=subprocess.STDOUT)
    print('Object audit exit (identity is diagnostic):', result.returncode)
    hot = (ROOT / 'tools/serverfix_hot_identity.py').read_text().replace(
        'docs/serverfix/command-hot-identity.json', 'docs/persistfix2/command-hot-identity.json')
    previous = sys.argv
    sys.argv = ['persistfix2-hot', str(WORK / 'pre')]
    try:
        exec(compile(hot, str(ROOT / 'tools/serverfix_hot_identity.py'), 'exec'),
             {'__file__': str(ROOT / 'tools/serverfix_hot_identity.py'), '__name__': '__main__'})
    except SystemExit as exit_status:
        print('GET/SET/MGET/MSET audit exit:', exit_status.code)
    finally:
        sys.argv = previous
    source = (ROOT / 'tools/serverfix_identity.py').read_text().replace('serverfix', 'persistfix2')
    start = source.index("        reason = 'Compiler/link")
    end = source.index('        row = dict(', start)
    source = source[:start] + '''        if any(x in name for x in ('Aof', 'aof_', 'bgrewrite', 'persistence_command', 'schedule_offline')):
            reason = 'PS4.6/PS4.13/D8: rewrite attempt accounting, explicit disabled-AOF rewrite, scheduling, error admission and errno publication.'
        elif any(x in name for x in ('Snapshot', 'snapshot_', 'cmd_save', 'cmd_bgsave')):
            reason = 'PS4.6/PS4.12/PS4.13: RDB-only LASTSAVE, cancellation before final save, SAVE coordination and exact replies.'
        elif any(x in name.lower() for x in ('shutdown', 'signal_handler')):
            reason = 'PS4.12: modifiers, signal policies, pending ABORT and FORCE exit behavior.'
        elif any(x in name for x in ('Config', 'config', 'parse_args', 'cmd_info')):
            reason = 'PS4.12 and persistence telemetry: canonical signal policies in existing Config padding and INFO rewrite state.'
        elif any(x in name for x in ('multi_', 'Multi', 'command_metadata_write')):
            reason = 'D8: write classification and refusal of a queued write transaction, including WATCH retirement.'
        elif any(x in name for x in ('FunctionRegistry', 'invoke_fcall', 'function_metadata_write')):
            reason = 'D8: use registered no-writes flags for FCALL admission and recheck the selected callback after library replacement.'
        elif any(x in name for x in ('IoLoop', 'ExLoop', 'Server', 'ThreadCtx', 'main')):
            reason = 'Owner-loop integration for cold persistence commands/error admission; compiler propagation through existing inlined owner helpers.'
        else:
            reason = 'Compiler/link propagation or helper instantiation from persistence changes; the retained strict instruction diff identifies the actual change.'
''' + source[end:]
    exec(compile(source, str(ROOT / 'tools/serverfix_identity.py'), 'exec'),
         {'__file__': str(ROOT / 'tools/serverfix_identity.py'), '__name__': '__main__'})


def explain_hot():
    import psfix_artifacts as audit
    report = json.loads((DOCS / 'command-hot-identity.json').read_text())
    resolved = []
    for row in report['changed']:
        pre = audit.audit.Elf(WORK / 'pre' / row['object'])
        post = audit.audit.Elf(ROOT / 'build' / row['object'])
        old, new = pre.functions(), post.functions()
        a, b = old[row['symbol']], new[row['symbol']]
        aa, bb = pre.canonical(a), post.canonical(b)
        assert aa[1:] == bb[1:] and len(aa[0]) == len(bb[0])
        left, right = bytearray(aa[0]), bytearray(bb[0])
        references = []
        for offset in range(len(left)):
            if left[offset] == right[offset]:
                continue
            # GCC resolves same-section LEAs without ELF relocations. Validate
            # their exact opcode, destination symbol and unchanged target body.
            starts = [i for i in range(max(0, offset - 6), offset - 2)
                      if left[i:i + 3] == right[i:i + 3] == b'\x48\x8d\x3d'
                      and i + 3 <= offset < i + 7]
            assert len(starts) == 1, (row['name'], offset)
            start = starts[0]
            at = a['value'] + start + 7 + struct.unpack_from('<i', left, start + 3)[0]
            bt = b['value'] + start + 7 + struct.unpack_from('<i', right, start + 3)[0]
            names_a = {n for n, f in old.items() if f['sec'] == a['sec'] and f['value'] == at}
            names_b = {n for n, f in new.items() if f['sec'] == b['sec'] and f['value'] == bt}
            names = names_a & names_b
            assert names and all(pre.canonical(old[n]) == post.canonical(new[n]) for n in names)
            references.append(dict(offset=start, targets=sorted(names), target_body_equal=True))
            left[start + 3:start + 7] = right[start + 3:start + 7] = b'\0' * 4
        assert left == right
        resolved.append(dict(name=row['name'], same_section_references=references,
                             instruction_and_resolved_target_identity=True))
    # The strict linked normalizer uses objdump's nearest named symbol for one
    # literal. Compare the eight loaded bytes instead of accepting that label.
    literals = []
    for row in report['changed']:
        values = []
        for binary in (ROOT / 'build/tomokv-persistfix2-pre', ROOT / 'build/tomokv'):
            elf = audit.audit.Elf(binary)
            f = elf.functions()[row['symbol']]
            body = elf.body(f)
            offset = 0x4c15
            assert body[offset:offset + 3] == b'\x48\x8b\x05'
            address = f['value'] + offset + 7 + struct.unpack_from('<i', body, offset + 3)[0]
            index, = [i for i, s in enumerate(elf.sections) if s[3] <= address and address + 8 <= s[3] + s[5]
                      and s[3] != 0]
            position = address - elf.sections[index][3]
            values.append(elf.section_data(index)[position:position + 8].hex())
        assert values[0] == values[1]
        literals.append(dict(name=row['name'], offset=offset, pre_bytes=values[0], post_bytes=values[1]))
    output = dict(compared=report['compared'], stock_object_tool_changed=len(report['changed']),
                  resolved_differences=resolved, linked_literal_labels=literals,
                  all_hot_instructions_constants_and_targets_equal=True)
    (DOCS / 'hot-resolved-identity.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pad', 'control', 'identity', 'hot-explain'))
    args = parser.parse_args()
    DOCS.mkdir(parents=True, exist_ok=True)
    {'pad': build_pad, 'control': build_control, 'identity': identity, 'hot-explain': explain_hot}[args.action]()


if __name__ == '__main__':
    main()
