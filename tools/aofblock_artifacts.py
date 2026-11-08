#!/usr/bin/env python3
"""Offline whole-binary instruction audit and exact-layout AOF behaviour twin."""
import argparse
import bisect
import difflib
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
from lbstall_artifacts import Elf


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Image(Elf):
    def offset(self, address, size):
        matches = [s[4] + address - s[3] for s in self.sections
                   if s[1] == 1 and s[2] & 2 and s[3] <= address
                   and address + size <= s[3] + s[5]]
        assert len(matches) == 1, (hex(address), size, matches)
        return matches[0]

    def read(self, address, size):
        off = self.offset(address, size)
        return self.data[off:off + size]


class Pools(audit.LiteralPools):
    def jump_label(self, index, body, instructions, addr, size):
        result = super().jump_label(index, body, instructions, addr, size)
        if result:
            return result
        # kvobj_external_bytes checks the byte in memory before loading it.
        # Verify the complete dispatch and every destination, not just a moved LEA.
        if index < 4 or index + 3 >= len(body):
            return None
        code = [' '.join(instructions[p][1].split()) for p in body[index-4:index+4]]
        if not (code[0] == 'cmpb $0x5,(%rdi)' and code[1] == 'mov %rdi,%rdx'
                and code[2].startswith('ja ') and code[3] == 'movzbl (%rdi),%eax'
                and re.fullmatch(r'lea -?0x[0-9a-f]+\(%rip\),%rcx # [0-9a-f]+ <[^<>]+>', code[4])
                and code[5:] == ['movslq (%rcx,%rax,4),%rax', 'add %rcx,%rax',
                                 'notrack jmp *%rax']):
            return None
        target = int(audit.REFERENCE.search(code[4])[1], 16)
        for start, data in self.sections:
            off = target - start
            if not 0 <= off <= len(data) - 24:
                continue
            destinations = [target + x[0] for x in struct.iter_unpack('<i', data[off:off+24])]
            assert all(addr <= p < addr + size and p in instructions for p in destinations)
            return 'local-switch-' + ','.join(hex(p - addr) for p in destinations)
        raise AssertionError('bounded switch table missing')


def relabel(binary, elf):
    tables = {}
    functions = sorted((s['value'], s['value'] + s['size'], s['name']) for s in elf.symbols
                       if s['info'] & 15 == 2 and s['size'])
    starts = [f[0] for f in functions]
    for s in elf.symbols:
        if s['name'].startswith('CSWTCH.') and s['size']:
            data = elf.body(s)
            assert len(data) == s['size'] and not elf.sections[s['sec']][2] & 1
            tables[s['value']] = 'switch-data-' + data.hex()
    for group in binary.groups.values():
        for fn in group:
            for i, line in enumerate(fn['ins']):
                at = fn['addr'] + int(line.split()[0], 16)
                raw = binary.instructions[at][1]
                ref = audit.REFERENCE.search(raw)
                if not ref:
                    continue
                target, label = int(ref[1], 16), ref[2]
                if label.startswith('CSWTCH.'):
                    assert target in tables, label
                    fn['ins'][i] = re.sub(r'<CSWTCH\.[^>]+>', '<' + tables[target] + '>', line)
                elif label.startswith('tomo_multidb2_pad_'):
                    n = bisect.bisect_right(starts, target) - 1
                    assert n >= 0 and functions[n][0] <= target < functions[n][1]
                    begin, _, name = functions[n]
                    identity = binary.demangle[name] + '+' + hex(target - begin)
                    fn['ins'][i] = re.sub(r'<tomo_multidb2_pad_[^>]+>', '<' + identity + '>', line)


def metadata(line):
    def literal(match):
        data = bytes.fromhex(match[2])
        data = re.sub(rb'(redis_git_sha1:)[0-9a-f]{8}', rb'\1<commit>', data)
        data = re.sub(rb'((?:re)?dis_git_dirty:)[01]', rb'\1<dirty>', data)
        return match[1] + data.hex()
    return re.sub(r'(literal-(?:load|string)-)([0-9a-f]+)', literal, line)


def compare(before, after, output):
    output.mkdir(parents=True, exist_ok=True)
    audit.LiteralPools = Pools
    old, new = audit.Binary(before, output, True), audit.Binary(after, output, True)
    relabel(old, Image(before))
    relabel(new, Image(after))
    assert set(old.groups) == set(new.groups), 'function/alias set changed'
    changed, equal, info = [], 0, []
    for name in sorted(old.groups):
        aa = sorted(old.groups[name], key=lambda f: f['addr'])
        bb = sorted(new.groups[name], key=lambda f: f['addr'])
        assert len(aa) == len(bb), name
        for n, (a, b) in enumerate(zip(aa, bb)):
            if a['ins'] == b['ins'] and a['encodings'] == b['encodings']:
                equal += 1
                continue
            row = dict(name=name, instance=n, pre_address=hex(a['addr']), post_address=hex(b['addr']),
                       pre_size=a['size'], post_size=b['size'],
                       pre_instructions=len(a['ins']), post_instructions=len(b['ins']))
            is_info = ('::info_stats_build_fields(' in name and a['encodings'] == b['encodings']
                       and list(map(metadata, a['ins'])) == list(map(metadata, b['ins'])))
            (info if is_info else changed).append(row)
            filename = f'{len(changed)+len(info):02}.diff'
            row['diff'] = filename
            (output / filename).write_text(name + '\n' + '\n'.join(difflib.unified_diff(
                [x + ' | ' + y for x, y in zip(a['ins'], a['encodings'])],
                [x + ' | ' + y for x, y in zip(b['ins'], b['encodings'])],
                fromfile='PRE', tofile='POST', lineterm='')) + '\n')
    permitted = ('::blocking_finish_cancelled(', '::AofManager::defer_completion(',
                 '::DatabaseMap::join_workers(')
    unexpected = [r for r in changed if not any(n in r['name'] for n in permitted)]
    result = dict(pre=str(before), post=str(after), pre_sha256=sha(before), post_sha256=sha(after),
                  equal_functions=equal, changed=changed, build_metadata_only=info,
                  unexpected=unexpected, passed=not unexpected)
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}, indent=2))
    assert not unexpected, 'instructions changed outside the S1 completion/shutdown fixes'


def pad(post, target):
    elf = Image(post)
    data = bytearray(elf.data)
    dis = subprocess.check_output(['objdump', '-dw', str(post)], text=True)
    instructions = {}
    for line in dis.splitlines():
        m = audit.INSTRUCTION.match(line)
        if m:
            instructions[int(m[1], 16)] = (bytes.fromhex(m[2]), m[3])
    symbols = list(elf.functions().values())
    names = subprocess.check_output(['c++filt'], input='\n'.join(s['name'] for s in symbols),
                                    text=True).splitlines()
    patches = []

    def patch(at, old, new, name, purpose):
        assert len(old) == len(new) and elf.read(at, len(old)) == old
        off = elf.offset(at, len(old))
        data[off:off+len(old)] = new
        patches.append(dict(function=name, address=hex(at), file_offset=off,
                            pre=old.hex(), pad=new.hex(), purpose=purpose))

    for s, name in zip(symbols, names):
        if '[clone .cold]' in name:
            continue
        if not any(token in name for token in ('::AofManager::defer_completion(',
                   '::blocking_finish_cancelled(', 'tomo::DatabaseMap::join_workers(')):
            continue
        begin, end = s['value'], s['value'] + s['size']
        body = [(at, raw, asm) for at, (raw, asm) in instructions.items() if begin <= at < end]
        if '::AofManager::defer_completion(' in name:
            matches = [(at, raw) for at, raw, asm in body if asm.startswith('lock cmpxchg')]
            assert len(matches) == 1, name
            at, _ = matches[0]
            patch(at-7, bytes.fromhex('31 c0 ba 03 00 00 00'), bytes.fromhex('b8 01 00 00 00 b2 03'),
                  name, 'Free claim restored to PRE Issued claim; DL remains AofWait')
        elif '::blocking_finish_cancelled(' in name:
            matches = [(at, raw) for at, raw, asm in body
                       if asm.startswith('call') and 'defer_completion' in asm]
            assert len(matches) == 1, name
            at, raw = matches[0]
            assert len(raw) == 5 and raw[0] == 0xe8
            patch(at, raw, bytes.fromhex('31 c0 90 90 90'), name,
                  'skip added cancellation deferral and return false')
        elif 'tomo::DatabaseMap::join_workers(' in name and '[clone' not in name:
            matches = []
            for i, (at, raw, asm) in enumerate(body):
                if not asm.startswith('jne '):
                    continue
                ref = audit.REFERENCE.search(asm)
                if ref and instructions[int(ref[1], 16)][1].split() == ['mov', '$0x2710,%eax']:
                    assert body[i-1][2].split() == ['test', '%al,%al']
                    matches.append((at, raw))
            assert len(matches) == 1, name
            at, raw = matches[0]
            assert len(raw) == 6
            patch(at, raw, b'\x90' * 6, name, 'retain PRE worker deadline instead of AOF extension')
    assert len(patches) == 5, patches
    assert len(data) == len(elf.data)
    target.write_bytes(data)
    target.chmod(0o755)
    changed = {p['file_offset'] + i for p in patches for i in range(len(bytes.fromhex(p['pre'])))}
    assert all(i in changed for i, (a, b) in enumerate(zip(elf.data, data)) if a != b)
    control = Image(target)
    assert elf.sections == control.sections and elf.symbols == control.symbols
    result = dict(kind='A: behaviour twin; PRE behaviour, exact POST size/layout',
                  post=str(post), pad=str(target), post_sha256=sha(post), pad_sha256=sha(target),
                  patches=patches, byte_count=len(data))
    target.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    check = sub.add_parser('audit')
    check.add_argument('pre', type=Path)
    check.add_argument('post', type=Path)
    check.add_argument('output', type=Path)
    twin = sub.add_parser('pad')
    twin.add_argument('post', type=Path)
    twin.add_argument('output', type=Path)
    a = p.parse_args()
    if a.command == 'audit':
        compare(a.pre, a.post, a.output)
    else:
        pad(a.post, a.output)


if __name__ == '__main__':
    main()
