#!/usr/bin/env python3
"""Offline PAD-A and byte receipts for splitlocal. Never executes an ELF.

Retarget POST's split-local overlap-0 parser calls to the retained PRE-policy
parser, and restore PRE's parked epoll callback policy. All addresses, section
sizes, symbol tables, and bytes outside those call displacements stay fixed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf
from ttlstate_proof import compare_files, save


def instructions(path):
    text = subprocess.check_output(['objdump', '-dw', str(path)], text=True)
    rows = []
    owner = None
    for line in text.splitlines():
        head = re.fullmatch(r'[0-9a-f]+ <([^>]+)>:', line)
        if head: owner = head[1]
        match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if match: rows.append((int(match[1], 16), bytes.fromhex(match[2]), match[3], owner))
    return rows


def verify(source, output, patches):
    before, after = Elf(source), Elf(output)
    assert before.sections == after.sections and before.symbols == after.symbols, 'PAD layout changed'
    restored = bytearray(after.data)
    for p in patches:
        at = p['offset']
        assert after.data[at:at+5].hex() == p['after'], 'PAD planned retarget missing'
        destination = p['address'] + 5 + struct.unpack_from('<i', after.data, at+1)[0]
        assert destination == after.functions()[p['new']]['value'], 'PAD target mismatch'
        restored[at:at+5] = bytes.fromhex(p['before'])
    assert bytes(restored) == before.data, 'PAD bytes changed outside call displacements'


def pad(source, output):
    elf = Elf(source)
    functions = elf.functions()
    code = instructions(source)
    patched = bytearray(elf.data)
    patches = []
    parser_counts, park_counts = Counter(), Counter()
    parser_pattern = re.compile(r'_ZN(4tomo|8tomo_db0)6IoLoop18parse_and_dispatchILb([01])ELj32ELb0ELb1EEENS0_14DispatchResultEPNS_6ClientE')
    parsers = {n: n.replace('ELj32ELb0ELb1E', 'ELj32ELb0ELb0E')
               for n in functions if parser_pattern.fullmatch(n)}
    assert len(parsers) == 4, 'PAD new parser inventory'
    policy = []
    for new, old in sorted(parsers.items()):
        calls = {}
        for symbol in (old, new):
            calls[symbol] = [text for _, _, text, owner in code
                             if owner == symbol and 'l4prebuild_' in text]
        assert not calls[new], ('split-local parser still references prebuild', new)
        assert any('l4prebuild_prepare_set' in c for c in calls[old]), ('missing PRE-policy prepare', old)
        assert any('l4prebuild_discard_set' in c for c in calls[old]), ('missing PRE-policy discard', old)
        policy.append(dict(candidate=new, reference_policy=old, calls=calls,
                           candidate_bytes=functions[new]['size'], reference_bytes=functions[old]['size']))
    loop_pattern = re.compile(r'_ZN(4tomo|8tomo_db0)6IoLoop8run_loopILb([01])ELb([01])ELb1ELb1ELh([01])ELb1EEEvv')
    loops = {n for n in functions if loop_pattern.fullmatch(n)}
    assert len(loops) == 16, 'PAD split-local epoll loop inventory'
    # GCC may outline epoll_accept and discard its unused return value. Keep
    # that clone's ABI; restore the policy at its unchanged admit_fd edge.
    accept_pattern = re.compile(r'_ZN(4tomo|8tomo_db0)6IoLoop12epoll_acceptILb1ELb1ELh1EEEjNS_6UrKindE(?:\.isra\.\d+)?')
    accepts = {n for n in functions if accept_pattern.fullmatch(n)}
    accept_callers = Counter()
    accept_patches = Counter()
    for index, (address, raw, instruction, owner) in enumerate(code):
        call = re.fullmatch(r'(call|jmp)\s+([0-9a-f]+) <([^>]+)>', instruction)
        if not call: continue
        old = call[3]
        new, category = None, None
        if old in accepts:
            assert owner in loops and loop_pattern.fullmatch(owner)[4] == '1', ('PAD shared accept clone', owner)
            park_counts[owner] += 1
            accept_callers[old] += 1
            continue
        if old in parsers:
            assert '11flush_ready' in owner and 'ELb1EEEjv' in owner, ('PAD parser caller', owner)
            new, category = parsers[old], 'parser'
            parser_counts[owner] += 1
        elif owner in accepts:
            ns = accept_pattern.fullmatch(owner)[1]
            assert old == f'_ZN{ns}6IoLoop8admit_fdILb1ELb1ELh1EEEviNS_6UrKindE' or 'admit_fd' not in old
            if 'admit_fd' in old:
                new, category = old.replace('ILb1ELb1ELh1', 'ILb1ELb0ELh1'), 'park-accept'
                accept_patches[owner] += 1
        elif owner in loops:
            ns, unix, tls, pipeline = loop_pattern.fullmatch(owner).groups()
            if pipeline == '0':
                expected = f'_ZN{ns}6IoLoop10epoll_passILb{unix}ELb{tls}ELb1ELh0EEEji'
                if old == expected and any(re.fullmatch(r'mov\s+\$0x32,%esi', r[2])
                                           for r in code[max(0,index-4):index]):
                    new = old.replace('ELb1ELh0EEEji', 'ELb0ELh0EEEji')
            else:
                expected = f'_ZN{ns}6IoLoop8admit_fdILb1ELb1ELh1EEEviNS_6UrKindE'
                if old == expected:
                    new = old.replace('ILb1ELb1ELh1', 'ILb1ELb0ELh1')
            if new:
                category = 'park'
                park_counts[owner] += 1
        if new is None: continue
        assert len(raw) == 5 and raw[0] in (0xe8, 0xe9), ('PAD rel32 edge', instruction)
        assert new in functions and int(call[2], 16) == functions[old]['value']
        symbol = functions[owner]
        section = elf.sections[symbol['sec']]
        offset = section[4] + address - section[3]
        assert elf.data[offset:offset+5] == raw
        replacement = raw[:1] + struct.pack('<i', functions[new]['value'] - address - 5)
        patched[offset:offset+5] = replacement
        patches.append(dict(category=category, caller=owner, address=address, offset=offset,
                            old=old, new=new, before=raw.hex(), after=replacement.hex()))
    for loop in loops:
        _, unix, tls, pipeline = loop_pattern.fullmatch(loop).groups()
        expected = 1 if pipeline == '0' else 1 + int(unix) + int(tls)
        assert park_counts[loop] == expected, ('PAD park call inventory', loop, park_counts[loop], expected)
    assert len(parser_counts) == 32, ('PAD split-local flush inventory', len(parser_counts))
    assert set(accept_callers) == accepts and all(accept_patches[a] == 1 for a in accepts), 'PAD accept clone closure'
    assert set(p['old'] for p in patches if p['category'] == 'parser') == parsers.keys()
    output.parent.mkdir(parents=True, exist_ok=True)
    save(output.parent / 'parser-policy.json', policy)
    output.write_bytes(patched)
    output.chmod(0o755)
    verify(source, output, patches)
    receipt = dict(kind='A: behaviour twin', behavior='PRE parser and admission policy with POST text size/layout',
                   source=str(source), output=str(output), sha256=hashlib.sha256(patched).hexdigest(),
                   text_bytes=elf.sections[elf.names.index('.text')][5],
                   exact_layout=True, all_other_bytes_equal=True, patches=patches,
                   parser_callers=dict(parser_counts), park_callers=dict(park_counts),
                   outlined_accept_callers=dict(accept_callers))
    save(output.parent / 'patches.json', receipt)
    # Deliberately omit a retarget in a nonexecutable copy; the verifier must fail.
    first = patches[0]
    patched[first['offset']:first['offset']+5] = bytes.fromhex(first['before'])
    broken = output.parent / 'missing-retarget.NEVER-RUN'
    broken.write_bytes(patched); broken.chmod(0o600)
    try: verify(source, broken, patches)
    except AssertionError as error:
        assert str(error) == 'PAD planned retarget missing', str(error)
        save(output.parent / 'negative.json', dict(rejected=True, assertion=str(error)))
    else: raise AssertionError('PAD negative control accepted')
    print('PASS PAD-A:', len(patches), 'retargets;', len(parser_counts), 'flush bodies;', len(park_counts), 'park bodies')


def compare(pre, post, output):
    rows = {}
    for relative in sorted(p.relative_to(pre) for p in pre.glob('**/*.o') if 'source' not in p.parts):
        rows[str(relative)] = compare_files(pre / relative, post / relative)
    rows['tomokv'] = compare_files(pre / 'tomokv', post / 'tomokv')
    assert len(rows) == 85, ('production artifact inventory', len(rows))
    save(output, rows)
    print('PRE/POST strict identity:', sum(r['okay'] for r in rows.values()), '/', len(rows))
    for path, row in rows.items():
        if not row['okay']: print('CHANGED', path)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('pad'); a.add_argument('source', type=Path); a.add_argument('output', type=Path)
    a = sub.add_parser('compare'); a.add_argument('pre', type=Path); a.add_argument('post', type=Path); a.add_argument('output', type=Path)
    args = p.parse_args()
    if args.action == 'pad': pad(args.source, args.output)
    else: compare(args.pre, args.post, args.output)
