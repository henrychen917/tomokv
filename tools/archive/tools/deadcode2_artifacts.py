#!/usr/bin/env python3
"""Serverless, complete object-function inventory for the deadcode2 cleanup.

Keep literal byte equality separate from equality after resolving relocations.
No opcode, immediate, register, branch, missing symbol or clone is ignored.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from lbstall_artifacts import Elf


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(pre, post, output):
    objects = []
    changed = []
    paths = {p.relative_to(root) for root in (pre, post) for ns in ('src', 'db0/src')
             for p in (root / ns).rglob('*.o')}
    for rel in sorted(paths):
        assert (pre / rel).is_file() and (post / rel).is_file(), f'unmatched object: {rel}'
        a, b = Elf(pre / rel), Elf(post / rel)
        before, after = a.functions(), b.functions()
        names = sorted(before.keys() | after.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
        raw_count = same_count = 0
        for name, label in zip(names, labels):
            old, new = before.get(name), after.get(name)
            raw = bool(old and new) and a.body(old) == b.body(new)
            same = bool(old and new) and a.canonical(old) == b.canonical(new)
            raw_count += raw
            same_count += same
            if not same:
                changed.append(dict(object=str(rel), symbol=name, name=label,
                                    pre_size=old['size'] if old else None,
                                    post_size=new['size'] if new else None,
                                    raw_equal=raw, relocation_equal=False,
                                    pre_bytes_sha256=digest(a.body(old)) if old else None,
                                    post_bytes_sha256=digest(b.body(new)) if new else None))
        objects.append(dict(object=str(rel), bodies=len(names), raw_equal=raw_count,
                            relocation_equal=same_count))
        print(f'{rel}: {same_count}/{len(names)} resolved bodies equal', flush=True)
    assert objects, 'empty object inventory'
    result = dict(pre=str(pre), post=str(post), objects=objects, changed=changed,
                  comparison='literal opcodes and bytes; relocation operands resolve to target identity',
                  bodies=sum(r['bodies'] for r in objects),
                  raw_equal=sum(r['raw_equal'] for r in objects),
                  relocation_equal=sum(r['relocation_equal'] for r in objects))
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(f"ALL: {result['relocation_equal']}/{result['bodies']} resolved bodies equal; "
          f"{len(changed)} changed/added/deleted")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    audit(args.pre, args.post, args.output)
