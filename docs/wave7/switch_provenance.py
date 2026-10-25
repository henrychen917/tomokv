"""Resolve one additional GCC switch-table form for command probe provenance.

This supplements (and does not alter) the gate's strict normalizer. The byte
reload between cmp/ja and LEA defeats its existing local-switch recognizer.
Every instruction, encoding and table destination remains compared.
"""
import bisect
import copy
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
import identity


def resolve(binary, body, pools):
    addresses = sorted(binary.instructions)
    start, size = body['addr'], body['size']
    addresses = addresses[bisect.bisect_left(addresses, start):
                          bisect.bisect_left(addresses, start + size)]
    instructions = list(body['ins'])
    tables = []
    for index in range(4, len(addresses) - 3):
        asm = [binary.instructions[a][1] for a in addresses[index-4:index+4]]
        bound = re.fullmatch(r'cmpb\s+\$0x([0-9a-f]+),(\(%r(?:di|bx)\))', asm[0])
        if not bound or not asm[2].startswith('ja '):
            continue
        # These moves preserve EFLAGS and the byte's base register. No stores,
        # calls or unknown instructions are accepted between cmp and ja.
        if re.sub(r'\s+', ' ', asm[1]) not in ('mov %rdi,%rdx', 'mov 0x8(%rdx,%rax,1),%r12'):
            continue
        if re.sub(r'\s+', ' ', asm[3]) != 'movzbl ' + bound[2] + ',%eax':
            continue
        lea = re.fullmatch(r'lea\s+-?0x[0-9a-f]+\(%rip\),%(rcx|rdx)\s+#\s+([0-9a-f]+) <[^<>]+>', asm[4])
        if not lea:
            continue
        base = lea[1]
        if [re.sub(r'\s+', ' ', a) for a in asm[5:]] != [
                f'movslq (%{base},%rax,4),%rax', f'add %{base},%rax', 'notrack jmp *%rax']:
            continue
        target, count = int(lea[2], 16), int(bound[1], 16) + 1
        assert count <= 256
        assert not any(a < target + count*4 and target < b for a, b in pools.named)
        section, = [(a, data) for a, data in pools.sections
                    if a <= target and target + count*4 <= a + len(data)]
        data = section[1][target-section[0]:target-section[0]+count*4]
        destinations = [target + x[0] for x in struct.iter_unpack('<i', data)]
        assert all(start <= x < start + size and x in binary.instructions for x in destinations)
        offsets = [x-start for x in destinations]
        label = 'verified-byte-switch-' + ','.join(hex(x) for x in offsets)
        instructions[index] = re.sub(r'# <[^<>]+>$', '# <' + label + '>', instructions[index])
        tables.append(dict(offset=addresses[index]-start, count=count, destinations=offsets))
    assert len(tables) == 1, (start, tables)
    payload = [instructions, body['encodings']]
    return dict(digest=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
                instructions=instructions, encodings=body['encodings'], tables=tables)


def inspect(path, names):
    folder = identity.ROOT / 'build/wave7/switch-provenance'
    folder.mkdir(exist_ok=True)
    binary = identity.audit.Binary(path, folder, literal_pools=True)
    nm = subprocess.check_output(['nm', '-S', '--defined-only', str(path)], text=True)
    pools = identity.audit.LiteralPools(path, nm)
    result = {name: [resolve(binary, body, pools) for body in binary.groups[name]] for name in names}
    controls = {}
    for name in names:
        body = binary.groups[name][0]
        proof = result[name][0]
        table = proof['tables'][0]
        at = body['addr'] + table['offset']
        target = int(re.search(r'#\s+([0-9a-f]+) <', binary.instructions[at][1])[1], 16)
        changed = copy.deepcopy(pools)
        replacement = next(x for x in table['destinations'] if x != table['destinations'][0])
        for i, (base, data) in enumerate(changed.sections):
            if base <= target < base + len(data):
                data = bytearray(data)
                struct.pack_into('<i', data, target-base, body['addr'] + replacement - target)
                changed.sections[i] = (base, bytes(data))
                break
        table_rejected = resolve(binary, body, changed)['digest'] != proof['digest']
        addresses = sorted(binary.instructions)
        branch = addresses[bisect.bisect_left(addresses, at)-2]
        original = binary.instructions[branch]
        assert original[1].startswith('ja ')
        binary.instructions[branch] = (original[0], original[1].replace('ja ', 'jb ', 1))
        branch_rejected = False
        try:
            resolve(binary, body, pools)
        except AssertionError:
            branch_rejected = True
        finally:
            binary.instructions[branch] = original
        assert table_rejected and branch_rejected
        controls[name] = dict(changed_case_destination=table_rejected, changed_bound_branch=branch_rejected)
    result['_negative_controls'] = controls
    for file in folder.glob('*.objdump'):
        file.unlink(missing_ok=True)
    return result
