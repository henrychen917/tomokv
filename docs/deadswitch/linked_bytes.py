#!/usr/bin/env python3
"""Compare every loadable ELF section, excluding only the build-id note. No execution."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from lbstall_artifacts import Elf


def inventory(path):
    elf = Elf(path)
    rows = {}
    for i, (name, section) in enumerate(zip(elf.names, elf.sections)):
        if not section[2] & 2:
            continue
        rows[name] = dict(type=section[1], flags=section[2], address=section[3],
                          size=section[5], alignment=section[8],
                          sha256=None if section[1] == 8 else
                          hashlib.sha256(elf.section_data(i)).hexdigest())
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    before, after = inventory(a.pre), inventory(a.post)
    rows = [dict(section=name, pre=before.get(name), post=after.get(name),
                 equal=before.get(name) == after.get(name))
            for name in sorted(before.keys() | after.keys())]
    differences = [r['section'] for r in rows
                   if not r['equal'] and r['section'] != '.note.gnu.build-id']
    result = dict(pre=str(a.pre), post=str(a.post),
                  pre_sha256=hashlib.sha256(a.pre.read_bytes()).hexdigest(),
                  post_sha256=hashlib.sha256(a.post.read_bytes()).hexdigest(),
                  runtime_sections_equal=not differences, differences=differences,
                  sections=rows)
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'sections'}))
    return bool(differences)


if __name__ == '__main__':
    raise SystemExit(main())
