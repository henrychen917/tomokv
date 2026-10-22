#!/usr/bin/env python3
"""Read the actual data behind six residual labels; do not alter identity rules."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/wave4'))
import identity
from lbstall_artifacts import Elf

policy = json.loads((ROOT / 'docs/wave4c/reference-policy.json').read_text())
names = [r['name'] for r in policy if r['reference'] == 'headline']
arms = {'headline': identity.REFS['headline'], 'wave4': ROOT / 'build/wave4c/tomokv-pre'}
rows = []
for arm, path in arms.items():
    elf = Elf(path)
    inventory = identity.inventory(path)
    for name in names:
        body, = inventory['groups'][name]
        address = int(body['address'], 16)
        asm = subprocess.check_output(['objdump', '-dw', f'--start-address={address}',
            f"--stop-address={address + body['size']}", str(path)], text=True)
        data = []
        for line in asm.splitlines():
            match = re.match(r'\s*([0-9a-f]+):.*#\s+([0-9a-f]+) <(CSWTCH\.[^>]+|[^>]*kNoThread[^>]*)>', line)
            if not match:
                continue
            at, target, label = int(match[1], 16), int(match[2], 16), match[3]
            if label.startswith('CSWTCH.'):
                symbol, = [s for s in elf.symbols if s['value'] == target and
                            s['name'] == label and s['info'] & 15 == 1]
                width = symbol['size']
                assert 0 < width <= 256
            else:
                assert re.search(r'\bmov\s+[^#]*\(%rip\),%rax\s+#', line), line
                width = 8
            section, = [s for s in elf.sections if s[1] == 1 and s[2] & 2 and not s[2] & (1 | 4)
                        and s[3] <= target and target + width <= s[3] + s[5]]
            start = section[4] + target - section[3]
            data.append(dict(offset=at - address, label=label, target=hex(target),
                             width=width, bytes=elf.data[start:start + width].hex()))
        assert data, name
        rows.append(dict(arm=arm, binary_sha256=inventory['sha256'], name=name, operands=data))
for name in names:
    before, after = [r for r in rows if r['name'] == name]
    signature = lambda r: [(x['offset'], x['width'], x['bytes']) for x in r['operands']]
    assert signature(before) == signature(after), name
result = dict(scope='Data-byte diagnostic only; strict linked identity remains residual.',
              groups=len(names), same_data_bytes=True, rows=rows)
(ROOT / 'docs/wave4c/literal-proof.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS equal referenced data bytes in', len(names), 'strictly residual function groups')
