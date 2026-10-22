#!/usr/bin/env python3
"""Offline kind-A writeback behaviour twin for the nominated merit cells.

Restore PRE's positive-work result whenever a connection is deferred, without
moving any POST instruction, function, constant, relocation, or ELF section.
This is a scoped control: hz/DEBUG/SIGNAL administrative surfaces remain POST.
The merit cells use the default 10 Hz and 512 clients, and issue no DEBUG SLEEP
or signal-stop-with-save request. This is not a full four-feature PRE binary.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import subprocess

from lbstall_artifacts import Elf


def sha(data):
    return hashlib.sha256(data).hexdigest()


def work_ranges(binary, line):
    command = ['readelf', '--debug-dump=decodedline', str(binary)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    previous = None
    ranges = []
    for text in process.stdout:
        if text.startswith('CU:'):
            previous = None
        match = re.match(r'^(\S+)\s+(\d+|-)\s+(0x[0-9a-f]+)\b', text)
        if not match:
            continue
        current = match[1], match[2], int(match[3], 16)
        if previous and previous[:2] == ('wb_rule.h', str(line)):
            if previous[2] < current[2]:
                ranges.append((previous[2], current[2]))
        previous = None if current[1] == '-' else current
    assert process.wait() == 0
    return sorted(set(ranges))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--post', type=Path, default=Path('build/tomokv'))
    p.add_argument('--pre', type=Path, default=Path('build/tomokv-pre'))
    p.add_argument('--output', type=Path, default=Path('build/tomokv-pad-a'))
    p.add_argument('--receipt', type=Path, default=Path('docs/iofix/pad-a.json'))
    args = p.parse_args()
    assert args.post.resolve() != args.output.resolve()
    source = Path('src/core/wb_rule.h').read_text().splitlines()
    lines = [i + 1 for i, text in enumerate(source)
             if 'work += c->wb_deferrals() != previous_deferrals;' in text]
    assert len(lines) == 1, 'review the exact work predicate before constructing this control'
    original = subprocess.check_output(['git', 'show', 'a7dfb9d23:src/core/wb_rule.h'], text=True)
    assert 'if (!loop.pending_serve_.empty()) ++work;' in original
    elf = Elf(args.post)
    index = elf.names.index('.text')
    section = elf.sections[index]
    ranges = [(a, b) for a, b in work_ranges(args.post, lines[0])
              if section[3] <= a < b <= section[3] + section[5]]
    starts = [a for a, _ in ranges]
    process = subprocess.Popen(['objdump', '-dw', str(args.post)], stdout=subprocess.PIPE, text=True)
    patches = []
    bodies = [s for s in elf.symbols if s['info'] & 15 == 2 and s['sec'] == index and s['size']]
    for text in process.stdout:
        match = re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)', text)
        if not match:
            continue
        address = int(match[1], 16)
        at = bisect.bisect_right(starts, address) - 1
        if at < 0 or address >= ranges[at][1] or not match[3].startswith('setne'):
            continue
        before = bytes.fromhex(match[2])
        assert before == bytes.fromhex('0f 95 c0') and match[3].strip() == 'setne  %al', text
        owners = [s for s in bodies if s['value'] <= address < s['value'] + s['size']]
        assert owners and all('flush_ready' in s['name'] for s in owners), owners
        # cmp still executes; force its boolean result to one. Flags are unchanged.
        # xor eax,eax precedes this sequence; AL=1 therefore adds exactly one work unit.
        patches.append(dict(address=address, file_offset=section[4] + address - section[3],
                            before=before.hex(), after='b00190',
                            functions=[s['name'] for s in owners]))
    assert process.wait() == 0
    assert len(patches) >= 32 and len({p['address'] for p in patches}) == len(patches)
    touched = {name for patch in patches for name in patch['functions']}
    # Every linked FIFO/R7 flush_ready specialization carrying the source predicate is covered.
    expected = {s['name'] for s in bodies if 'flush_ready' in s['name'] and
                any(s['value'] <= a < s['value'] + s['size'] for a, _ in ranges)}
    assert touched == expected, ('missing or extra predicate sites', expected - touched, touched - expected)
    data = bytearray(elf.data)
    for patch in patches:
        offset = patch['file_offset']
        assert data[offset:offset + 3].hex() == patch['before']
        data[offset:offset + 3] = bytes.fromhex(patch['after'])
    args.output.write_bytes(data)
    args.output.chmod(0o755)
    twin = Elf(args.output)
    assert elf.sections == twin.sections and elf.symbols == twin.symbols
    assert len(elf.data) == len(twin.data)
    allowed = {p['file_offset'] + i for p in patches for i in range(3)}
    differences = [i for i, (a, b) in enumerate(zip(elf.data, twin.data)) if a != b]
    assert set(differences) == allowed
    receipt = dict(kind='A: scoped PRE deferred-work behaviour with exact POST ELF/text layout',
                   scope='nominated 512-client merit cells, default hz, no DEBUG SLEEP or signal-save operation',
                   limitation='hz, DEBUG SLEEP and signal-stop admin behaviour remains POST; not a full four-feature PRE twin',
                   pre_sha256=sha(args.pre.read_bytes()), post_sha256=sha(elf.data),
                   pad_sha256=sha(twin.data), post_text_bytes=section[5], pad_text_bytes=section[5],
                   all_sections_and_symbol_addresses_sizes_equal=True,
                   bytes_changed=len(differences), functions_patched=len(touched), patches=patches)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'patches'}, indent=2))


if __name__ == '__main__':
    main()
