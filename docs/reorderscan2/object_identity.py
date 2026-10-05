from pathlib import Path
import json
import sys
sys.path.insert(0, 'tools')
from lbstall_artifacts import Elf, compare
root = Path.cwd()
out = root / 'build/reorderscan2-evidence'
pre = root / 'build/reorderscan-pre2'
post = root / 'build'
rows = []
for path in sorted(pre.rglob('*.o')):
    rel = path.relative_to(pre)
    if rel.as_posix().endswith('src/core/reorder.o'):
        continue
    other = post / rel
    a, b = Elf(path), Elf(other)
    def sections(elf):
        return {name: elf.section_data(i) for i, (name, section) in enumerate(zip(elf.names, elf.sections)) if section[2] & 4}
    old, new = sections(a), sections(b)
    row = dict(object=str(rel), executable_sections=len(old), bytes=sum(map(len, old.values())), raw_equal=old == new)
    rows.append(row)
    for arm, source in (('pre', path), ('post', other)):
        target = out / 'objects' / arm / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink(): target.unlink()
        target.symlink_to(source)
(out / 'non-r7-sections.json').write_text(json.dumps(rows, indent=2) + '\n')
assert len(rows) == 84, len(rows)
assert all(row['raw_equal'] for row in rows), [r for r in rows if not r['raw_equal']]
print('PASS 84/84 non-R7 TUs:', sum(r['executable_sections'] for r in rows), 'executable sections,', sum(r['bytes'] for r in rows), 'bytes identical', flush=True)
assert compare(out / 'objects/pre', out / 'objects/post', out / 'non-r7-hot.json')
hot = json.loads((out / 'non-r7-hot.json').read_text())
assert len(hot) == 1221 and all(r['raw_equal'] and r['relocation_equal'] for r in hot)
print('PASS 1221/1221 hot bodies: raw bytes and relocation targets identical', flush=True)
