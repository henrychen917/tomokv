#!/usr/bin/env python3
"""Remove unit/control DWARF after correctness, retaining every allocated byte.

Keep POST, PAD-A, rebuilt PRE and the four command-scope probe executables
unchanged. Object prerequisites stay intact, so freshness is checked normally.
"""
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
out = ROOT / 'docs/wave7'
summary = json.loads((out / 'correctness/summary.json').read_text())
assert not summary['pending'], summary['pending']
assert any(r['name'] == 'merged-sweep-final' for r in summary['selections'])
keep = {ROOT / 'build/tomokv', ROOT / 'build/tomokv-wave7-PAD-A',
        ROOT / 'build/wave7/pre-source/build/tomokv'}
keep.update((ROOT / 'build/wave7/commands').glob('*/probe'))
inodes = {(p.stat().st_dev, p.stat().st_ino) for p in keep}
def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(keep)}
def allocated(path):
    with path.open('rb') as source:
        header = source.read(64)
        offset = struct.unpack_from('<Q', header, 40)[0]
        size, number = struct.unpack_from('<HH', header, 58)
        source.seek(offset)
        headers = source.read(size * number)
        rows = []
        for index in range(number):
            section = struct.unpack_from('<IIQQQQIIQQ', headers, index * size)
            if not section[2] & 2:
                continue
            digest = None
            if section[1] != 8:
                source.seek(section[4])
                digest = hashlib.sha256(source.read(section[5])).hexdigest()
            rows.append((section[1], section[2], section[3], section[5], section[8], digest))
        return rows

before = hashes()
rows = []
for path in sorted((ROOT / 'build').rglob('*')):
    if not path.is_file() or path.is_symlink():
        continue
    if (path.stat().st_dev, path.stat().st_ino) in inodes:
        continue
    with path.open('rb') as source:
        header = source.read(20)
    if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[16:18], 'little') not in (2, 3):
        continue
    size = path.stat().st_size
    image = allocated(path)
    subprocess.run(['strip', '--strip-debug', str(path)], check=True)
    assert image == allocated(path), ('allocated section changed', path)
    rows.append(dict(path=str(path.relative_to(ROOT)), before=size,
                     after=path.stat().st_size, allocated_equal=True))
after = hashes()
assert before == after, 'protected executable changed'
build = json.loads((out / 'build/receipt.json').read_text())
env = dict(os.environ, LANG='en_US.UTF-8')
env.pop('LC_ALL', None)
freshness = []
for check in build['freshness']:
    result = subprocess.run(check['command'], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    freshness.append(dict(command=check['command'], exit=result.returncode, output=result.stdout))
receipt = dict(protected_before=before, protected_after=after, stripped=rows,
               bytes_saved=sum(row['before'] - row['after'] for row in rows), freshness=freshness)
(out / 'lean-build.json').write_text(json.dumps(receipt, indent=2) + '\n')
assert all(row['exit'] == 0 for row in freshness), freshness
print('unit/control executables', len(rows), 'bytes saved', receipt['bytes_saved'],
      'freshness checks', len(freshness), 'protected binaries unchanged')
