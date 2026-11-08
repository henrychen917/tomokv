#!/usr/bin/env python3
"""Build a kind-A P15 control offline: PRE probes in the exact POST ELF layout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf


def gate_bodies(path):
    bodies = {}
    current = None
    disassembly = subprocess.check_output(['objdump', '-dwC', str(path)], text=True)
    for line in disassembly.splitlines():
        symbol = re.fullmatch(r'[0-9a-f]+ <(.+)>:', line)
        if symbol:
            current = None
            if re.search(r'IoLoop::(?:wb_gather\(|(?:r7_)?flush_ready<)', symbol[1]):
                current = []
                bodies[symbol[1]] = current
        if 'call' in line and 'AofManager::reply_gate_ready(' in line:
            assert current is not None, 'unhandled IO reply gate: ' + line
        instruction = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S.*)', line)
        if current is not None and instruction:
            current.append((int(instruction[1], 16), bytes.fromhex(instruction[2]), instruction[3]))
    return {name: body for name, body in bodies.items()
            if any('call' in text and 'AofManager::reply_gate_ready(' in text for _, _, text in body)}


def offsets(path):
    # Read types only; GDB never runs or attaches to a process.
    result = {}
    for namespace in ('tomo', 'tomo_db0'):
        expressions = [f'&(({namespace}::Server*)0)->aof_',
                       f'&(({namespace}::AofManager*)0)->configured_',
                       f'&(({namespace}::AofManager*)0)->posted_sequence_']
        command = ['gdb', '-nx', '-batch', str(path)]
        for expression in expressions:
            command += ['-ex', 'p /x ' + expression]
        output = subprocess.check_output(command, text=True)
        values = [int(value, 16) for value in re.findall(r'^\$\d+ = (0x[0-9a-f]+)$', output, re.M)]
        assert len(values) == 3, output
        result[namespace] = dict(configured=values[0] + values[1], posted=values[0] + values[2])
    return result


def twin(pre, post, output):
    assert len({Path(path).resolve() for path in (pre, post, output)}) == 3
    before, after = Elf(pre), Elf(post)
    assert before.kind != 1 and after.kind != 1, 'expected linked executables'
    layouts = offsets(post)
    assert offsets(pre) == layouts, 'P15 must not change object layouts'
    old, new = gate_bodies(pre), gate_bodies(post)
    assert old.keys() == new.keys() and len(new) == 82, 'audit every linked IO gate variant'
    patched = bytearray(after.data)
    patches = []
    for name, body in new.items():
        assert re.search(r'IoLoop::(?:wb_gather\(|(?:r7_)?flush_ready<)', name), name
        namespace = 'tomo_db0' if 'tomo_db0::' in name else 'tomo'
        compare = re.compile(r'cmpb\s+\$0x0,0x%x\(%%\w+\)$' % layouts[namespace]['configured'])
        assert not any(compare.fullmatch(text) for _, _, text in old[name]), name
        matches = [index for index, (_, _, text) in enumerate(body) if compare.fullmatch(text)]
        assert len(matches) == 1, (name, matches)
        index = matches[0]
        address, raw, _ = body[index]
        branch_address, branch_raw, branch = body[index + 1]
        assert branch_address == address + len(raw) and branch_raw[:2] == b'\x0f\x85', name
        target = branch_address + 6 + struct.unpack('<i', branch_raw[2:])[0]
        assert re.match(r'jne\s+%x\s' % target, branch), branch
        # The true arm loads the local target, then tests it; compare flags are dead.
        target_index = next(i for i, (pc, _, _) in enumerate(body) if pc == target)
        assert body[target_index][2].startswith('mov') and body[target_index + 1][2].startswith('test'), name
        assert any(re.search(r'mov\s+0x%x\(' % layouts[namespace]['posted'], text)
                   for _, _, text in body), 'missing posted_sequence load: ' + name
        gate_calls = lambda instructions: sum('call' in text and 'AofManager::reply_gate_ready(' in text
                                              for _, _, text in instructions)
        assert gate_calls(old[name]) == 2 and 1 <= gate_calls(body) <= 2, name
        # Jump over the configured() comparison straight into the old unconditional
        # probe. The remaining eight bytes are unreachable padding, not extra loads.
        size = len(raw) + len(branch_raw)
        replacement = b'\xe9' + struct.pack('<i', target - address - 5) + b'\x90' * (size - 5)
        section = next(section for section in after.sections
                       if section[3] <= address < section[3] + section[5] and section[2] & 4)
        at = section[4] + address - section[3]
        original = raw + branch_raw
        assert after.data[at:at + size] == original
        patched[at:at + size] = replacement
        patches.append(dict(function=name, address=address, file_offset=at,
                            original=original.hex(), replacement=replacement.hex(), target=target))
    assert len(patched) == len(after.data)
    # Byte-for-byte identity outside the audited replacement spans.
    cursor = 0
    for patch in sorted(patches, key=lambda row: row['file_offset']):
        at = patch['file_offset']
        assert at >= cursor and patched[cursor:at] == after.data[cursor:at]
        cursor = at + len(bytes.fromhex(patch['original']))
    assert patched[cursor:] == after.data[cursor:]
    Path(output).write_bytes(patched)
    Path(output).chmod(Path(post).stat().st_mode)
    control = Elf(output)
    assert after.sections == control.sections and after.symbols == control.symbols
    return dict(kind='A: behaviour twin',
                scope='P15 PRE unconditional reply probes; S3 remains fixed',
                control='POST layout; configured guards replaced by unconditional jumps and dead padding',
                caveat='one unconditional jump per probe in PAD; no instruction-per-op claim without measurement',
                pre=str(pre), post=str(post), pad=str(output), offsets=layouts,
                pre_sha256=hashlib.sha256(before.data).hexdigest(),
                post_sha256=hashlib.sha256(after.data).hexdigest(),
                pad_sha256=hashlib.sha256(patched).hexdigest(),
                pre_text_bytes=before.sections[before.names.index('.text')][5],
                post_and_pad_text_bytes=after.sections[after.names.index('.text')][5],
                all_other_bytes_equal=True, sections_and_symbols_equal=True, patches=patches)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', help='S3-only executable, before P15')
    parser.add_argument('post')
    parser.add_argument('output')
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    receipt = twin(args.pre, args.post, args.output)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print('P15 PAD kind A: %d guards patched; identical sections, symbols and all other bytes' %
          len(receipt['patches']))
    print('POST sha256=' + receipt['post_sha256'])
    print('PAD  sha256=' + receipt['pad_sha256'])
