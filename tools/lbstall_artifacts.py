#!/usr/bin/env python3
"""Offline ELF byte comparison and an exact-layout LB negative control. Never runs a server."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


class Elf:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        assert self.data[:6] == b'\x7fELF\x02\x01', 'expected little-endian ELF64'
        self.kind = struct.unpack_from('<H', self.data, 16)[0]
        off = struct.unpack_from('<Q', self.data, 40)[0]
        size, count, names = struct.unpack_from('<HHH', self.data, 58)
        self.sections = [struct.unpack_from('<IIQQQQIIQQ', self.data, off + i * size)
                         for i in range(count)]
        strings = self.section_data(names)
        self.names = [self.string(strings, s[0]) for s in self.sections]
        self.symbols = []
        self.tables = {}
        self.relocs = {}
        self.direct = None
        for i, s in enumerate(self.sections):
            if s[1] != 2:  # SHT_SYMTAB
                continue
            strings = self.section_data(s[6])
            table = []
            for at in range(s[4], s[4] + s[5], s[9]):
                name, info, other, sec, value, length = struct.unpack_from('<IBBHQQ', self.data, at)
                symbol = dict(name=self.string(strings, name), info=info, sec=sec,
                              value=value, size=length)
                table.append(symbol)
                self.symbols.append(symbol)
            self.tables[i] = table
        for s in self.sections:
            if s[1] != 4:  # SHT_RELA
                continue
            rels = self.relocs.setdefault(s[7], [])
            for at in range(s[4], s[4] + s[5], s[9]):
                offset, info, addend = struct.unpack_from('<QQq', self.data, at)
                rels.append((offset, info & 0xffffffff, self.tables[s[6]][info >> 32], addend))

    @staticmethod
    def string(data, off):
        return data[off:].split(b'\0', 1)[0].decode(errors='replace')

    def section_data(self, index):
        s = self.sections[index]
        return self.data[s[4]:s[4] + s[5]]

    def body(self, symbol):
        s = self.sections[symbol['sec']]
        offset = symbol['value'] - (s[3] if self.kind != 1 else 0)
        return self.section_data(symbol['sec'])[offset:offset + symbol['size']]

    def target(self, symbol, addend, kind):
        # Relocation displacement fields are addresses, not executable opcodes. Resolve their
        # identities as well as clearing the bytes: changing a callee must still fail the check.
        if symbol['sec'] == 0 or symbol['sec'] >= len(self.sections):
            return (symbol['name'], addend)
        sec = self.sections[symbol['sec']]
        adjustment = 4 if kind in (2, 4, 9, 41, 42) else 0
        offset = symbol['value'] + addend + adjustment
        if symbol['info'] & 15 == 3 and sec[2] & 4:  # section-relative code target
            for fn in self.symbols:
                if fn['info'] & 15 == 2 and fn['sec'] == symbol['sec'] and \
                        fn['value'] <= offset < fn['value'] + fn['size']:
                    return (fn['name'], offset - fn['value'])
        if sec[2] & 0x20:  # SHF_STRINGS: LC ordinals/offsets can move without changing data
            return ('string', self.string(self.section_data(symbol['sec']), offset))
        if symbol['name'].startswith('.LC'):
            return ('constant', self.section_data(symbol['sec'])[offset:offset + 8].hex())
        return (symbol['name'] or self.names[symbol['sec']], addend)

    def canonical(self, symbol):
        body = bytearray(self.body(symbol))
        targets = []
        for offset, kind, target, addend in self.relocs.get(symbol['sec'], []):
            at = offset - symbol['value']
            if not 0 <= at < len(body):
                continue
            width = {1: 8, 2: 4, 4: 4, 9: 4, 10: 4, 11: 4, 24: 8,
                     41: 4, 42: 4}.get(kind)
            assert width, f'unhandled relocation {kind}'
            body[at:at + width] = bytes(width)
            targets.append((at, kind, self.target(target, addend, kind)))
        # GAS resolves same-section relative calls itself. These have no ELF relocation record,
        # but are still address displacements. Decode only instruction boundaries from objdump;
        # never mask arbitrary opcode-looking bytes in immediates or data.
        if self.direct is None:
            self.direct = {}
            section = None
            disassembly = subprocess.check_output(['objdump', '-dw', str(self.path)]).decode()
            by_name = {n: i for i, n in enumerate(self.names)}
            for line in disassembly.splitlines():
                if line.startswith('Disassembly of section '):
                    section = by_name[line[len('Disassembly of section '):-1]]
                    continue
                m = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(?:call|jmp)\s+([0-9a-f]+)\s+<', line)
                if not m:
                    continue
                raw = bytes.fromhex(m[2])
                if len(raw) != 5 or raw[0] not in (0xe8, 0xe9):
                    continue
                at, destination = int(m[1], 16), int(m[3], 16)
                if any(r[0] == at + 1 for r in self.relocs.get(section, [])):
                    continue
                self.direct.setdefault(section, []).append((at, destination))
        for at, destination in self.direct.get(symbol['sec'], []):
            offset = at - symbol['value']
            if not 0 <= offset < len(body) or \
                    symbol['value'] <= destination < symbol['value'] + symbol['size']:
                continue
            target = dict(sec=symbol['sec'], info=3, value=0, name='')
            targets.append((offset + 1, 'direct', self.target(target, destination, 0)))
            body[offset + 1:offset + 5] = bytes(4)
        targets.sort(key=lambda r: r[0])
        return bytes(body), targets

    def functions(self):
        return {s['name']: s for s in self.symbols if s['info'] & 15 == 2 and s['size']}


HOT = re.compile(r'parse_and_dispatch|fused_pass_impl|drain_tasks|genthread_ifid_batch|'
                 r'genthread_wb_|pipeline_pass|flush_ready|collect_retire_work|'
                 r'ExLoopT.*execute|WbEngine.*serve|cmd_(?:get|set|mget|mset)(?:\(|<)')


def compare(before, after, output):
    rows = []
    for path in sorted(Path(before).rglob('*.o')):
        post = Path(after) / path.relative_to(before)
        if not post.exists():
            continue
        a, b = Elf(path), Elf(post)
        old, new = a.functions(), b.functions()
        names = list(old)
        demangled = subprocess.check_output(['c++filt'], input=('\n'.join(names) + '\n').encode())
        for name, readable in zip(names, demangled.decode().splitlines()):
            if not HOT.search(readable):
                continue
            symbol = new.get(name)
            canonical = bool(symbol) and a.canonical(old[name]) == b.canonical(symbol)
            rows.append(dict(object=str(path.relative_to(before)), symbol=name, name=readable,
                             pre_size=old[name]['size'], post_size=symbol['size'] if symbol else 0,
                             raw_equal=bool(symbol) and a.body(old[name]) == b.body(symbol),
                             relocation_equal=canonical))
    assert rows, 'no hot bodies selected'
    Path(output).write_text(json.dumps(rows, indent=2) + '\n')
    print(f"Hot bodies: {len(rows)}; raw byte equal: {sum(r['raw_equal'] for r in rows)}; "
          f"bytes + resolved relocation targets equal: {sum(r['relocation_equal'] for r in rows)}")
    for r in rows:
        if not r['relocation_equal']:
            print('DIFF', r['object'], r['pre_size'], r['post_size'], r['name'])
    return all(r['relocation_equal'] for r in rows)


def twin(source, output):
    elf = Elf(source)
    # Type A: PRE's unbounded busy-drain behavior for ordinary tail-cell clients, with the
    # candidate's exact layout. Keep all code after this entry unreachable, at the same addresses.
    matches = [s for s in elf.functions().values() if 'lb_refuse_stalled' in s['name']]
    assert len(matches) == 1, 'refusal helper must have one out-of-line body'
    symbol = matches[0]
    sec = elf.sections[symbol['sec']]
    offset = sec[4] + symbol['value'] - sec[3]
    data = bytearray(elf.data)
    if data[offset:offset + 4] == b'\xf3\x0f\x1e\xfa':
        offset += 4  # preserve CET's indirect-branch landing instruction, if present
    assert symbol['size'] >= 7
    data[offset:offset + 3] = b'\x31\xc0\xc3'  # xor eax,eax; ret
    Path(output).write_bytes(data)
    Path(output).chmod(0o755)
    print(json.dumps(dict(kind='A: behaviour twin', patched_symbol=symbol['name'],
                          file_offset=offset, bytes_changed=3, text_size_unchanged=True,
                          sha256=hashlib.sha256(data).hexdigest()), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    cmp = sub.add_parser('compare')
    cmp.add_argument('before'); cmp.add_argument('after'); cmp.add_argument('output')
    pad = sub.add_parser('twin')
    pad.add_argument('source'); pad.add_argument('output')
    args = parser.parse_args()
    if args.mode == 'compare':
        raise SystemExit(0 if compare(args.before, args.after, args.output) else 1)
    twin(args.source, args.output)
