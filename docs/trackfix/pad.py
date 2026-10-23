"""PAD-A: restore PRE drop accounting within the exact POST text layout."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

pre, post, pad = [ROOT / ('build/' + name) for name in ('tomokv-PRE', 'tomokv', 'tomokv-PAD-A')]
elf = Elf(post)
data = bytearray(post.read_bytes())
patches = []
# GCC's count_if loop: load routes; AND 3; CMP 1; SBB -1 into the count.
# OR 3 makes the predicate true for every record, restoring PRE's batch->total
# count on empty/failed pub/sub reservations. records.size() == batch->total
# at this point: all records have been copied and sorted, with no erase.
# The zero-record case still adds zero to the externally visible counter.
needle = bytes.fromhex('8b500883e20383fa014883d9ff4883c0204839f075ea')
for namespace in ('tomo', 'tomo_db0'):
    mangled = f'_ZN{len(namespace)}{namespace}25notify_retire_batch_entryE'
    symbols = [s for s in elf.symbols if s['name'].startswith(mangled)
               and '.cold' not in s['name'] and s['info'] & 15 == 2]
    assert len(symbols) == 1, symbols
    symbol = symbols[0]
    section = elf.sections[symbol['sec']]
    start = section[4] + symbol['value'] - section[3]
    body = data[start:start + symbol['size']]
    assert body.count(needle) == 1, (namespace, body.count(needle))
    offset = start + body.index(needle) + 4
    assert data[offset] == 0xe2
    data[offset] = 0xca
    patches.append(dict(namespace=namespace, file_offset=offset,
                        address=hex(section[3] + offset - section[4]),
                        before='e2', after='ca', effect='count every record, as PRE'))
shutil.copy2(post, pad)
pad.write_bytes(data)
assert sum(a != b for a, b in zip(post.read_bytes(), data)) == 2


def describe(path):
    image = Elf(path)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                text_bytes=image.sections[image.names.index('.text')][5])


result = dict(kind='A: behaviour twin', scope=__doc__, padding_bytes=0,
              construction='Two one-byte predicate changes in POST; every address and size retained.',
              patches=patches, arms={name: describe(path) for name, path in
                                    [('PRE', pre), ('POST', post), ('PAD-A', pad)]})
(ROOT / 'docs/trackfix/pad.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result['arms']), flush=True)
