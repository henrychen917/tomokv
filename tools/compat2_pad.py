#!/usr/bin/env python3
"""PAD kind A: restore PRE behavior in POST's exact ELF section/symbol layout.

Disable the new arity helper, use the old ACL denial spelling, restore QUIT's
local bound, bypass the versioned-notification guard, and defer TLS release to
the existing reap_dead call. No addresses, section sizes or instruction lengths
change. Every patch is checked against decoded instructions and symbol counts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('post', type=Path)
    p.add_argument('pad', type=Path)
    p.add_argument('receipt', type=Path)
    p.add_argument('--unit', action='store_true')
    a = p.parse_args()
    original = a.post.read_bytes()
    data = bytearray(original)
    assert data[:6] == b'\x7fELF\x02\x01'
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize) for i in range(phnum)]

    def offset(address, size):
        found = [q[2] + address - q[3] for q in loads
                 if q[0] == 1 and q[3] <= address and address + size <= q[3] + q[5]]
        assert len(found) == 1, (address, size)
        return found[0]

    patches = []
    def patch(address, replacement, reason, symbol):
        at = offset(address, len(replacement))
        before = bytes(data[at:at + len(replacement)])
        assert before != replacement
        data[at:at + len(replacement)] = replacement
        patches.append(dict(address=hex(address), offset=at, before=before.hex(),
                            after=replacement.hex(), reason=reason, symbol=symbol))

    symbols = subprocess.check_output(['nm', '-SC', str(a.post)], text=True)
    counts = dict(arity=0, noauth=0, notification=0, tls=0, acl_name=0, acl_exec=0, quit=0)
    if not a.unit:
        for line in symbols.splitlines():
            match = re.match(r'([0-9a-f]+) ([0-9a-f]+) [tTWw] (.*)', line)
            if not match or '[clone .cold]' in match[3]:
                continue
            name, address = match[3], int(match[1], 16)
            if '::auth_noauth_error(' in name:
                literals = []
                for q in loads:
                    if q[0] != 1:
                        continue
                    at = original.find(b'NOAUTH Authentication required.\0', q[2], q[2] + q[5])
                    if at >= 0:
                        literals.append(q[3] + at - q[2])
                assert literals and int(match[2], 16) >= 8
                patch(address, b'\x48\x8d\x05' + struct.pack('<i', literals[0] - address - 7) + b'\xc3',
                      'NOAUTH: return PRE prefix after the unchanged output-limit check', name)
                counts['noauth'] += 1
            kind = ('arity' if '::auth_arity_reply(' in name else
                    'notification' if '::notify_read_resolves_versions()' in name else None)
            if kind:
                assert int(match[2], 16) >= 3
                patch(address, bytes.fromhex('31c0c3'), kind + ': return false', name)
                counts[kind] += 1
    disassembly = subprocess.check_output(['objdump', '-dC', str(a.post)], text=True)
    symbol = ''
    history = []
    for line in disassembly.splitlines():
        head = re.match(r'^[0-9a-f]+ <(.*)>:$', line)
        if head:
            symbol, history = head[1], []
            continue
        instruction = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if not instruction:
            continue
        address, raw, text = int(instruction[1], 16), bytes.fromhex(instruction[2]), instruction[3]
        if '::IoLoop::close_client(' in symbol and 'call' in text and '::IoLoop::release_tls(' in text:
            assert len(raw) == 5 and raw[0] == 0xe8
            patch(address, b'\x90' * 5, 'TLS: retain sidecar until reap_dead', symbol)
            counts['tls'] += 1
        if not a.unit and '::(anonymous namespace)::acl_reply_denied(' in symbol and 'call' in text:
            kind = None
            if '::command_metadata_resolve(' in text:
                kind = 'acl_name'
            elif '::Slice::eq_icase(' in text and any(
                    re.search(r'mov\s+\$0x4,%edx', old) for old in history[-3:]):
                kind = 'acl_exec'
            if kind:
                assert len(raw) == 5 and raw[0] == 0xe8
                patch(address, bytes.fromhex('31c0909090'), kind + ': use PRE fallback', symbol)
                counts[kind] += 1
        if (not a.unit and symbol.startswith('_GLOBAL__sub_I_') and
                'debug_sleep_prepare' in symbol and '::kTable+0x1e8>' in text):
            # QUIT is table entry 10. Its constructor stores the packed min/max
            # from RSI (1,-1). RDX still holds (1,1) for RESET/SAVE/LASTSAVE.
            # Check that defining load and every intervening register write.
            assert len(raw) == 7 and raw[:3] == bytes.fromhex('488935'), text
            writes = [old for old in history if re.search(r',%[er]dx$', old.split('#')[0].strip())]
            assert writes, history
            load = re.search(r'mov\s+.*\(%rip\),%rdx\s+# ([0-9a-f]+)', writes[-1])
            assert load, writes[-1]
            at = offset(int(load[1], 16), 8)
            assert original[at:at+8] == struct.pack('<ii', 1, 1)
            replacement = bytes.fromhex('488915') + raw[3:]
            patch(address, replacement, 'QUIT: initialize PRE bounds (1,1)', symbol)
            counts['quit'] += 1
        history.append(text)
    if not a.unit:
        assert counts == dict(arity=2, noauth=2, notification=4, tls=2, acl_name=2, acl_exec=2, quit=2), counts
    else:
        assert counts['tls'] == 1, counts
    assert len(data) == len(original)
    a.pad.write_bytes(data)
    a.pad.chmod(a.post.stat().st_mode)
    a.receipt.write_text(json.dumps(dict(kind='A: PRE behavior in POST layout', counts=counts,
        changed_bytes=sum(x != y for x, y in zip(original, data)), patches=patches,
        post_sha256=hashlib.sha256(original).hexdigest(), pad_sha256=hashlib.sha256(data).hexdigest()),
        indent=2) + '\n')
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
