#!/usr/bin/env python3
"""Offline exact-layout PAD-A and one-helper sanitizer-bypass control.

Restore PRE cold error writers in POST's existing function slots. All section
and symbol addresses/sizes stay fixed; no source tree, server or measurement.
The control restores just FUNCTION's error helper in both namespaces. PAD-A
also restores script raw errors and PRE's map-without-trim error semantics.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import instructions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/crlffix/arms'
PROOF = ROOT / 'docs/crlffix/arms'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def offset(elf, address):
    candidates = [s[4] + address - s[3] for s in elf.sections
                  if s[2] & 2 and s[3] <= address < s[3] + s[5] and s[1] != 8]
    assert len(candidates) == 1, hex(address)
    return candidates[0]


def main():
    PROOF.mkdir(parents=True, exist_ok=True)
    pre, post = Elf(OUT / 'PRE'), Elf(OUT / 'POST')
    old_ins = instructions(subprocess.check_output(['objdump', '-dw', str(pre.path)], text=True))
    new_ins = instructions(subprocess.check_output(['objdump', '-dw', str(post.path)], text=True))
    # Include PLT names as relocation targets, as well as defined ELF symbols.
    symbols = {s['name']: s['value'] for s in post.symbols if s['sec'] and s['size']}
    for address, _, _, owner in new_ins:
        if owner and owner.endswith('@plt'): symbols.setdefault(owner, address)
    old_by_address = {s['value']: s['name'] for s in pre.symbols if s['size']}

    def transplant(old, dest):
        body = bytearray(pre.body(old))
        for pc, raw, asm, owner in old_ins:
            if not old['value'] <= pc < old['value'] + old['size']: continue
            here = dest + pc - old['value']
            direct = re.match(r'(?:call|jmp|j\w+)\s+([0-9a-f]+)\s+<([^>]+)>', asm)
            if direct:
                target = int(direct[1], 16)
                if old['value'] <= target < old['value'] + old['size']: continue
                assert len(raw) in (5, 6), (asm, raw.hex())
                name = old_by_address.get(target, direct[2])
                if '15reply_line_textI' in name:
                    name = name.replace('15reply_line_textI', '15reply_line_textILb0E')
                assert name in symbols, name
                struct.pack_into('<i', body, pc - old['value'] + len(raw) - 4,
                                 symbols[name] - here - len(raw))
            if '%rip' in asm:
                match = re.search(r'# ([0-9a-f]+)', asm)
                assert match, asm
                target = int(match[1], 16)
                before = offset(pre, target)
                # The donors only reference the literal CRLF terminator.
                assert pre.data[before:before + 3] == b'\r\n\0', asm
                ro = post.sections[post.names.index('.rodata')]
                at = post.section_data(post.names.index('.rodata')).find(b'\r\n\0')
                assert at >= 0
                struct.pack_into('<i', body, pc - old['value'] + len(raw) - 4,
                                 ro[3] + at - here - len(raw))
        return bytes(body)

    changes = []

    def patch(address, data, purpose, control=False):
        at = offset(post, address)
        assert all(at + len(data) <= p['offset'] or p['offset'] + len(bytes.fromhex(p['after'])) <= at
                   for p in changes), 'overlapping patches'
        changes.append(dict(address=address, offset=at, before=post.data[at:at+len(data)].hex(),
                            after=data.hex(), purpose=purpose, control=control))

    for ns in ('4tomo', '8tomo_db0'):
        prefix = '_ZN' + ns
        donors = [s for s in pre.symbols if s['name'].startswith(prefix) and
                  '16reply_text_error' in s['name'] and s['size'] == 0x1df]
        assert len(donors) == 1
        donor = donors[0]
        targets = [s for s in post.symbols if s['name'].startswith(prefix) and
                   '16reply_text_error' in s['name'] and s['size'] == 0x32d]
        assert len(targets) == 2
        for target in targets:
            assert donor['size'] < target['size']
            is_function = '.constprop' not in target['name']
            patch(target['value'], transplant(donor, target['value']),
                  ns + (' FUNCTION' if is_function else ' scripting') + ' PRE raw typed error', is_function)

        # Use unused bytes after the restored helper's return paths for a raw
        # length writer. The ABI is the existing length-aware reply_err ABI.
        target = next(s for s in targets if '.constprop' not in s['name'])
        cave = (target['value'] + donor['size'] + 15) & ~15
        code = bytearray.fromhex('f30f1efa4154415541564989fc4989f54989d6')
        def emit(raw): code.extend(bytes.fromhex(raw))
        def call(name):
            code.append(0xe8)
            code.extend(struct.pack('<i', symbols[prefix + name] - (cave + len(code) + 4)))
        emit('be2d000000');call('2Op4Sink9push_backEc')
        emit('4c89e74c89ee4c89f2');call('2Op4Sink6appendEPKcm')
        emit('4c89e7be0d000000');call('2Op4Sink9push_backEc')
        emit('4c89e7be0a000000');call('2Op4Sink9push_backEc')
        emit('415e415d415cc3')
        assert cave + len(code) <= target['value'] + target['size']
        patch(cave, code, ns + ' raw runtime writer in unused helper tail')
        calls = [(pc, raw) for pc, raw, asm, owner in new_ins
                 if owner and owner.startswith(prefix + '14script_execute') and
                 asm.startswith('call') and 'reply_err' in asm and 'PKcmb' in asm]
        assert len(calls) == 1, calls
        for pc, raw in calls:
            assert raw[0] == 0xe8 and len(raw) == 5
            patch(pc, b'\xe8' + struct.pack('<i', cave - pc - 5), ns + ' PRE raw runtime error call')

        # PRE's C-string wrapper can inline the text loop; restore it too.
        name = prefix + '9reply_errINS_2Op4SinkEEEvOT_PKc'
        old = next(s for s in pre.symbols if s['name'] == name)
        new = next(s for s in post.symbols if s['name'] == name)
        assert old['size'] <= new['size']
        patch(new['value'], transplant(old, new['value']), ns + ' PRE C-string wrapper')
        trimming = [s for s in post.symbols if s['name'].startswith(prefix + '15reply_line_textILb1E')]
        assert len(trimming) == 2
        for symbol in trimming:
            plain = symbols[symbol['name'].replace('ILb1E', 'ILb0E')]
            # Preserve the IBT landing pad; the following direct jump is local.
            start = symbol['value'] + 4
            assert post.body(symbol)[:4] == bytes.fromhex('f30f1efa')
            patch(start, b'\xe9' + struct.pack('<i', plain - start - 5), ns + ' PRE untrimmed mapping')

    for name, selected in [('BROKEN', [p for p in changes if p['control']]), ('PAD-A', changes)]:
        data = bytearray(post.data)
        for p in selected:
            at = p['offset']; value = bytes.fromhex(p['after']);data[at:at+len(value)] = value
        path = OUT / name;path.write_bytes(data);path.chmod(0o755)
        twin = Elf(path)
        assert twin.sections == post.sections and twin.symbols == post.symbols
        restored = bytearray(data)
        for p in selected:
            at = p['offset']; value = bytes.fromhex(p['before']);restored[at:at+len(value)] = value
        assert restored == post.data
        report = dict(kind='A: behaviour twin' if name == 'PAD-A' else 'one FUNCTION helper bypass',
                      pre_sha256=sha(pre.data), post_sha256=sha(post.data), sha256=sha(data),
                      section_and_symbol_tables_identical=True,
                      text_bytes=post.sections[post.names.index('.text')][5], patches=selected)
        (PROOF / (name + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        print(name, report['sha256'], len(selected), 'patches')


if __name__ == '__main__':
    main()
