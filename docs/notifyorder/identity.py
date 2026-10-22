#!/usr/bin/env python3
"""Conservative complete-body inventory, including parser and reply hot paths."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf, HOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, objects = [], []
    paths = sorted(list((args.pre / 'src').rglob('*.o')) + list((args.pre / 'db0/src').rglob('*.o')))
    for path in paths:
        rel = path.relative_to(args.pre)
        before, after = Elf(path), Elf(args.post / rel)
        old, new = before.functions(), after.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
        unit = []
        for symbol, name in zip(names, labels):
            a, b = old.get(symbol), new.get(symbol)
            ac = before.canonical(a) if a else None
            bc = after.canonical(b) if b else None
            row = dict(object=str(rel), symbol=symbol, name=name,
                       pre_size=a['size'] if a else 0, post_size=b['size'] if b else 0,
                       raw_equal=bool(a and b and before.body(a) == after.body(b)),
                       relocation_equal=bool(a and b and ac == bc))
            if not row['relocation_equal']:
                at = {repr(t[2:]) for t in ac[1]} if ac else set()
                bt = {repr(t[2:]) for t in bc[1]} if bc else set()
                row.update(code_targets_removed=sorted(at-bt), code_targets_added=sorted(bt-at))
            unit.append(row)
        objects.append(dict(object=str(rel), functions=len(unit), changed=sum(not r['relocation_equal'] for r in unit)))
        rows.extend(unit)
    hot = [r for r in rows if HOT.search(r['name']) or
           re.search(r'resp_|reply_line_text|parse_len_crlf|ExLoopT<.*>::run\(', r['name'])]
    changed = [r for r in rows if not r['relocation_equal']]
    summary = dict(objects=len(objects), functions=len(rows), changed=len(changed),
                   hot=len(hot), hot_equal=sum(r['relocation_equal'] for r in hot),
                   hot_raw_equal=sum(r['raw_equal'] for r in hot),
                   changed_objects=dict(Counter(r['object'] for r in changed)))
    for arm, folder in [('PRE', args.pre), ('POST', args.post)]:
        binary = Elf(folder / 'tomokv')
        summary[arm] = dict(sha256=hashlib.sha256(binary.data).hexdigest(),
                           text_bytes=binary.sections[binary.names.index('.text')][5])
    for name, content in [('objects', objects), ('hot-bodies', hot), ('changed-bodies', changed), ('summary', summary)]:
        (args.output / (name+'.json')).write_text(json.dumps(content, indent=2)+'\n')
    print(json.dumps(summary, indent=2))
    # Identity differences are evidence to review, never a reason to stop the lane.


if __name__ == '__main__':
    main()
