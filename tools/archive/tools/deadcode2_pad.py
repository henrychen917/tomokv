#!/usr/bin/env python3
"""Offline type-A diagnostic compatibility twin at POST's exact executable layout.

Transplant PRE's two LB reporting bodies into production-unreachable RO7 false-arm
slots, then redirect their original entries. Restore CT16 aliases with positional
printf conversions. Code stays inside the existing .text; copied literals and
relocated unwind records occupy one added read-only PT_LOAD. Production code has
no new selector. This control must not itself be fed to the old RO7 PAD patcher.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import disassemble, instructions, moved_symbol, tables


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(value, boundary):
    return (value + boundary - 1) & -boundary


def plan(source, pre):
    e = Elf(source)
    data = e.data
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 54)
    assert phsize == 56
    headers = [(phoff + i * phsize, struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize))
               for i in range(phcount)]
    note_at, _ = [h for h in headers if h[1][0] == 4][-1]
    eh_at, old_eh = next(h for h in headers if h[1][0] == 0x6474e550)
    file_at = align(len(data), 4096)
    base = align(max(h[3] + h[6] for _, h in headers if h[0] == 1), 4096)
    blob = bytearray()
    edits = []
    donors = []
    new_frames = []
    moves = []
    funcs = e.functions()
    names = list(funcs)
    labels = dict(zip(names, subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()))
    symbols = {}
    for s in e.symbols:
        if s['sec'] and s['value']:
            symbols.setdefault(s['name'], set()).add(s['value'])
    plt_sections = [arg for section in ('.plt', '.plt.got', '.plt.sec') if section in e.names for arg in ('-j', section)]
    plt = subprocess.check_output(['objdump', '-d', *plt_sections, str(source)], text=True)
    for addr, name in re.findall(r'^([0-9a-f]+) <([^>]+)@plt>:', plt, re.M):
        symbols.setdefault(name, set()).add(int(addr, 16))

    def address(name):
        found = symbols.get(name, set())
        assert len(found) == 1, ('missing/ambiguous target', name, found)
        return next(iter(found))

    def append(raw, alignment=8):
        blob.extend(bytes(align(len(blob), alignment) - len(blob)))
        result = base + len(blob)
        blob.extend(raw)
        return result

    def edit(at, raw, reason):
        assert len(raw) and at + len(raw) <= len(data)
        assert not any(at < x['offset'] + len(bytes.fromhex(x['new'])) and
                       x['offset'] < at + len(raw) for x in edits), 'overlapping patches'
        edits.append(dict(offset=at, old=data[at:at+len(raw)].hex(), new=raw.hex(), reason=reason))

    def code_offset(addr):
        sec = e.sections[e.names.index('.text')]
        assert sec[3] <= addr < sec[3] + sec[5]
        return sec[4] + addr - sec[3]

    namespaces = ['tomo'] + (['tomo_db0'] if any('tomo_db0::lbsignals_format(' in n for n in labels.values()) else [])
    for ns in namespaces:
        selector = next(f for name, f in funcs.items() if labels[name] == ns+'::r7::shadow_available()')
        selector_bytes = e.body(selector)
        if selector_bytes.startswith(b'\xf3\x0f\x1e\xfa'):
            selector_bytes = selector_bytes[4:]
        assert selector_bytes == b'\xb8\x01\x00\x00\x00\xc3', 'RO7 selector must return true'
        obj = Elf(pre / ('db0/src/cmd/lbsignals.o' if ns == 'tomo_db0' else 'src/cmd/lbsignals.o'))
        old_funcs = obj.functions()
        selected = [f for f in old_funcs.values() if 'lbsignals_format' in f['name'] or 'lbsignals_info_section' in f['name']]
        assert len(selected) == 3, 'two reporting entries and one cleanup clone'
        info = next(f for f in selected if 'lbsignals_info_section' in f['name'] and '.cold' not in f['name'])
        cold = next(f for f in selected if '.cold' in f['name'])
        fmt = next(f for f in selected if 'lbsignals_format' in f['name'])
        def donor(predicate):
            found = [funcs[n] for n, label in labels.items() if predicate(label)]
            assert len(found) == 1, ('RO7 donor inventory', ns, [f['name'] for f in found])
            return found[0]
        slot_info = donor(lambda n: n.startswith('void '+ns+'::r7::ExReorderQueues<32ul>::submit<') and
                          'r7_drain_tasks_impl<false, 32u, false>' in n)
        slot_fmt = donor(lambda n: n.startswith('unsigned int '+ns+'::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>'))
        assert info['size'] + 15 + cold['size'] <= slot_info['size'] and fmt['size'] <= slot_fmt['size']
        mapped = {info['name']: slot_info['value'],
                  cold['name']: align(slot_info['value'] + info['size'], 16),
                  fmt['name']: slot_fmt['value']}
        for slot in (slot_info, slot_fmt):
            donors.append(dict(symbol=slot['name'], start=slot['value'], size=slot['size'],
                               reason='Shadow=false; production shadow_available() is true'))
        copied = {}
        for i, name in enumerate(obj.names):
            if name.startswith('.rodata') or name in ('.gcc_except_table', '.eh_frame'):
                copied[i] = append(obj.section_data(i), max(1, obj.sections[i][8]))

        def resolve(symbol, addend, bias=0, unused_frame=False):
            sec = symbol['sec']
            if sec == 0:
                return address(symbol['name']) + addend
            if sec < len(obj.sections) and obj.sections[sec][2] & 4:
                offset = symbol['value'] + addend + bias
                found = [f for f in old_funcs.values() if f['sec'] == sec and f['value'] <= offset < f['value'] + f['size']]
                assert found, ('unresolved code target', symbol, addend, bias)
                f = found[0]
                if unused_frame and f['name'] not in mapped:
                    return 0
                target = mapped[f['name']] if f['name'] in mapped else address(f['name'])
                return target + offset - f['value'] - bias
            if sec in copied:
                return copied[sec] + symbol['value'] + addend
            return address(symbol['name']) + addend

        for f in selected:
            raw = bytearray(obj.body(f))
            dest = mapped[f['name']]
            obj.canonical(f)  # Decode same-section, non-relocated calls at instruction boundaries.
            relocated = set()
            for offset, kind, symbol, addend in obj.relocs.get(f['sec'], []):
                at = offset - f['value']
                if not 0 <= at < len(raw):
                    continue
                assert kind in (2, 4), ('unexpected code relocation', kind)
                value = resolve(symbol, addend, bias=4) - (dest + at)
                struct.pack_into('<i', raw, at, value)
                relocated.add(offset)
            for at, target in obj.direct.get(f['sec'], []):
                if not f['value'] <= at < f['value'] + f['size'] or \
                        f['value'] <= target < f['value'] + f['size'] or at + 1 in relocated:
                    continue
                fake = dict(sec=f['sec'], info=3, value=0, name='')
                destination = resolve(fake, target)
                struct.pack_into('<i', raw, at - f['value'] + 1, destination - (dest + at - f['value'] + 5))
            edit(code_offset(dest), raw, 'transplanted PRE '+f['name'])
            moves.append(dict(symbol=f['name'], source=str(obj.path), source_size=f['size'],
                              pre_body_sha256=sha(obj.body(f)), destination=dest))
            if '.cold' not in f['name']:
                entry = funcs[f['name']]
                prefix = 4 if e.body(entry).startswith(b'\xf3\x0f\x1e\xfa') else 0
                ip = entry['value'] + prefix
                edit(code_offset(ip), b'\xe9' + struct.pack('<i', dest - ip - 5), 'reporting entry '+f['name'])

        # Preserve exception propagation: original PRE CIE/FDE/LSDA bytes, with
        # relocated PC-relative fields. Only transplanted FDEs enter the runtime index.
        frame_sec = obj.names.index('.eh_frame')
        frame_addr = copied[frame_sec]
        for offset, kind, symbol, addend in obj.relocs.get(frame_sec, []):
            assert kind == 2
            value = resolve(symbol, addend, unused_frame=True)
            struct.pack_into('<i', blob, frame_addr - base + offset, value - (frame_addr + offset))
        frames = obj.section_data(frame_sec)
        frame_relocs = {r[0]:r for r in obj.relocs.get(frame_sec, [])}
        pos = 0
        while pos < len(frames):
            length, cie = struct.unpack_from('<II', frames, pos)
            if not length: break
            if cie and pos + 8 in frame_relocs:
                _, _, symbol, addend = frame_relocs[pos+8]
                offset = symbol['value'] + addend
                f = next((f for f in selected if f['sec'] == symbol['sec'] and f['value'] == offset), None)
                if f:
                    new_frames.append((mapped[f['name']], frame_addr + pos))
            pos += 4 + length
        assert sum(1 for start, _ in new_frames if start in mapped.values()) == 3

    # Restore duplicate aliases without restoring duplicate argument pushes.
    # POSIX positional conversions reuse the canonical trigger arguments.
    ro = e.sections[e.names.index('.rodata')]
    strings = e.section_data(e.names.index('.rodata'))
    marker = b'flipctl_rate_collapse_triggers:%llu\r\n'
    assert strings.count(marker) == 1
    hit = strings.index(marker)
    begin, end = strings.rfind(b'\0', 0, hit)+1, strings.index(b'\0', hit)+1
    original = strings[begin:end]
    arg = 0
    fields = {}
    pattern = re.compile(rb'%(?:[-+ #0]*)(?:\d+)?(?:\.\d+)?(?:hh|ll|[hljztL])?[diuoxXfFeEgGaAcsp]')
    def positional(m):
        nonlocal arg
        arg += 1
        field = original[:m.start()].split(b'\r\n')[-1].split(b':')[0]
        fields[field] = arg
        return b'%' + str(arg).encode() + b'$' + m[0][1:]
    restored = pattern.sub(positional, original)
    surge, collapse = fields[b'flipctl_rate_surge_triggers'], fields[b'flipctl_rate_collapse_triggers']
    marker = b'flipctl_rate_collapse_triggers:%'+str(collapse).encode()+b'$llu\r\n'
    restored = restored.replace(marker, marker + b'flipctl_surge_triggers:%'+str(surge).encode()+
                                b'$llu\r\nflipctl_collapse_triggers:%'+str(collapse).encode()+b'$llu\r\n')
    target = append(restored, 1)
    references = []
    for fn in funcs.values():
        if '8cmd_infoE' not in fn['name']:
            continue
        for ip, raw, asm, _ in instructions(disassemble(source, fn['name'])):
            rip = re.fullmatch(r'lea\s+[^,]*\(%rip\),%r[a-z0-9]+\s+#\s+([0-9a-f]+) <.*>', asm)
            immediate = re.fullmatch(r'mov\s+\$0x([0-9a-f]+),%e[a-z0-9]+', asm)
            if rip and int(rip[1],16) == ro[3]+begin:
                assert len(raw) == 7
                replacement = raw[:3]+struct.pack('<i',target-ip-len(raw))
            elif immediate and int(immediate[1],16) == ro[3]+begin:
                assert len(raw) == 5 and target < 2**31
                replacement = raw[:1]+struct.pack('<I',target)
            else:
                continue
            edit(code_offset(ip),replacement,'PRE flip INFO aliases '+fn['name'])
            references.append(fn['name'])
    assert len(references) == len(namespaces)

    old_hdr = data[old_eh[2]:old_eh[2]+old_eh[5]]
    assert old_hdr[:4] == b'\x01\x1b\x03\x3b', 'supported GNU unwind index encoding'
    count = struct.unpack_from('<I',old_hdr,8)[0]
    assert len(old_hdr) == 12 + 8 * count
    rows = [(old_eh[3]+x,old_eh[3]+y) for x,y in struct.iter_unpack('<ii',old_hdr[12:])]
    rows = [r for r in rows if not any(d['start'] <= r[0] < d['start']+d['size'] for d in donors)]
    rows = sorted(rows+new_frames)
    assert len({r[0] for r in rows}) == len(rows), 'duplicate unwind start'
    hdr = append(bytes(12+8*len(rows)),4)
    original_frame = old_eh[3]+4+struct.unpack_from('<i',old_hdr,4)[0]
    off = hdr-base
    blob[off:off+4] = old_hdr[:4]
    struct.pack_into('<iI',blob,off+4,original_frame-(hdr+4),len(rows))
    for i,(start,frame) in enumerate(rows):
        struct.pack_into('<ii',blob,off+12+8*i,start-hdr,frame-hdr)
    hsize = 12+8*len(rows)
    edit(eh_at,struct.pack('<IIQQQQQQ',0x6474e550,4,file_at+off,hdr,hdr,hsize,hsize,4),'merged unwind index')
    edit(note_at,struct.pack('<IIQQQQQQ',1,4,file_at,base,base,len(blob),len(blob),4096),'read-only literals and unwind records')
    return dict(kind='A: PRE observable behavior, POST text size and function/object layout',
                input_sha256=sha(data), input_size=len(data), patches=edits, donors=donors,
                transplants=moves, unwind_functions=len(new_frames), namespaces=namespaces,
                appended_offset=file_at, appended_address=base, appended_hex=blob.hex(),
                caveat='Null-only control. RO7 false-arm code slots are repurposed; do not apply r7shadow_pad.py to this PAD-A.')


def verify(source, output, expected):
    a,b = Elf(source),Elf(output)
    assert a.sections == b.sections and a.symbols == b.symbols, 'function or section layout changed'
    restored=bytearray(b.data)
    at=expected['appended_offset']
    assert restored[at:] == bytes.fromhex(expected['appended_hex']), 'compatibility data changed'
    assert restored[len(a.data):at] == bytes(at-len(a.data)), 'unplanned tail'
    del restored[len(a.data):]
    for patch in expected['patches']:
        at=patch['offset'];new=bytes.fromhex(patch['new']);old=bytes.fromhex(patch['old'])
        assert restored[at:at+len(new)] == new, 'planned patch missing'
        restored[at:at+len(new)] = old
    assert restored == a.data, 'unplanned byte change'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('receipt',type=Path);p.add_argument('--pre',type=Path,default=Path('build/deadcode2/PRE'))
    a=p.parse_args();a.receipt.mkdir(parents=True,exist_ok=True)
    expected=plan(a.source,a.pre)
    data=bytearray(a.source.read_bytes());data.extend(bytes(expected['appended_offset']-len(data)))
    data.extend(bytes.fromhex(expected['appended_hex']))
    for patch in expected['patches']:
        at=patch['offset'];raw=bytes.fromhex(patch['new']);data[at:at+len(raw)]=raw
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(data);a.output.chmod(a.source.stat().st_mode)
    verify(a.source,a.output,expected)
    (a.receipt/'plan.json').write_text(json.dumps(expected,indent=2)+'\n')
    before=tables(Elf(a.source),a.receipt,'POST');after=tables(Elf(a.output),a.receipt,'PAD-A')
    assert before['function_table_sha256']==after['function_table_sha256']
    assert before['section_table_sha256']==after['section_table_sha256']
    controls = {}
    missing = bytearray(data)
    first = expected['patches'][0]
    at = first['offset']
    missing[at:at+len(bytes.fromhex(first['old']))] = bytes.fromhex(first['old'])
    one = bytearray(data)
    elf = Elf(a.source)
    one[elf.sections[elf.names.index('.text')][4]] ^= 1
    for name, broken, message in (
            ('missing-transplant', missing, 'planned patch missing'),
            ('moved-symbol', moved_symbol(data, elf, expected['donors'][0]['symbol']), 'function or section layout changed'),
            ('one-byte', one, 'unplanned byte change')):
        control = a.output.with_name(a.output.name+'-'+name)
        control.write_bytes(broken)
        try:
            verify(a.source, control, expected)
        except AssertionError as error:
            assert str(error) == message, (name, str(error))
            controls[name] = dict(rejected=True, assertion=str(error), sha256=sha(broken))
        else:
            raise AssertionError('accepted negative control '+name)
        finally:
            control.unlink()
    result=dict(kind=expected['kind'],post=before,pad=after,patches=len(expected['patches']),controls=controls,
                exact_function_and_section_tables=True,all_other_original_bytes_identical=True,
                unwind_functions=expected['unwind_functions'],caveat=expected['caveat'])
    (a.receipt/'proof.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS PAD-A: PRE reporting bodies and aliases; executable layout unchanged; 3 mutations rejected')


if __name__=='__main__':main()
