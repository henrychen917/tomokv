#!/usr/bin/env python3
"""Offline deadfused ELF receipts and the cold INFO compatibility twin.

No server or load generator is run. PAD-A retains POST's complete function and
section tables. Only cmd_info's format-string references change. An appended
read-only PT_LOAD restores the PRE zero-valued INFO row, without a production
patch point, a counter, or a reader retry. The data path is already behaviorally
equivalent; this is a null-test control, not a way to attribute a speedup.
"""
import argparse
import json
from pathlib import Path
import re
import struct

from lbstall_artifacts import Elf
from rlfence_artifacts import disassemble, instructions, moved_symbol, save, sha, tables

ROW = b'read_local_mget_generation_retries:0\r\n'
MARKER = b'read_local_mget_fallback_generation:%llu\r\n'


def plan(path):
    elf = Elf(path)
    data = elf.data
    ro = elf.sections[elf.names.index('.rodata')]
    body = elf.section_data(elf.names.index('.rodata'))
    assert body.count(MARKER) == 1, 'INFO format inventory'
    at = body.index(MARKER)
    begin = body.rfind(b'\0', 0, at) + 1
    end = body.index(b'\0', at) + 1
    old = body[begin:end]
    assert ROW not in old, 'already contains PRE INFO format'
    assert b'read_local_mget_local_hits:%llu\r\n' in old
    new = old.replace(MARKER, ROW + MARKER)
    address = ro[3] + begin
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 54)
    assert phsize == 56
    headers = [(phoff + i * phsize, struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize))
               for i in range(phcount)]
    notes = [(at, h) for at, h in headers if h[0] == 4]
    assert notes, 'no PT_NOTE slot for non-executable compatibility string'
    note_at, note = notes[-1]
    page = 4096
    align = lambda n: (n + page - 1) & -page
    offset = align(len(data))
    target = align(max(h[3] + h[6] for _, h in headers if h[0] == 1))
    load = struct.pack('<IIQQQQQQ', 1, 4, offset, target, target, len(new), len(new), page)
    edits = [dict(kind='read-only PT_LOAD', offset=note_at,
                  old=data[note_at:note_at + phsize].hex(), new=load.hex())]
    callers = []
    for fn in elf.functions().values():
        if '8cmd_infoE' not in fn['name']:
            continue
        for ip, raw, asm, _ in instructions(disassemble(path, fn['name'])):
            m = re.fullmatch(r'lea\s+[^,]*\(%rip\),%r[a-z0-9]+\s+#\s+([0-9a-f]+) <.*>', asm)
            immediate = re.fullmatch(r'mov\s+\$0x([0-9a-f]+),%e[a-z0-9]+', asm)
            if m and int(m[1], 16) == address:
                assert len(raw) == 7 and raw[1] == 0x8d, 'unrecognized INFO address load'
                replacement = raw[:3] + struct.pack('<i', target - (ip + len(raw)))
            elif immediate and int(immediate[1], 16) == address:
                assert len(raw) == 5 and 0xb8 <= raw[0] <= 0xbf and target < 2**31
                replacement = raw[:1] + struct.pack('<I', target)
            else:
                continue
            sec = elf.sections[fn['sec']]
            file_at = sec[4] + ip - sec[3]
            edits.append(dict(kind='INFO format reference', offset=file_at, address=ip,
                              symbol=fn['name'], old=raw.hex(), new=replacement.hex()))
            callers.append(fn['name'])
    # Unit images have one namespace; production has both, each exactly once.
    assert len(callers) in (1, 2) and len(set(callers)) == len(callers), ('INFO callers', callers)
    return dict(kind='A: PRE observable behavior at POST function/object layout',
                input_sha256=sha(data), input_size=len(data), patches=edits,
                appended_offset=offset, appended_address=target,
                appended_hex=new.hex(), old_format_sha256=sha(old), callers=callers)


def verify(source, output, expected):
    assert expected == plan(source), 'plan differs from independent inventory'
    before, after = Elf(source), Elf(output)
    assert before.sections == after.sections, 'section table moved'
    assert before.symbols == after.symbols, 'symbol table moved'
    restored = bytearray(after.data)
    tail = bytes.fromhex(expected['appended_hex'])
    at = expected['appended_offset']
    assert restored[at:] == tail, 'restored INFO format missing'
    assert restored[len(before.data):at] == bytes(at - len(before.data)), 'unplanned tail'
    del restored[len(before.data):]
    for change in expected['patches']:
        at = change['offset']
        old, new = bytes.fromhex(change['old']), bytes.fromhex(change['new'])
        assert restored[at:at + len(new)] == new, 'planned retarget missing'
        restored[at:at + len(new)] = old
    assert bytes(restored) == before.data, 'unplanned byte change'


def pad(source, output, out):
    expected = plan(source)
    save(out / 'planned-retargets.json', expected)
    before = Elf(source)
    data = bytearray(before.data)
    data += bytes(expected['appended_offset'] - len(data))
    data += bytes.fromhex(expected['appended_hex'])
    for change in expected['patches']:
        at = change['offset']
        data[at:at + len(bytes.fromhex(change['new']))] = bytes.fromhex(change['new'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    output.chmod(source.stat().st_mode)
    verify(source, output, expected)
    a, b = tables(before, out, 'POST'), tables(Elf(output), out, 'PAD-A')
    assert a['function_table_sha256'] == b['function_table_sha256']
    assert a['section_table_sha256'] == b['section_table_sha256']
    bad = bytearray(data)
    first = expected['patches'][1]
    at = first['offset']
    bad[at:at + len(bytes.fromhex(first['old']))] = bytes.fromhex(first['old'])
    one = bytearray(data)
    one[before.sections[before.names.index('.text')][4]] ^= 1
    controls = {}
    for name, broken, message in (
            ('missing-retarget', bad, 'planned retarget missing'),
            ('moved-symbol', moved_symbol(data, before, first['symbol']), 'symbol table moved'),
            ('one-byte', one, 'unplanned byte change')):
        control = output.with_name(output.name + '-' + name)
        control.write_bytes(broken)
        try:
            verify(source, control, expected)
        except AssertionError as error:
            assert str(error) == message, (name, str(error))
            controls[name] = dict(rejected=True, assertion=str(error), sha256=sha(broken))
        else:
            raise AssertionError('accepted negative control ' + name)
        control.unlink()
    save(out / 'negative-controls.json', controls)
    save(out / 'proof.json', dict(kind=expected['kind'], post=a, pad=b,
        exact_function_and_section_tables=True, all_other_original_bytes_identical=True,
        patches=len(expected['patches']), restored_row=ROW.decode().strip(), controls=controls,
        caveat='No independent data-path treatment: dead behavior is absent in both arms. '
               'This twin verifies PRE INFO compatibility at POST addresses; only a null '
               'performance verdict is admissible. No speedup attribution from POST/PAD.'))
    print('PASS PAD-A: exact function/section tables; PRE INFO row restored; 3 controls rejected')


def compare(pre, post, out):
    left, right = Elf(pre), Elf(post)
    a, b = tables(left, out, 'PRE'), tables(right, out, 'POST')
    rows = []
    for name in sorted({n for e in (left, right) for n, s in zip(e.names, e.sections) if s[2] & 4}):
        def record(e):
            if name not in e.names:
                return None
            i = e.names.index(name); s = e.sections[i]
            return dict(address=s[3], size=s[5], sha256=sha(e.section_data(i)))
        old, new = record(left), record(right)
        rows.append(dict(section=name, pre=old, post=new, equal=old == new))
    removed = ('gather_tasks_unretired', 'retire_task_lanes', 'exec_batch_prefetched_buffered',
               'finish_buffered_exec_pass', 'prepare_pipeline', 'fused_coarse_pass',
               'fused_three_way_pass', 'fused_pipeline_control', 'drain_tasks_with_filler',
               'set_window')
    names = '\n'.join(s['name'] for s in left.symbols if s['info'] & 15 == 2)
    absent = {name: name not in names for name in removed}
    assert all(absent.values()), absent
    save(out / 'identity.json', dict(pre=a, post=b, executable_sections=rows,
        exact_executable_identity=all(r['equal'] for r in rows),
        deleted_functions_absent_in_pre=absent,
        caveat='Absent functions do not prove surrounding code unchanged: full section hashes above decide.'))
    print('Executable identity:', all(r['equal'] for r in rows), '; unreachable symbol inventory PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('pad')
    p.add_argument('source', type=Path); p.add_argument('output', type=Path); p.add_argument('receipt', type=Path)
    p = sub.add_parser('compare')
    p.add_argument('pre', type=Path); p.add_argument('post', type=Path); p.add_argument('receipt', type=Path)
    args = parser.parse_args()
    if args.action == 'pad': pad(args.source, args.output, args.receipt)
    else: compare(args.pre, args.post, args.receipt)
