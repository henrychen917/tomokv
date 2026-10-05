#!/usr/bin/env python3
"""Cold-body inventory using lbstall's canonicalizer (also supports ELF TLS relocation 23)."""
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap
sys.path.insert(0, 'tools')
import lbstall_artifacts as audit
source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count('24: 8,') == 1
scope = vars(audit).copy()
exec(source.replace('24: 8,', '23: 4, 24: 8,'), scope)
audit.Elf.canonical = scope['canonical']


def changed(before, after):
    a, b = audit.Elf(before), audit.Elf(after)
    old, new = a.functions(), b.functions()
    names = sorted(old.keys() | new.keys())
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    rows = []
    for name, label in zip(names, labels):
        if name not in old or name not in new or a.canonical(old[name]) != b.canonical(new[name]):
            rows.append(dict(symbol=name, name=label, pre_size=old.get(name, {}).get('size', 0),
                             post_size=new.get(name, {}).get('size', 0),
                             raw_equal=name in old and name in new and a.body(old[name]) == b.body(new[name])))
    return rows


if __name__ == '__main__':
    if len(sys.argv) == 3:
        rows = changed(*sys.argv[1:])
        for row in rows:
            if not any(term in row['name'] for term in ('multi_', 'Multi', 'command_metadata_no_multi')):
                print(json.dumps(row), flush=True)
        print(len(rows), 'total changed functions')
    else:
        rows, objects = [], []
        pre = Path('build/at15-pre')
        for path in sorted(pre.rglob('*.o')):
            rel = path.relative_to(pre)
            post = Path('build') / rel
            if path.read_bytes() == post.read_bytes():
                continue
            objects.append(str(rel))
            for row in changed(path, post):
                row['object'] = str(rel)
                rows.append(row)
                print(json.dumps(row), flush=True)
        for path in sorted(list(Path('build/src').rglob('*.o')) + list(Path('build/db0/src').rglob('*.o'))):
            rel = path.relative_to('build')
            if (pre / rel).exists():
                continue
            objects.append(str(rel))
            functions = audit.Elf(path).functions()
            names = sorted(functions)
            labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
            for name, label in zip(names, labels):
                rows.append(dict(object=str(rel), symbol=name, name=label, pre_size=0,
                                 post_size=functions[name]['size'], added_object=True))
        Path('docs/at15/changed-objects.json').write_text(json.dumps(objects, indent=2) + '\n')
        Path('docs/at15/changed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(len(objects), 'changed objects;', len(rows), 'changed function bodies')
        assert not any('xshard_plain_prepare' in r['name'] and not r.get('added_object') for r in rows), \
            'ordinary write-preparation body changed'
