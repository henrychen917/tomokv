"""Explain five retained strict residuals without weakening the identity tool."""
import gzip
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

spec = importlib.util.spec_from_file_location('trackfix_identity', ROOT / 'docs/trackfix/identity.py')
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
paths = [ROOT / 'build/tomokv-PRE', ROOT / 'build/tomokv']
inventories = [identity.audit.inventory(path) for path in paths]
images = [Elf(path) for path in paths]
dest = ROOT / 'docs/trackfix/identity'
summary = json.loads((dest / 'summary.json').read_text())
diffs = gzip.open(dest / 'instruction-differences.txt.gz', 'rt').read()
blocks = {part.splitlines()[0]: part for part in diffs.split('\nFUNCTION ') if part}


def read(image, address, size):
    for index, section in enumerate(image.sections):
        if section[1] != 8 and section[3] <= address and address + size <= section[3] + section[5]:
            return image.section_data(index)[address-section[3]:address-section[3]+size]
    raise AssertionError(hex(address))


def disassembly(arm, name):
    bodies = inventories[arm]['groups'][name]
    assert len(bodies) == 1
    address, size = int(bodies[0]['address'], 16), bodies[0]['size']
    text = subprocess.check_output(['objdump', '-d', '--start-address=' + hex(address),
        '--stop-address=' + hex(address + size), str(paths[arm])], text=True)
    return address, text


results = []
for row in summary['changed']:
    name = row['name']
    if 'cmd_xshard_only_impl' not in name:
        continue
    edits = [line for line in blocks[name].splitlines()
             if line.startswith(('-', '+')) and not line.startswith(('---', '+++'))]
    left = [line[1:] for line in edits if line.startswith('-')]
    right = [line[1:] for line in edits if line.startswith('+')]
    assert len(left) == len(right) == 2
    for a, b in zip(left, right):
        assert 'CSWTCH.' in a and 'CSWTCH.' in b
        assert re.sub(r'CSWTCH\.\d+', 'verified-switch-table', a) == re.sub(r'CSWTCH\.\d+', 'verified-switch-table', b)
    tables = []
    for arm in (0, 1):
        _, text = disassembly(arm, name)
        refs = re.findall(r'#\s+([0-9a-f]+)\s+<(CSWTCH\.\d+)>', text)
        assert len(refs) == 2 and len(set(refs)) == 1, refs
        address, symbol_name = int(refs[0][0], 16), refs[0][1]
        symbols = [s for s in images[arm].symbols if s['value'] == address and s['name'] == symbol_name]
        assert len(symbols) == 1 and symbols[0]['size'] > 0
        payload = read(images[arm], address, symbols[0]['size'])
        tables.append(dict(symbol=symbol_name, address=hex(address), bytes=payload.hex()))
    assert tables[0]['bytes'] == tables[1]['bytes']
    row['reason'] = ('Only two compiler switch-table label references differ in the strict report; '
                     'all normalized encodings/other instructions and the entire referenced table bytes match. '
                     'Verified independently in literal-controls.json; the strict residual is retained.')
    results.append(dict(name=name, tables=tables, status='PASS'))

name = 'void tomo::IoLoop::on_cqe<true, true, true>(io_uring_cqe*)'
targets = []
for arm in (0, 1):
    address, text = disassembly(arm, name)
    line = next(line for line in text.splitlines() if line.lstrip().startswith(f'{address + 0x16:x}:'))
    table = int(re.search(r'#\s+([0-9a-f]+)', line)[1], 16)
    offsets = struct.unpack('<18i', read(images[arm], table, 18 * 4))
    targets.append(dict(table=hex(table), target_function_offsets=[table + offset - address for offset in offsets]))
assert targets[0]['target_function_offsets'] == targets[1]['target_function_offsets']
results.append(dict(name=name, targets=targets, status='PASS'))
assert len(results) == 5
(dest / 'literal-controls.json').write_text(json.dumps(results, indent=2) + '\n')
(dest / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
(dest / 'changed-bodies.md').write_text('# Every changed linked body\n\n'
    'All 18 strict residuals remain reported. Literal controls independently verify table payloads.\n\n'
    '| Body | PRE sizes | POST sizes | Reason |\n|---|---|---|---|\n' + ''.join(
    f"| `{row['name']}` | {row['headline_sizes']} | {row['post_sizes']} | {row['reason']} |\n"
    for row in summary['changed']))
print('PASS: four multi-key dispatch tables and all 18 CQE jump targets match PRE')
