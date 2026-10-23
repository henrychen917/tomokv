"""Verify the exact-layout PAD-A restores PRE's count-all predicate."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

post = ROOT / 'build/tomokv'
pad = ROOT / 'build/tomokv-PAD-A'
left, right = post.read_bytes(), pad.read_bytes()
receipt = json.loads((ROOT / 'docs/trackfix/pad.json').read_text())
assert len(left) == len(right)
changes = [index for index, (a, b) in enumerate(zip(left, right)) if a != b]
assert changes == sorted(row['file_offset'] for row in receipt['patches'])
assert len(changes) == 2 and all(left[i] == 0xe2 and right[i] == 0xca for i in changes)
a, b = Elf(post), Elf(pad)
assert a.sections == b.sections and a.symbols == b.symbols
evidence = []
for row in receipt['patches']:
    address = int(row['address'], 16) - 4
    output = subprocess.check_output(['objdump', '-d', '--start-address=' + hex(address),
        '--stop-address=' + hex(address + 24), str(pad)], text=True)
    assert 'or     $0x3,%edx' in output and 'sbb    $0xffffffffffffffff,%rcx' in output
    evidence.append(output)
result = dict(status='PASS', all_post_bytes_equal_except_two_predicate_bytes=True,
              post_sections_symbols_addresses_sizes_identical=True, disassembly=evidence)
(ROOT / 'docs/trackfix/identity/pad-layout.json').write_text(json.dumps(result, indent=2) + '\n')
print('PAD-A: exact POST layout; two predicates count every record as PRE')
