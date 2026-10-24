#!/usr/bin/env python3
"""Resolve the six remaining strict linked hot differences; never mask instructions."""
import json
from pathlib import Path
import struct
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from lbstall_artifacts import Elf

rows = json.loads((ROOT/'docs/dispatchfix/identity/hot-linked-diffs.json').read_text())
elves = {arm:Elf(ROOT/path) for arm,path in [('PRE','build/tomokv-PRE'), ('POST','build/tomokv')]}
functions = {}
for arm,elf in elves.items():
    symbols = elf.functions()
    keys = list(symbols)
    names = subprocess.check_output(['c++filt'], input='\n'.join(keys)+'\n', text=True).splitlines()
    functions[arm] = dict(zip(names, (symbols[k] for k in keys)))

def bytes_at(elf, address, length):
    for i,section in enumerate(elf.sections):
        if section[1] != 8 and section[3] <= address and address + length <= section[3] + section[5]:
            offset = address-section[3]
            return elf.section_data(i)[offset:offset+length]
    raise AssertionError(hex(address))

proof = []
for row in rows:
    assert row['encodings_equal'], row['name']
    name = row['name']
    constant = 'prepare_local_read' in name
    # These offsets are retained in hot-linked-diffs.json and both complete
    # object inventories. Decode the actual rel32 operand at that instruction.
    offset = 0x581 if constant else (0x16 if name.startswith('void tomo::') else
                                  0x18 if '<true, false, false>' in name else 0x17)
    arms = {}
    for arm,elf in elves.items():
        function = functions[arm][name]
        instruction = bytes_at(elf, function['value']+offset, 7)
        assert instruction[0] == 0x48 and instruction[1] == (0x8b if constant else 0x8d)
        assert instruction[2] & 0xc7 == 5
        destination = function['value'] + offset + 7 + struct.unpack('<i', instruction[3:])[0]
        if constant:
            value = bytes_at(elf,destination,8).hex()
        else:
            raw = bytes_at(elf,destination,18*4)
            value = [destination + delta - function['value'] for delta in struct.unpack('<18i',raw)]
            assert all(0 <= target < function['size'] for target in value)
        arms[arm] = dict(address=hex(destination), value=value)
    assert arms['PRE']['value'] == arms['POST']['value'], (name,arms)
    proof.append(dict(name=name, opcodes_and_nonaddress_operands_equal=True,
                      kind='constant pool: 8 identical bytes' if constant else '18 identical jump destinations within the unchanged body',
                      arms=arms))
(ROOT/'docs/dispatchfix/identity/hot-relocations.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS:',len(proof),'hot bodies differ only in resolved constant/table placement; all data and destinations agree')
